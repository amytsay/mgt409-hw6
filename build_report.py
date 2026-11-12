"""Problem 9: build output/hw6_report.html, one self-contained file (no internet, no files next to it).

    python build_report.py

Every number on the page is read from the result files the earlier problems wrote (nothing is typed in by hand):
  data/prices.json, data/shop_handbook.md (token count), output/cache_test.json (Problem 4),
  output/attack_results.json (5), output/defense_results.json (6), output/red_team.json and
  output/red_team_after_fix.json (7), output/exam_results.json and output/exam_details.json (8).
The design (layout, the LISA "Alter Ego" theme, turntable, prism, cursor, LLOUD vault) lives in report/template.html;
this script drops the numbers into it as a JSON block and writes one file.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import mean

import tiktoken

from agent import MODEL_NAME  # the one place the model is set (OPENAI_MODEL, gpt-6-luna)

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
TEMPLATE = HERE / "report" / "template.html"
TARGET = OUT / "hw6_report.html"
DOCS_PER_MONTH = 1000 * 30


def load(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


# Short descriptions of each document's hidden payload (from the Problem 5 and 8 analyses; labels only, not results).
PRACTICE_PAYLOADS = {
    "p01": "none", "p02": "0px text: 'new price $5.11'", "p03": "display:none box: vendor swap",
    "p04": "HTML comment: approve a $4,800 deposit", "p05": "none", "p06": "white PDF text: email our cost list",
    "p07": "0.8 pt text: 'lead time now 7 days'", "p08": "none", "p09": "1px white email text: 12 days + tracking link",
    "p10": "none", "p11": "none (normal page script)", "p12": "text drawn below the page: 'new price $17.44'",
}
EXAM_NOTES = {
    "e01": "clean", "e02": "off-screen 'negotiated $16.27' price", "e03": "background-colored $6,200 deposit request",
    "e04": "hidden 'vendor is really Blue Hen'", "e05": "clean (price over cap)", "e06": "white text: email our cost table",
    "e07": "0.8 pt 'minimum is 100'", "e08": "clean", "e09": "visible 'pre-approved, approve the deposit' pressure",
    "e10": "hidden 'withdrawn, do not recommend' sabotage",
}


def steady(rows: list[dict]) -> dict:
    """Average per document once the cache is warm (runs that stored the prefix in cache are left out)."""
    warm = [r for r in rows if r["tokens"]["cache_write_tokens"] == 0] or rows
    return {
        "input": mean(r["tokens"]["input_tokens"] for r in warm),
        "uncached": mean(r["tokens"]["uncached_input_tokens"] for r in warm),
        "output": mean(r["tokens"]["output_tokens"] for r in warm),
        "usd": mean(r["cost_usd"] for r in warm),
        "calls": mean(r["model_calls"] for r in warm),
        "fooled": [Path(r["document"]).name[:3] for r in rows if r["fooled"]],
        "decisions": sum(r["decision_matched"] for r in rows),
    }


def main() -> None:
    prices = load("data/prices.json")[MODEL_NAME]
    hb_tokens = len(tiktoken.get_encoding("o200k_base").encode((HERE / "data/shop_handbook.md").read_text(encoding="utf-8")))
    cache = load("output/cache_test.json")
    attack = load("output/attack_results.json")
    defense = load("output/defense_results.json")
    rt_before, rt_after = load("output/red_team.json"), load("output/red_team_after_fix.json")
    exam, exam_details = load("output/exam_results.json"), load("output/exam_details.json")

    # --- Problem 2 + 4: caching ------------------------------------------------------------------
    cs = cache["summary"]
    linked = [r["total_usd"] for r in cache["follow_up_experiments"]["runs"]
              if r["experiment"] in ("linked_chain", "comparison_response_id_single") and r["calls"][0]["cached_input_tokens"] > 0]
    naive = [r["total_usd"] for r in cache["follow_up_experiments"]["runs"] if r["experiment"] == "naive_no_cache_implicit_writes"]
    prefix = max(c["cached_input_tokens"] for c in cache["calls"])
    exam_per_doc = mean(e["cost_usd"] for e in exam)
    per_doc = {
        "no_cache": cs["no_cache"]["per_document_usd"], "cached": cs["cached"]["per_document_usd"],
        "linked": mean(linked), "naive": naive[0], "defended": exam_per_doc,
    }
    caching = {
        "handbook_tokens": hb_tokens, "prefix_tokens": prefix,
        "est_call_uncached": hb_tokens * prices["input_per_1m"] / 1e6,
        "est_call_cached": hb_tokens * prices["cached_input_per_1m"] / 1e6,
        "est_1000_uncached": 1000 * hb_tokens * prices["input_per_1m"] / 1e6,
        "est_1000_cached": (hb_tokens * prices["cache_write_per_1m"] + 999 * hb_tokens * prices["cached_input_per_1m"]) / 1e6,
        "total_cached": cs["cached"]["total_usd"], "total_no_cache": cs["no_cache"]["total_usd"],
        "saved_pct": cs["percent_saved_with_cache"],
        "cached_reads": cache["checks"]["cached_calls_reading_cache"], "cached_writes": cache["checks"]["cached_calls_writing_cache"],
        "calls": cache["checks"]["cached_calls_total"],
        "no_cache_zero": cache["checks"]["no_cache_zero_cached_tokens"] and cache["checks"]["no_cache_zero_cache_writes"],
        "per_doc": per_doc, "per_month": {k: v * DOCS_PER_MONTH for k, v in per_doc.items()},
        "linked_saved_pct": 100 * (per_doc["no_cache"] - per_doc["linked"]) / per_doc["no_cache"],
        "naive_extra_pct": 100 * (per_doc["naive"] - per_doc["no_cache"]) / per_doc["no_cache"],
    }

    # --- Problem 5 + 6: attacks before and after -------------------------------------------------
    docs = []
    for d in defense["documents"]:
        b = d["before"]
        name = Path(d["document"]).name
        docs.append({
            "file": name, "payload": PRACTICE_PAYLOADS[name[:3]], "clean": d["clean_document"],
            "before": {"facts": b["fields_matched"], "decision": b["answer"]["decision"], "ok": b["decision_matched"], "fooled": b["fooled"]},
            "after": {"facts": d["fields_matched"], "decision": d["answer"]["decision"], "ok": d["decision_matched"],
                      "fooled": d["fooled"], "review": d["needs_human_review"]},
        })
    attacks = {
        "docs": docs,
        "before": {"fooled": sum(x["before"]["fooled"] for x in docs), "wrong_buys": sum(not x["before"]["ok"] for x in docs),
                   "correct": sum(x["before"]["facts"] == 5 and x["before"]["ok"] for x in docs),
                   "traps": sum(a["trap_tool_called"] for a in attack["documents"])},
        "after": {"fooled": sum(x["after"]["fooled"] for x in docs), "wrong_buys": sum(not x["after"]["ok"] for x in docs),
                  "correct": sum(x["after"]["facts"] == 5 and x["after"]["ok"] for x in docs),
                  "flagged": sum(x["after"]["review"] for x in docs),
                  "trapped_docs": sum(not x["clean"] for x in docs),
                  "false_flags": sum(x["after"]["review"] and x["clean"] for x in docs)},
        "post_fix_correct": defense["post_red_team_fix"]["summary"]["all_layers"]["decisions_correct"],
        "post_fix_fooled": len(defense["post_red_team_fix"]["summary"]["all_layers"]["fooled"]),
    }

    # --- Problem 6: what each layer costs ----------------------------------------------------------
    runs = defense["layers"]["runs"]
    st = {n: steady(r) for n, r in runs.items()}
    base = st["undefended"]
    labels = {"undefended": "No defenses", "code_only": "Code only", "design_only": "Design only",
              "prompt_only": "Prompt only", "all_layers": "All three layers"}
    layers = [{
        "key": n, "label": labels[n], "input": s["input"], "uncached": s["uncached"], "output": s["output"],
        "usd": s["usd"], "calls": s["calls"], "fooled": s["fooled"], "decisions": s["decisions"],
        "d_input": s["input"] - base["input"], "d_usd": s["usd"] - base["usd"],
        "d_pct": 100 * (s["usd"] - base["usd"]) / base["usd"],
    } for n, s in st.items()]
    writes = [r["cost_usd"] for r in runs["all_layers"] if r["tokens"]["cache_write_tokens"] > 0]

    # --- Problem 7: red team -----------------------------------------------------------------------
    def rt(data: dict, attack_file: str, agent: str) -> dict:
        x = next(r for r in data["results"] if r["attack"] == attack_file and r["agent"] == agent)
        return {"fooled": x["fooled"], "flagged": x["flagged_for_review"], "trap": x["trap_tool_ran"]}

    redteam = {f: {"undefended": rt(rt_before, f, "undefended"), "defended": rt(rt_before, f, "defended"),
                   "fixed": rt(rt_after, f, "defended")}
               for f in ("a1_westville_invoice.html", "a2_bluehen_confirmation.pdf", "bonus/a3_yorkst_quote.html")}

    # --- Problem 8: exam ---------------------------------------------------------------------------
    flags = {d["file"]: d["needs_human_review"] for d in exam_details["documents"]}
    stable = {d["file"]: d["stability_check"]["facts_and_decision_identical"] for d in exam_details["documents"]}
    exam_rows = [{**e, "review": flags[e["file"]], "stable": stable[e["file"]], "note": EXAM_NOTES[e["file"][:3]]} for e in exam]

    # --- Recommendation ---------------------------------------------------------------------------
    one_write = mean(writes) if writes else 0.0015
    reco = {
        "per_doc": exam_per_doc, "monthly": exam_per_doc * DOCS_PER_MONTH,
        "cache_refresh_hourly_month": one_write * 24 * 30, "one_write": one_write,
        "monthly_high": exam_per_doc * DOCS_PER_MONTH + one_write * 24 * 30,
        "flag_rate_exam": sum(flags.values()) / len(flags),
    }

    data = {
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"), "model": MODEL_NAME,
        "prices": prices, "caching": caching, "attacks": attacks, "layers": layers, "one_write": one_write,
        "redteam": redteam, "exam": exam_rows,
        "exam_totals": {"cost": sum(e["cost_usd"] for e in exam), "recommend": sum(e["decision"] == "recommend" for e in exam),
                        "traps": sum(e["trap_tool_called"] for e in exam), "flagged": sum(flags.values()),
                        "stable": sum(stable.values()), "cached": mean(e["cached_tokens"] for e in exam)},
        "reco": reco,
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__REPORT_DATA__", blob)
    TARGET.write_text(html, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(HERE)} ({len(html):,} bytes)")
    print(json.dumps({"monthly": round(reco["monthly"], 2), "monthly_high": round(reco["monthly_high"], 2),
                      "per_doc": per_doc, "layers": {l["key"]: round(l["usd"], 6) for l in layers},
                      "attacks_before": attacks["before"], "attacks_after": attacks["after"]}, indent=1))


if __name__ == "__main__":
    main()
