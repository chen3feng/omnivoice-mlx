#!/usr/bin/env python3
"""Run a repeatable answer-quality check against a running OmniVoice server.

Each turn is written as one JSON line, so the output can be diffed between
models or reviewed after a UI session:

  python scripts/eval_quality.py --model qwen
  python scripts/eval_quality.py --model minicpm --out eval-minicpm.jsonl

The server must already be running (``python -m omnivoice``).
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

QUESTIONS = [
    "北京今天天气怎么样？",
    "上海明天会下雨吗？",
    "美元兑人民币汇率是多少？",
    "北京空气质量怎么样？",
    "现在几点了？",
    "苹果公司股价多少？",
    "北京今天日出是几点？",
    "珠穆朗玛峰有多高？",
    "今天有什么科技新闻？",
    "给我讲个笑话。",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate OmniVoice answers")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", choices=["qwen", "minicpm"], default="qwen")
    parser.add_argument("--out", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    out_path = args.out or f"eval-{args.model}.jsonl"
    questions = QUESTIONS[: args.limit] if args.limit > 0 else QUESTIONS
    rows = []
    for i, question in enumerate(questions, 1):
        data = urllib.parse.urlencode(
            {"text": question, "speaker": "Ethan", "model": args.model}
        ).encode()
        req = urllib.request.Request(args.base_url + "/api/answer", data=data)
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                payload = json.load(resp)
        except Exception as exc:  # noqa: BLE001 - report and continue the suite
            print(f"[{i}] ERROR {question!r}: {exc}")
            continue

        tool = payload.get("tool") or {}
        row = {
            "question": question,
            "model": payload.get("model"),
            "decision": payload.get("decision"),
            "tools_offered": payload.get("tools_offered"),
            "tool": tool.get("name"),
            "arguments": tool.get("arguments"),
            "result": tool.get("result"),
            "answer": payload.get("answer"),
            "timings": payload.get("timings"),
            "wall_s": round(time.time() - started, 2),
        }
        rows.append(row)
        print(f"\n[{i}] {question}")
        print(f"  tool: {row['tool']} {row['arguments']}")
        print(f"  answer: {row['answer']!r}")
        print(f"  timings: {row['timings']} wall={row['wall_s']}s")

    with open(out_path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(rows)} turns to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
