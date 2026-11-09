# Contributing

Thanks for helping improve OmniVoice.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[mlx,dev]"
```

You do **not** need to download model weights to run the unit tests.

## Before opening a pull request

```bash
make check
```

This runs `ruff check`, `ruff format --check`, and `pytest`. The CI workflow
does the same on Python 3.11–3.13.

## Guidelines

- Keep the tool layer keyless: every tool must work without an API key.
- Keep prompts bilingual. If you add a tool, add it to `TOOLS`, `TOOL_IMPL`,
  and the relevant `TOOL_GROUPS` entry in `omnivoice/public_tools.py`.
- Add a unit test for pure logic (routing, parsing, rounding, labels).
- Do not commit model weights, `turns.jsonl`, `.env`, or diagnostic audio.
- For MLX changes, test on Apple Silicon and note the model used in the PR.

## Reporting bugs

Please include:

- the model (`qwen` or `minicpm`) and the UI language;
- the question/transcript, tool call, and answer from `turns.jsonl`;
- the relevant `timings` block;
- your macOS version, Python version, and memory size.
