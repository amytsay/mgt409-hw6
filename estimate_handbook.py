"""Problem 2: count the handbook's tokens and price it with data/prices.json.

No API calls: tokens are counted locally with tiktoken, so this costs $0.
Run from hw6/:  python estimate_handbook.py
"""

from __future__ import annotations

import json
from pathlib import Path

import tiktoken

from agent import MODEL_NAME

HERE = Path(__file__).resolve().parent
HANDBOOK = HERE / "data" / "shop_handbook.md"
PRICES = HERE / "data" / "prices.json"
MODEL = MODEL_NAME  # read once in agent.py from OPENAI_MODEL
CALLS = 1000


def main() -> None:
    text = HANDBOOK.read_text(encoding="utf-8")
    tokens = len(tiktoken.get_encoding("o200k_base").encode(text))
    cross_check = len(tiktoken.get_encoding("cl100k_base").encode(text))
    p = json.loads(PRICES.read_text(encoding="utf-8"))[MODEL]

    per_m = 1_000_000
    uncached = tokens * p["input_per_1m"] / per_m
    write = tokens * p["cache_write_per_1m"] / per_m
    read = tokens * p["cached_input_per_1m"] / per_m

    print(f"model={MODEL}  chars={len(text):,}  words={len(text.split()):,}")
    print(f"o200k_base tokens={tokens:,}  (cl100k_base cross-check={cross_check:,})")
    print(f"1 call  no cache      = ${uncached:.8f}")
    print(f"1 call  cache write   = ${write:.8f}")
    print(f"1 call  cache read    = ${read:.8f}")
    print(f"{CALLS} calls no cache   = ${uncached * CALLS:.6f}")
    print(f"{CALLS} calls cached     = ${write + read * (CALLS - 1):.6f}  (1 write + {CALLS - 1} reads)")


if __name__ == "__main__":
    main()
