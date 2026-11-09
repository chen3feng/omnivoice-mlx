import numpy as np

from omnivoice.utils import (
    extract_assistant,
    language_of,
    parse_tool_call,
    trim_trailing_silence,
)


def test_parse_tool_call_valid():
    text = '<tool_call>{"name": "get_weather", "arguments": {"city": "北京"}}</tool_call>'
    assert parse_tool_call(text) == {
        "name": "get_weather",
        "arguments": {"city": "北京"},
    }


def test_parse_tool_call_string_arguments():
    text = '<tool_call>{"name": "get_flight", "arguments": "{\\"callsign\\": \\"TVF6410\\"}"}</tool_call>'
    assert parse_tool_call(text) == {
        "name": "get_flight",
        "arguments": {"callsign": "TVF6410"},
    }


def test_parse_tool_call_rejects_bad_json_and_missing_calls():
    assert parse_tool_call("<tool_call>{not json}</tool_call>") is None
    assert parse_tool_call("NO_TOOL") is None
    assert parse_tool_call(None) is None


def test_extract_assistant_keeps_last_turn():
    decoded = "user text<|im_start|>assistant 你好<|im_end|>"
    assert extract_assistant(decoded) == "你好"


def test_language_of():
    assert language_of("北京天气") == "zh"
    assert language_of("weather in Tokyo") == "en"
    assert language_of("123", fallback="zh") == "zh"


def test_trim_trailing_silence_keeps_voice_and_drops_tail():
    sr = 1000
    silence = np.zeros(sr, dtype=np.float32)
    tone = (0.2 * np.sin(2 * np.pi * 100 * np.arange(sr) / sr)).astype(np.float32)
    wav = np.concatenate([silence, tone, np.zeros(sr, dtype=np.float32)])

    trimmed = trim_trailing_silence(wav, sr, threshold=0.01, keep=0.05)

    assert trimmed.size < wav.size
    assert trimmed.size >= 2 * sr - 10  # the 1s tone is still present
    assert np.max(np.abs(trimmed)) > 0.1
