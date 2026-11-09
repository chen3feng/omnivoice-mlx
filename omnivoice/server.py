"""FastAPI backend for OmniVoice.

Endpoints:
  POST /api/transcribe   (audio file)      -> transcript
  POST /api/answer       (text, speaker)   -> answer + spoken WAV (base64)
  POST /api/answer_audio (audio, speaker)  -> native-audio answer + WAV
  GET  /api/health
  GET  /api/turns        -> recent evaluation records
  GET  /api/turns/download

Run:
  python -m omnivoice
Then open http://127.0.0.1:8000
"""

import asyncio
import base64
import gc
import io
import json
import os
import re
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import mlx.core as mx
import mlx_whisper
import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mlx_vlm import load

from . import minicpm_omni
from .prompts import (
    ASR_PROMPTS,
    INSTRUCTION_EN,
    INSTRUCTION_NATIVE,
    INSTRUCTION_ZH,
    build_instruction,
    build_router_instruction,
)
from .public_tools import TOOLS, select_tools
from .qwen_omni import (
    MODEL_PATH,
    execute_tool,
    generate,
    trim_trailing_silence,
)
from .routing import resolve_decision

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
TURN_LOG = ROOT / "turns.jsonl"
_turn_seq = 0
ASR_MODEL = os.environ.get("ASR_MODEL", "mlx-community/whisper-large-v3-turbo")
# Native Qwen voice routes on the audio itself.  Keeping a Whisper transcript
# costs about a second but preserves the question text in turns.jsonl and
# gives an explicit language.  KEEP_TRANSCRIPT=0 skips Whisper entirely.
KEEP_TRANSCRIPT = os.environ.get("KEEP_TRANSCRIPT", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _clip(value, limit=4000):
    """Keep turn logs readable when a tool returns a long article/list."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "...[truncated]"
    if isinstance(value, list):
        return [_clip(v, limit) for v in value[:50]]
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    return value


def log_turn(result, source):
    """Append one evaluation record so answers can be reviewed and optimized."""
    global _turn_seq
    _turn_seq += 1
    rec = {
        "id": f"{time.strftime('%Y%m%d-%H%M%S')}-{_turn_seq:04d}",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "model": result.get("model"),
        "question": result.get("question"),
        "route_input": result.get("route_input"),
        "transcript_kept": result.get("transcript_kept"),
        "detected_language": result.get("detected_language"),
        "native": result.get("native", False),
        "decision": result.get("decision"),
        "decision_retry": result.get("decision_retry"),
        "tools_offered": result.get("tools_offered"),
        "tool": _clip(result.get("tool")),
        "answer": result.get("answer"),
        "duration_s": result.get("duration_s"),
        "timings": result.get("timings"),
    }
    try:
        with open(TURN_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:
        print("turn log failed:", exc)


state = {}
lock = asyncio.Lock()


def unload_qwen():
    """Release Qwen so MiniCPM can use the unified memory."""
    if "model" in state or "processor" in state:
        state.pop("model", None)
        state.pop("processor", None)
        state.pop("load_s", None)
        gc.collect()
        mx.clear_cache()


def warm_qwen():
    """Warm the text tool-call + speech path.

    The audio path is warmed on its first real request: under memory pressure
    warming both paths here can add minutes to startup.
    """
    print("warming up Qwen text pipeline ...")
    t = time.time()
    try:
        run_qwen_pipeline(question="北京今天天气怎么样？", speaker="Ethan")
    except Exception as exc:
        print("text pipeline warmup failed:", exc)
    print(f"text pipeline warmup done in {time.time() - t:.1f}s")


def load_qwen(warm=True):
    if "model" in state:
        return
    if minicpm_omni.is_loaded():
        minicpm_omni.unload()
    print("loading Qwen3-Omni ...")
    t = time.time()
    state["model"], state["processor"] = load(MODEL_PATH, trust_remote_code=True)
    state["load_s"] = time.time() - t
    print(f"Qwen ready in {state['load_s']:.1f}s")
    if warm:
        warm_qwen()


def ensure_qwen():
    if "model" not in state:
        # Do not warm here: the next real request warms the exact path, and a
        # separate warm-up doubles the wait on a memory-constrained machine.
        load_qwen(warm=False)


def ensure_minicpm():
    if minicpm_omni.is_loaded():
        return
    unload_qwen()
    print("loading MiniCPM-o 4.5 ...")
    t = time.time()
    minicpm_omni.load_minicpm(warm=True)
    print(f"MiniCPM ready in {time.time() - t:.1f}s")


@asynccontextmanager
async def lifespan(app):
    # Keep model weights resident.  Without a wired limit macOS swaps them
    # under memory pressure and a 30B model can take minutes per request.
    try:
        wired_gb = float(os.environ.get("MLX_WIRED_LIMIT_GB", "30"))
        mx.set_wired_limit(int(wired_gb * 1024**3))
        print(f"MLX wired limit set to {wired_gb:g} GB")
    except Exception as exc:
        print("could not set MLX wired limit:", exc)

    load_qwen(warm=False)

    # Whisper and the first pipeline call are warmed lazily.  On a machine
    # under memory pressure, doing them here can block startup for minutes.
    # load_qwen(warm=True) still warms when a model is loaded on demand.

    yield
    state.clear()


app = FastAPI(title="OmniVoice", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
async def health():
    loaded = "minicpm" if minicpm_omni.is_loaded() else ("qwen" if "model" in state else None)
    return {
        "ready": loaded is not None,
        "loaded": loaded,
        "models": ["qwen", "minicpm"],
        "load_s": state.get("load_s"),
        "minicpm_load_s": minicpm_omni._state.get("load_s"),
        "keep_transcript": KEEP_TRANSCRIPT,
    }


@app.get("/api/turns")
async def turns(limit: int = 50):
    """Recent evaluation turns: transcript, tool, answer, timings."""
    if not TURN_LOG.exists():
        return {"turns": [], "count": 0}
    limit = max(1, min(limit, 500))
    lines = TURN_LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    items = []
    for line in lines:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"turns": items, "count": len(items)}


@app.get("/api/turns/download")
async def turns_download():
    if not TURN_LOG.exists():
        return JSONResponse({"error": "no turns recorded yet"}, status_code=404)
    return FileResponse(TURN_LOG, media_type="application/x-ndjson", filename="turns.jsonl")


def _transcribe_once(path, language):
    kwargs = {
        "path_or_hf_repo": ASR_MODEL,
        "condition_on_previous_text": False,
        "temperature": 0.0,
        "without_timestamps": True,
        "no_speech_threshold": 0.6,
        "logprob_threshold": -1.0,
    }
    if language:
        kwargs["language"] = language
        kwargs["initial_prompt"] = ASR_PROMPTS[language]
    result = mlx_whisper.transcribe(path, **kwargs)
    segments = result.get("segments") or []
    if segments:
        avg_logprob = sum((s.get("avg_logprob") or -9.0) for s in segments) / len(segments)
    else:
        avg_logprob = -9.0
    return result.get("text", "").strip(), avg_logprob


def transcribe_file(path, language="auto"):
    """Transcribe with a zh/en constraint.

    `auto` runs both forced languages and keeps the higher-confidence one, so
    Whisper can no longer drift into Korean, Icelandic, etc.
    """
    t = time.time()
    if language in ("zh", "en"):
        text, _ = _transcribe_once(path, language)
        return text, language, time.time() - t

    zh_text, zh_lp = _transcribe_once(path, "zh")
    en_text, en_lp = _transcribe_once(path, "en")
    if en_lp > zh_lp:
        text, lang = en_text, "en"
    else:
        text, lang = zh_text, "zh"
    if not text:
        if en_text:
            text, lang = en_text, "en"
        elif zh_text:
            text, lang = zh_text, "zh"
    return text, lang, time.time() - t


def run_qwen_pipeline(question=None, audio_path=None, speaker="Ethan", language="auto"):
    model, processor = state["model"], state["processor"]
    router = build_router_instruction(question, language)
    if audio_path:
        if language == "zh":
            instruction = INSTRUCTION_ZH
            prefix = "用户说："
        elif language == "en":
            instruction = INSTRUCTION_EN
            prefix = "The user said: "
        else:
            instruction = INSTRUCTION_NATIVE
            prefix = "用户说："
        if question:
            instruction = prefix + question + "\n" + instruction
        # Both turns hear the real clip.  The router does not need a Whisper
        # transcript, and offering every tool means a bad transcript cannot
        # hide the right schema from the model.
        answer_conv = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": audio_path},
                    {"type": "text", "text": instruction},
                ],
            }
        ]
        decision_conv = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio": audio_path},
                    {"type": "text", "text": router},
                ],
            }
        ]
        tools = TOOLS
    else:
        answer_conv = [{"role": "user", "content": question + " " + build_instruction(question)}]
        decision_conv = [{"role": "user", "content": question + "\n" + router}]
        # Keep the text prompt small: a keyword-matched subset is faster.
        tools = select_tools(question) if question else TOOLS
    timings = {}

    # Turn 1: tool decision.  Native voice routes on audio; text routes on text.
    t = time.time()
    first, _, _, _ = generate(
        model,
        processor,
        decision_conv,
        return_audio=False,
        max_new_thinker=256,
        max_new_talker=384,
        tools=tools,
    )
    timings["decide_s"] = round(time.time() - t, 2)

    def retry_decision(failed, retry_instruction):
        # Retrying keeps the model's own argument extraction instead of
        # guessing arguments ourselves.
        t_retry = time.time()
        retry_conv = decision_conv + [
            {"role": "assistant", "content": failed},
            {"role": "user", "content": retry_instruction},
        ]
        reply, _, _, _ = generate(
            model,
            processor,
            retry_conv,
            return_audio=False,
            max_new_thinker=256,
            max_new_talker=384,
            tools=tools,
        )
        timings["decide_retry_s"] = round(time.time() - t_retry, 2)
        return reply

    call, decision_used, decision_retry, forced = resolve_decision(question, first, retry_decision)

    tool = None
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
        answer_conv += [
            {"role": "assistant", "content": decision_used},
            {"role": "tool", "content": json.dumps(result, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    "请根据上面的工具结果，用一句简短的中文回答用户的问题。"
                    "不要编造工具结果里没有的数据。"
                    if re.search(r"[一-鿿]", question or "")
                    else "Answer the user's question in one short English sentence "
                    "using only the tool result above. Do not invent data."
                ),
            },
        ]

    # Turn 2: final spoken answer, grounded in the tool result when present.
    # With audio input the answer is generated from the real clip (native
    # speech understanding); the transcript only steered the tool decision.
    # Tools are omitted here so the model cannot start a second tool call and
    # speak the raw call instead of an answer.
    t = time.time()
    answer, audio, _, _ = generate(
        model,
        processor,
        answer_conv,
        return_audio=True,
        max_new_thinker=256,
        max_new_talker=384,
        speaker=speaker,
        tools=[],
    )
    timings["speech_s"] = round(time.time() - t, 2)

    wav = trim_trailing_silence(np.array(audio.reshape(-1)), 24000)
    buf = io.BytesIO()
    sf.write(buf, wav, 24000, format="WAV")
    payload = {
        "model": "qwen",
        "question": question,
        "route_input": "audio" if audio_path else "text",
        "decision": first,
        "decision_retry": decision_retry,
        "tools_offered": [t["function"]["name"] for t in tools],
        "tool": tool,
        "answer": answer,
        "audio": "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode(),
        "duration_s": round(len(wav) / 24000, 2),
        "timings": timings,
    }
    if tool and tool["name"] == "get_weather":
        payload["weather"] = tool["result"]
    # Release transient KV/activation buffers before another model runs.
    mx.clear_cache()
    return payload


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), language: str = Form("auto")):
    if language not in ("auto", "zh", "en"):
        language = "auto"
    raw = await audio.read()
    if not raw:
        return JSONResponse({"error": "empty audio"}, status_code=400)
    async with lock:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.audio"
            dst = Path(td) / "in.wav"
            src.write_bytes(raw)
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(src),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        str(dst),
                    ],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                return JSONResponse(
                    {"error": "cannot decode audio: " + e.stderr.decode()[:300]},
                    status_code=400,
                )
            # MLX GPU streams are thread-local; run on the event-loop thread.
            text, detected, asr_s = transcribe_file(str(dst), language)
    return {"transcript": text, "language": detected, "asr_s": round(asr_s, 2)}


@app.post("/api/answer")
async def answer(
    text: str = Form(...),
    speaker: str = Form("Ethan"),
    model: str = Form("qwen"),
):
    question = text.strip()
    if not question:
        return JSONResponse({"error": "empty text"}, status_code=400)
    if speaker.lower() not in ("chelsie", "ethan", "aiden"):
        speaker = "Ethan"
    async with lock:
        # MLX GPU streams are thread-local; run on the event-loop thread.
        if model == "minicpm":
            ensure_minicpm()
            result = minicpm_omni.run_pipeline(question=question)
        else:
            ensure_qwen()
            result = run_qwen_pipeline(question=question, speaker=speaker)
    log_turn(result, "text")
    return JSONResponse(result)


@app.post("/api/answer_audio")
async def answer_audio(
    audio: UploadFile = File(...),
    speaker: str = Form("Ethan"),
    language: str = Form("auto"),
    model: str = Form("qwen"),
    keep_transcript: bool | None = Form(None),
):
    """Voice path. Qwen hears the clip directly; MiniCPM also hears it, with a
    Whisper transcript used for language/tool routing."""
    raw = await audio.read()
    if not raw:
        return JSONResponse({"error": "empty audio"}, status_code=400)
    if speaker.lower() not in ("chelsie", "ethan", "aiden"):
        speaker = "Ethan"
    if language not in ("auto", "zh", "en"):
        language = "auto"
    # The UI exposes this per request; API clients fall back to the env default.
    if keep_transcript is None:
        keep_transcript = KEEP_TRANSCRIPT
    async with lock:
        if model == "minicpm":
            ensure_minicpm()
        else:
            ensure_qwen()
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.audio"
            dst = Path(td) / "in.wav"
            src.write_bytes(raw)
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(src),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        str(dst),
                    ],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                return JSONResponse(
                    {"error": "cannot decode audio: " + e.stderr.decode()[:300]},
                    status_code=400,
                )

            # MLX GPU streams are thread-local; run on the event-loop thread.
            if model == "minicpm":
                t_probe = time.time()
                transcript, detected, _ = transcribe_file(str(dst), language)
                probe_s = time.time() - t_probe
                if not transcript:
                    transcript = (
                        "请听这段语音，并用一句简短的话回答。"
                        if detected == "zh"
                        else "Please listen to this audio and answer in one short sentence."
                    )
                result = minicpm_omni.run_pipeline(
                    question=transcript,
                    audio_path=str(dst),
                    language=detected,
                )
                result["question"] = transcript
                result["route_input"] = "audio"
                result["transcript_kept"] = True
                result["detected_language"] = detected
                result["timings"]["probe_s"] = round(probe_s, 2)
            else:
                # Native audio: Qwen hears the clip for both the tool decision
                # and the answer.  Whisper is now only an optional transcript
                # probe for logs and an explicit language; it does not drive
                # routing, so a misheard word cannot hide the right tool.
                route_text = None
                probe_s = None
                if keep_transcript:
                    t_probe = time.time()
                    route_text, detected, _ = transcribe_file(str(dst), language)
                    if language == "auto":
                        language = detected
                    probe_s = time.time() - t_probe

                result = run_qwen_pipeline(
                    audio_path=str(dst),
                    question=route_text,
                    speaker=speaker,
                    language=language,
                )
                result["route_input"] = "audio"
                result["transcript_kept"] = keep_transcript
                if keep_transcript:
                    result["detected_language"] = language
                    result["timings"]["probe_s"] = round(probe_s, 2)
                else:
                    result["detected_language"] = language if language in ("zh", "en") else None
    result["native"] = True
    log_turn(result, "voice")
    return JSONResponse(result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
