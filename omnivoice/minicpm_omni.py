"""MiniCPM-o 4.5 (MLX 4-bit) text / audio / speech pipeline.

The `andrevp/MiniCPM-o-4_5-MLX-4bit` checkpoint keeps the official PyTorch
names (`vision_tower.encoder_layers`, `audio_encoder`) while mlx-vlm 0.7.x
expects `vision_tower.encoder.layers` and `audio_tower`.  We remap those two
prefixes at load time.  The checkpoint also has native TTS weights.

MiniCPM's TTS template expects the model to close a spoken turn with
`<|tts_eos|>`; after a tool response it often emits `<|im_end|>` instead, so we
swap the final token before handing the sequence to the vocoder.
"""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
import soundfile as sf
from mlx_vlm import generate, generate_audio, load
from mlx_vlm.models.minicpmo.minicpmo import Model
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config

from .prompts import INSTRUCTION_EN, INSTRUCTION_ZH, ROUTER_EN, ROUTER_ZH
from .public_tools import execute_tool, select_tools
from .routing import resolve_decision
from .utils import language_of, trim_trailing_silence

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = str(ROOT / "models" / "MiniCPM-o-4_5-MLX-4bit")
REF_ZH = str(ROOT / "assets" / "voices" / "ref_zh.wav")
REF_EN = str(ROOT / "assets" / "voices" / "ref_en.wav")

_patched = False
_state: dict = {}


def _patch_model_class():
    """Apply checkpoint-name and TTS-marker compatibility fixes once."""
    global _patched
    if _patched:
        return

    orig_sanitize = Model.sanitize

    def sanitize(self, weights):
        remapped = {}
        for key, value in weights.items():
            if key.startswith("vision_tower.encoder_layers."):
                key = "vision_tower.encoder.layers." + key[len("vision_tower.encoder_layers.") :]
            elif key.startswith("audio_encoder."):
                key = "audio_tower." + key[len("audio_encoder.") :]
            remapped[key] = value
        return orig_sanitize(self, remapped)

    orig_generate_audio = Model.generate_audio

    def generate_audio_with_marker(self, *, input_ids, generated_tokens, tokenizer, **kwargs):
        tts_eos = tokenizer.convert_tokens_to_ids("<|tts_eos|>")
        im_end = tokenizer.convert_tokens_to_ids("<|im_end|>")
        tokens = list(generated_tokens or [])
        if tts_eos not in tokens:
            if tokens and tokens[-1] == im_end:
                tokens[-1] = tts_eos
            else:
                tokens.append(tts_eos)
        return orig_generate_audio(
            self,
            input_ids=input_ids,
            generated_tokens=tokens,
            tokenizer=tokenizer,
            **kwargs,
        )

    Model.sanitize = sanitize
    Model.generate_audio = generate_audio_with_marker
    _patched = True


def is_loaded():
    return "model" in _state


def load_minicpm(warm=True):
    """Load MiniCPM-o 4.5 once and return (model, processor, config)."""
    if "model" in _state:
        return _state["model"], _state["processor"], _state["config"]

    _patch_model_class()
    t = time.time()
    model, processor = load(MODEL_PATH, trust_remote_code=True)
    config = load_config(MODEL_PATH)
    _state.update(
        model=model,
        processor=processor,
        config=config,
        load_s=round(time.time() - t, 2),
    )

    if warm:
        # One spoken turn compiles both the text and TTS paths and loads the
        # vocoder.  Keep it tiny: this is warm-up, not a real answer.
        try:
            generate_speech("你好", language="zh", max_tokens=8, tts_max_tokens=32)
        except Exception as exc:  # warm-up must never block startup
            print("MiniCPM warmup failed:", exc)

    return model, processor, config


def unload():
    """Drop the model and its MLX buffers so another model can take the RAM."""
    _state.clear()
    mx.clear_cache()


def _ref_audio(language):
    return REF_EN if language == "en" else REF_ZH


def _messages(question, language, router=False):
    if router:
        instruction = ROUTER_EN if language == "en" else ROUTER_ZH
    else:
        instruction = INSTRUCTION_EN if language == "en" else INSTRUCTION_ZH
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": question},
    ]


def generate_text(
    question,
    language="zh",
    tools=None,
    audio_path=None,
    max_tokens=128,
    temperature=0.1,
    router=False,
    messages=None,
):
    model, processor, config = load_minicpm(warm=False)
    if messages is None:
        messages = _messages(question, language, router=router)
    prompt = apply_chat_template(
        processor,
        config,
        messages,
        tools=tools,
        num_images=0,
    )
    result = generate(
        model,
        processor,
        prompt,
        audio=audio_path,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return result.text or "", result.token_ids or []


def generate_speech(
    question,
    language="zh",
    tools=None,
    audio_path=None,
    messages=None,
    max_tokens=256,
    tts_max_tokens=256,
    temperature=0.3,
):
    model, processor, config = load_minicpm(warm=False)
    if messages is None:
        messages = _messages(question, language)
    prompt = apply_chat_template(
        processor,
        config,
        messages,
        tools=tools,
        num_images=0,
        use_tts_template=True,
    )
    return generate_audio(
        model,
        processor,
        prompt,
        audio=audio_path,
        ref_audio_path=_ref_audio(language),
        max_tokens=max_tokens,
        tts_max_tokens=tts_max_tokens,
        temperature=temperature,
    )


def run_pipeline(question=None, audio_path=None, language="auto"):
    """One voice turn: decide on a tool, run it, then answer with speech."""
    question = (question or "").strip()
    if language not in ("zh", "en"):
        language = language_of(question)
    if not question:
        question = (
            "请听这段语音，并用一句简短的话回答。"
            if language == "zh"
            else ("Please listen to this audio and answer in one short sentence.")
        )

    timings = {}

    # Turn 1: route to a tool (or decide to chat).  This is a router prompt,
    # not an answer prompt: it must not invent live data.  The router already
    # hears the clip, but the 9B model is much slower with all 25 schemas
    # (~6.0s vs ~1.7-2.3s in tests), so the keyword subset still picks which
    # tools it sees.  Whisper supplies the transcript and language.
    tools = select_tools(question)
    t = time.time()
    first, _ = generate_text(
        question,
        language=language,
        tools=tools,
        audio_path=audio_path,
        max_tokens=64,
        temperature=0.0,
        router=True,
    )
    timings["decide_s"] = round(time.time() - t, 2)

    def retry_decision(failed, retry_instruction):
        # Retry once when a keyword-matched question still produced NO_TOOL.
        retry_messages = _messages(question, language, router=True) + [
            {"role": "assistant", "content": failed},
            {"role": "user", "content": retry_instruction},
        ]
        t_retry = time.time()
        reply, _ = generate_text(
            question,
            language=language,
            tools=tools,
            audio_path=audio_path,
            max_tokens=64,
            temperature=0.0,
            router=True,
            messages=retry_messages,
        )
        timings["decide_retry_s"] = round(time.time() - t_retry, 2)
        return reply

    call, decision_used, decision_retry, forced = resolve_decision(question, first, retry_decision)

    tool = None
    messages = _messages(question, language)
    if call:
        t = time.time()
        result = execute_tool(call)
        timings["tool_s"] = round(time.time() - t, 2)
        tool = {
            "name": call.get("name"),
            "arguments": call.get("arguments", {}),
            "result": result,
        }
        if forced:
            tool["forced"] = True
        messages += [
            {"role": "assistant", "content": decision_used},
            {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
        ]
        if language == "zh":
            messages.append(
                {
                    "role": "user",
                    "content": "请根据工具结果，用一句简短的中文回答用户刚才的问题。"
                    "数字和单位用口语写法，不超过30个字。",
                }
            )
        else:
            messages.append(
                {
                    "role": "user",
                    "content": "Answer the user's question in one short English sentence "
                    "using the tool result. Write units the way they are spoken.",
                }
            )

    # Turn 2: speak.  Tools are deliberately omitted here: the decision is
    # already made, and a smaller prompt is much faster.
    t = time.time()
    spoken = generate_speech(
        question,
        language=language,
        audio_path=audio_path,
        messages=messages,
        max_tokens=256,
        tts_max_tokens=256,
        temperature=0.3,
    )
    timings["speech_s"] = round(time.time() - t, 2)

    wav = np.array(spoken.audio.reshape(-1)) if spoken.audio is not None else np.zeros(0)
    wav = trim_trailing_silence(wav, 24000)
    buf = io.BytesIO()
    sf.write(buf, wav, 24000, format="WAV")

    payload = {
        "model": "minicpm",
        "question": question,
        "decision": first,
        "decision_retry": decision_retry,
        "tools_offered": [t["function"]["name"] for t in tools],
        "tool": tool,
        "answer": spoken.text or "",
        "audio": "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode(),
        "duration_s": round(len(wav) / 24000, 2),
        "timings": timings,
        "load_s": _state.get("load_s"),
    }
    if tool and tool["name"] == "get_weather":
        payload["weather"] = tool["result"]
    # Release transient KV/activation buffers before another model runs.
    mx.clear_cache()
    return payload
