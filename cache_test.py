"""Problem 4: run all 12 practice documents with cache and without, and log every model call.

    python cache_test.py

Writes output/cache_test.json: one record per model call (setup, document, the API's raw usage block,
derived token counts, dollars from data/prices.json), one record per run, per-setup totals, and checks
that prove each setup did what it was meant to do. Each run is also appended to usage_log/audit_trail.
"""

from __future__ import annotations

import json
from pathlib import Path

import agent
from tools import DATA_DIR, OUTPUT_DIR, now_iso

PRACTICE_DIR = DATA_DIR / "practice_docs"
KEY_PATH = DATA_DIR / "practice_key.json"
OUT_PATH = OUTPUT_DIR / "cache_test.json"
FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")
TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "uncached_input_tokens",
              "output_tokens", "reasoning_tokens")


def _matches(answer: dict, key: dict) -> dict[str, bool]:
    return {f: answer.get(f) == key.get(f) for f in FIELDS}


def main() -> None:
    prices = json.loads(agent.PRICES_PATH.read_text(encoding="utf-8"))[agent.MODEL_NAME]
    key = {row["file"]: row for row in json.loads(KEY_PATH.read_text(encoding="utf-8"))}
    docs = sorted(PRACTICE_DIR.iterdir())
    started = now_iso()

    calls, runs = [], []
    for setup in agent.SETUPS:  # all 12 cached, then all 12 without cache
        print(f"\n== {setup} ==")
        for path in docs:
            doc = path.relative_to(agent.HERE).as_posix()
            r = agent.run(doc, setup=setup, defenses=agent.UNDEFENDED, link_cache=False, quiet=True)  # Problem 4 as run
            match = _matches(r["answer"], key.get(path.name, {}))
            runs.append({
                "setup": setup, "document": doc, "run_id": r["run_id"], "time": r["time"],
                "model_calls": len(r["model_calls"]), **r["totals"], "cost_usd": r["cost"]["total_usd"],
                "answer": r["answer"], "fields_matching_key": sum(match.values()), "key_match": match,
                "trap_calls": r["trap_calls"],
            })
            for c in r["model_calls"]:
                calls.append({"setup": setup, "document": doc, "run_id": r["run_id"], **c})
            print(f"{path.name:30} calls={len(r['model_calls'])} in={r['totals']['input_tokens']:>6,} "
                  f"cached={r['totals']['cached_input_tokens']:>6,} write={r['totals']['cache_write_tokens']:>6,} "
                  f"out={r['totals']['output_tokens']:>4} ${r['cost']['total_usd']:.6f} "
                  f"key={sum(match.values())}/6 traps={r['trap_calls']}")

    summary = {}
    for setup in agent.SETUPS:
        sc = [c for c in calls if c["setup"] == setup]
        sr = [r for r in runs if r["setup"] == setup]
        total = sum(c["cost"]["total_usd"] for c in sc)
        summary[setup] = {
            "documents": len(sr),
            "model_calls": len(sc),
            **{k: sum(c[k] for c in sc) for k in TOKEN_KEYS},
            "cost_breakdown_usd": {
                part: round(sum(c["cost"][part] for c in sc), 8)
                for part in ("uncached_input_usd", "cached_input_usd", "cache_write_usd", "output_usd")
            },
            "total_usd": round(total, 8),
            "per_document_usd": round(total / len(sr), 8),
            "per_call_usd": round(total / len(sc), 8),
        }
    cached_total, no_cache_total = summary["cached"]["total_usd"], summary["no_cache"]["total_usd"]
    summary["percent_saved_with_cache"] = round(100 * (no_cache_total - cached_total) / no_cache_total, 2)

    nc = [c for c in calls if c["setup"] == "no_cache"]
    ca = [c for c in calls if c["setup"] == "cached"]
    checks = {
        "no_cache_zero_cached_tokens": all(c["cached_input_tokens"] == 0 for c in nc),
        "no_cache_zero_cache_writes": all(c["cache_write_tokens"] == 0 for c in nc),
        "no_cache_every_prefix_unique": len({c["instructions_sha256"] for c in nc}) == len(nc),
        "cached_same_prefix_every_call": len({c["instructions_sha256"] for c in ca}) == 1,
        "cached_calls_reading_cache": sum(c["cached_input_tokens"] > 0 for c in ca),
        "cached_calls_writing_cache": sum(c["cache_write_tokens"] > 0 for c in ca),
        "cached_calls_total": len(ca),
        "all_usage_from_api": all(c["usage_source"] == "api" for c in calls),
    }

    OUT_PATH.write_text(json.dumps({
        "generated_at": started,
        "model": agent.MODEL_NAME,
        "prices_per_1m": prices,
        "setups": {
            "cached": "Static instructions + handbook with a cache breakpoint after them "
                      "(PydanticAI cache=CacheConfig(messages=False), 30-minute TTL) and a fixed prompt_cache_key.",
            "no_cache": "OpenAI prompt_cache_options mode=explicit with no breakpoint (nothing written), plus a "
                        "random request id at the start of every request (no prefix can match anything stored).",
        },
        "summary": summary,
        "checks": checks,
        "runs": runs,
        "calls": calls,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n" + json.dumps({"summary": summary, "checks": checks}, indent=2))
    print(f"\nSaved {len(calls)} model calls from {len(runs)} runs to {OUT_PATH.relative_to(agent.HERE)}")


if __name__ == "__main__":
    main()
