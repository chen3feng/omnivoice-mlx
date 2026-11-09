#!/usr/bin/env python3
"""Download the MLX models used by OmniVoice.

Examples:
  python scripts/download_models.py --model all
  python scripts/download_models.py --model qwen
  python scripts/download_models.py --model minicpm --mirror   # China-friendly

The script uses Hugging Face Hub.  ``--mirror`` sets HF_ENDPOINT to
https://hf-mirror.com before the hub client is imported, which is useful when
huggingface.co is slow or unreachable.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

# repo_id -> local directory (relative to the repository root)
LOCAL_MODELS = {
    "qwen": (
        "mlx-community/Qwen3-Omni-30B-A3B-Instruct-4bit",
        MODELS / "Qwen3-Omni-30B-A3B-Instruct-4bit",
    ),
    "minicpm": (
        "andrevp/MiniCPM-o-4_5-MLX-4bit",
        MODELS / "MiniCPM-o-4_5-MLX-4bit",
    ),
}
ASR_REPO = "mlx-community/whisper-large-v3-turbo"
APPROX_GB = {"qwen": 20, "minicpm": 7, "asr": 2}


def human_gb(num_bytes: int) -> str:
    return f"{num_bytes / 1024**3:.1f} GB"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download OmniVoice MLX models")
    parser.add_argument(
        "--model",
        choices=["qwen", "minicpm", "asr", "all"],
        default="all",
        help="which model to download (default: all)",
    )
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="use https://hf-mirror.com (useful in mainland China)",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("HF_ENDPOINT", ""),
        help="custom Hugging Face endpoint (overrides --mirror)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be downloaded without downloading",
    )
    args = parser.parse_args()

    endpoint = args.endpoint or ("https://hf-mirror.com" if args.mirror else "")
    if endpoint:
        os.environ["HF_ENDPOINT"] = endpoint

    if args.model == "all":
        targets = list(LOCAL_MODELS)
        need_asr = True
    elif args.model == "asr":
        targets = []
        need_asr = True
    else:
        targets = [args.model]
        need_asr = False

    total = sum(APPROX_GB.get(t, 0) for t in targets) + (APPROX_GB["asr"] if need_asr else 0)
    free = shutil.disk_usage(ROOT).free
    print(f"target: {', '.join(targets + (['asr'] if need_asr else []))}")
    print(f"approx download: {total} GB; free disk: {human_gb(free)}")
    if free < total * 1024**3:
        print("warning: free disk space may be too low", file=sys.stderr)

    if args.dry_run:
        for key in targets:
            repo, dest = LOCAL_MODELS[key]
            print(f"{key}: {repo} -> {dest}")
        if need_asr:
            print(f"asr: {ASR_REPO} -> Hugging Face cache")
        return 0

    from huggingface_hub import snapshot_download

    for key in targets:
        repo, dest = LOCAL_MODELS[key]
        dest.mkdir(parents=True, exist_ok=True)
        print(f"\n== {key}: {repo}")
        print(f"   -> {dest}")
        snapshot_download(repo_id=repo, local_dir=str(dest))

    if need_asr:
        print(f"\n== asr: {ASR_REPO}")
        print("   -> Hugging Face cache")
        snapshot_download(repo_id=ASR_REPO)

    print("\nDone. Start the app with: python -m omnivoice")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
