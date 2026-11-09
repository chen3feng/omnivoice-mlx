"""Pure helpers shared by the model pipelines and tests.

This module deliberately has no MLX imports so it can be unit-tested on any
platform (including Linux CI).
"""

from __future__ import annotations

import json
import re

import numpy as np

_CJK = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-z]")


def parse_tool_call(text: str | None) -> dict | None:
    """Parse ``<tool_call>{"name": ..., "arguments": ...}</tool_call>``."""
    m = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    name = obj.get("name")
    args = obj.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return {"name": name, "arguments": args}


def extract_assistant(decoded: str) -> str:
    """Keep only the last assistant turn from a decoded chat template."""
    marker = "<|im_start|>assistant"
    idx = decoded.rfind(marker)
    if idx != -1:
        decoded = decoded[idx + len(marker) :]
    return decoded.replace("<|im_end|>", "").strip()


def trim_trailing_silence(wav, sr, threshold=0.003, keep=0.15):
    """Cut trailing near-silence, keeping a short tail.

    Guards against the Talker running on after the spoken answer.
    """
    if wav.size == 0:
        return wav
    win = max(1, int(sr * 0.02))
    n = wav.size // win
    if n == 0:
        return wav
    rms = np.sqrt((wav[: n * win].reshape(n, win) ** 2).mean(axis=1))
    voiced = np.flatnonzero(rms > threshold)
    if voiced.size == 0:
        return wav
    end = min(wav.size, (voiced[-1] + 1) * win + int(sr * keep))
    return wav[:end]


def language_of(text: str | None, fallback: str = "zh") -> str:
    """Infer zh/en from the script used in the text."""
    if _CJK.search(text or ""):
        return "zh"
    if _LATIN.search(text or ""):
        return "en"
    return fallback
