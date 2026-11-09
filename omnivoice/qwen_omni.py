"""Qwen3-Omni MLX + keyless public tools.

Pipeline:
  1. user asks (text, or audio -- Whisper-transcribed or fed natively)
  2. model emits <tool_call>{"name": ...}</tool_call>
  3. public_tools.execute_tool() calls a free, keyless API
  4. model gets the tool result and speaks the answer

All tool implementations live in public_tools.py. This module only handles the
Qwen3-Omni MLX model: prompt preparation, generation, and audio output.

Usage:
  python -m omnivoice.qwen_omni --mode text --question "..."
  python -m omnivoice.qwen_omni --mode audio --audio assets/samples/test_en.wav
  python -m omnivoice.qwen_omni --mode audio --native-audio --audio assets/samples/test_en.wav
"""

import argparse
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import mlx_whisper
import numpy as np
import soundfile as sf
from mlx_vlm import load
from mlx_vlm.models.qwen3_omni_moe.omni_utils import load_audio, process_multimodal_info

from .public_tools import TOOLS, execute_tool
from .utils import extract_assistant, parse_tool_call, trim_trailing_silence

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = str(ROOT / "models" / "Qwen3-Omni-30B-A3B-Instruct-4bit")


def prepare_inputs(processor, conversation, tools=TOOLS, use_audio_in_video=False):
    """Same as omni_utils.prepare_omni_inputs, but passes tools to the template."""
    audios, images, videos = process_multimodal_info(conversation, use_audio_in_video)
    text = processor.apply_chat_template(
        conversation, tools=tools, add_generation_prompt=True, tokenize=False
    )
    loaded_audios = []
    if audios:
        sr = processor.feature_extractor.sampling_rate
        for audio_path in audios:
            loaded_audios.append(load_audio(audio_path, sr=sr))
    inputs = processor(
        text=[text],
        audio=loaded_audios if loaded_audios else None,
        images=images if images else None,
        videos=videos if videos else None,
        return_tensors="pt",
        padding=True,
        use_audio_in_video=use_audio_in_video,
    )
    model_inputs = {}
    for k, v in inputs.items():
        if hasattr(v, "numpy"):
            model_inputs[k] = mx.array(v.numpy())
        elif isinstance(v, np.ndarray):
            model_inputs[k] = mx.array(v)
        else:
            model_inputs[k] = v
    # audio_feature_lengths: sample-domain mask -> mel-frame count (see mlx-vlm #1620)
    if "feature_attention_mask" in model_inputs and "audio_feature_lengths" not in model_inputs:
        mask = model_inputs["feature_attention_mask"]
        lengths = mask.sum(axis=1)
        input_features = model_inputs.get("input_features")
        if input_features is not None:
            mel_frames = input_features.shape[-1]
            mask_len = mask.shape[-1]
            if mask_len > mel_frames:
                lengths = lengths // (mask_len // mel_frames)
        model_inputs["audio_feature_lengths"] = lengths.astype(mx.int32)
    return model_inputs, text


def generate(
    model,
    processor,
    conversation,
    return_audio,
    max_new_thinker=256,
    max_new_talker=1024,
    talker_do_sample=False,
    talker_temperature=0.0,
    speaker="Ethan",
    tools=TOOLS,
):
    inputs, rendered = prepare_inputs(processor, conversation, tools=tools)
    kwargs = {
        "input_ids": inputs["input_ids"],
        "pixel_values": inputs.get("pixel_values"),
        "pixel_values_videos": inputs.get("pixel_values_videos"),
        "image_grid_thw": inputs.get("image_grid_thw"),
        "video_grid_thw": inputs.get("video_grid_thw"),
        "input_features": inputs.get("input_features"),
        "feature_attention_mask": inputs.get("feature_attention_mask"),
        "audio_feature_lengths": inputs.get("audio_feature_lengths"),
        "thinker_max_new_tokens": max_new_thinker,
        "talker_max_new_tokens": max_new_talker,
        "talker_do_sample": talker_do_sample,
        "talker_temperature": talker_temperature,
        "return_audio": return_audio,
        "speaker": speaker,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    t = time.time()
    result, audio = model.generate(**kwargs)
    elapsed = time.time() - t
    text = extract_assistant(processor.decode(result.sequences[0].tolist()))
    return text, audio, elapsed, rendered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["text", "audio"], default="text")
    ap.add_argument("--question", default="What is the weather like in Tokyo today?")
    ap.add_argument("--audio", default="test_5s.wav")
    ap.add_argument("--speaker", default="Ethan")
    ap.add_argument("--out", default="weather_output.wav")
    ap.add_argument("--max-thinker", type=int, default=256)
    ap.add_argument("--max-talker", type=int, default=384)
    ap.add_argument(
        "--long",
        action="store_true",
        help="Allow two sentences (Talker may miss EOS; one sentence is the reliable default)",
    )
    ap.add_argument("--sample", action="store_true", help="Enable Talker sampling (less stable)")
    ap.add_argument(
        "--native-audio",
        action="store_true",
        help="Feed audio directly to Qwen3-Omni instead of transcribing first",
    )
    ap.add_argument("--asr-model", default="mlx-community/whisper-small.en-mlx")
    args = ap.parse_args()

    if args.long:
        STYLE = " Answer in plain spoken English, one or two short sentences. No markdown, no lists, no bullet points."
    else:
        STYLE = " Answer in one short spoken sentence. No markdown, no lists, no bullet points."
    talker_kwargs = dict(
        talker_do_sample=args.sample,
        talker_temperature=0.9 if args.sample else 0.0,
    )

    instruction = (
        "Chat naturally. Call a tool only when the user asks for live or factual data." + STYLE
    )

    if args.mode == "audio":
        if args.native_audio:
            print(f"native audio input: {args.audio}")
            user_content = [
                {"type": "audio", "audio": args.audio},
                {"type": "text", "text": "Answer the question in the audio. " + instruction},
            ]
        else:
            print(f"transcribing {args.audio} with {args.asr_model} ...")
            t_asr = time.time()
            transcript = mlx_whisper.transcribe(
                args.audio,
                path_or_hf_repo=args.asr_model,
                condition_on_previous_text=False,
            )["text"].strip()
            print(f"({time.time() - t_asr:.1f}s) transcript: {transcript!r}")
            user_content = transcript + " " + instruction
    else:
        user_content = args.question + STYLE

    conversation = [{"role": "user", "content": user_content}]

    print("loading model...")
    t0 = time.time()
    model, processor = load(MODEL_PATH, trust_remote_code=True)
    print(f"loaded in {time.time() - t0:.1f}s")

    # Turn 1: text-only, let the model decide whether to call the tool.
    print("\n--- turn 1: tool decision ---")
    text1, _, dt1, _ = generate(
        model,
        processor,
        conversation,
        return_audio=False,
        max_new_thinker=args.max_thinker,
        max_new_talker=args.max_talker,
    )
    print(f"({dt1:.1f}s) {text1}")

    call = parse_tool_call(text1)
    if not call:
        print("\nNo tool call emitted; returning the model's direct answer.")
        final_text, audio, dt2, _ = generate(
            model,
            processor,
            conversation,
            return_audio=True,
            max_new_thinker=args.max_thinker,
            max_new_talker=args.max_talker,
            speaker=args.speaker,
            **talker_kwargs,
        )
        print(f"({dt2:.1f}s) {final_text}")
    else:
        print(f"\n--- tool call: {call['name']}({call['arguments']}) ---")
        result = execute_tool(call)
        print("--- tool result ---")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        conversation += [
            {"role": "assistant", "content": text1},
            {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
        ]

        # Turn 2: final spoken answer grounded in the tool result.
        print("\n--- turn 2: spoken answer ---")
        final_text, audio, dt2, _ = generate(
            model,
            processor,
            conversation,
            return_audio=True,
            max_new_thinker=args.max_thinker,
            max_new_talker=args.max_talker,
            speaker=args.speaker,
            **talker_kwargs,
        )
        print(f"({dt2:.1f}s) {final_text}")

    if audio is None:
        print("\nNo audio generated.")
        return 1

    wav = np.array(audio.reshape(-1) if hasattr(audio, "reshape") else audio)
    raw_dur = len(wav) / 24000
    wav = trim_trailing_silence(wav, 24000)
    sf.write(args.out, wav, samplerate=24000)
    dur = len(wav) / 24000
    trimmed = raw_dur - dur
    note = f" (trimmed {trimmed:.2f}s silence)" if trimmed > 0.05 else ""
    print(f"\nsaved {args.out}: {dur:.2f}s @ 24kHz, peak={np.abs(wav).max():.4f}{note}")
    try:
        print(f"peak MLX memory: {mx.get_peak_memory() / 1e9:.1f} GB")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
