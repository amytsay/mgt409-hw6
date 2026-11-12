# HW6: Campus Customs Vendor Desk Agent

MGT 409 (AI Foundations for Managers), Homework 6: tokenomics and prompt injection.

The vendor desk agent reads one vendor document (HTML quote, PDF quote, catalog page, or email),
pulls out the key facts (vendor, SKU, unit price, lead time, minimum order), and recommends whether
the shop should buy, following the rules in `data/shop_handbook.md` (Campus Customs Shop Handbook).

## Ground rules for this project

- **Model:** `gpt-6-luna` for every AI call, set once through `OPENAI_MODEL`.
- **Gateway:** every AI call routes through Portkey using `PORTKEY_API_KEY` from `.env`. No direct OpenAI calls.
- **No real side effects:** the agent never sends real emails or makes real payments. Any "send email" or
  "pay" action only writes an entry to a local log file in `output/`.
- **Cost:** the handbook alone is 10,058 tokens (about 6,100 words), sent on every call. Prices are in `data/prices.json`.
- **Safety:** vendor documents are untrusted data. Defenses follow Lecture 12 (AI Safety): treat document text
  as data not instructions, watch for hidden text (0px fonts, white-on-white PDF text, zero-width characters),
  least-privilege tools, human approval for actions, and red-team tests with booby-trapped documents.
  Since Problem 6 the agent runs with three defense layers (code screening, safe design, prompt rules); see the
  Safety section of `output/harness.md`. The Problem 3 agent is still available with `--undefended`.

## Quick start: run the agent

Python 3.11+ and a Portkey API key. From the repo folder:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt      # Mac/Linux: .venv/bin/python -m pip ...
copy .env.example .env                                          # Mac/Linux: cp .env.example .env
```

Put your key in `.env` (`PORTKEY_API_KEY=...`; never commit `.env`), then run the agent on any vendor document
inside `data/`:

```
.venv\Scripts\python.exe agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

This runs the defended agent (all three defense layers, linked prompt cache). It prints the answer (vendor, SKU,
unit price, lead time, minimum order, decision, reason), a `needs_human_review` flag with warnings, and the
token count and cost. It also appends to `output/usage_log.json` and `output/audit_trail.json`. About $0.0002 per document.

Other modes:

```
.venv\Scripts\python.exe agent.py --doc <file> --undefended          # the Problem 3 agent, no defenses
.venv\Scripts\python.exe agent.py --doc <file> --layers code,design  # choose defense layers
.venv\Scripts\python.exe agent.py --doc <file> --no-cache            # reuse nothing from the prompt cache
.venv\Scripts\python.exe run_exam.py                                 # all 10 exam documents -> output/exam_results.json
```

No key needed: open `output/hw6_report.html` (the results page, works offline), or run
`python test_screen.py` (45 offline checks of the document screening, $0). Nothing can send email or pay:
`send_email` and `approve_payment` are trap tools that only log to `output/trap_calls.json`.

Local note: if the project sits in OneDrive or Dropbox, pause syncing while creating `.venv`.

## Layout

| Path | What it is |
| --- | --- |
| `data/shop_handbook.md` | Campus Customs Shop Handbook (the rules) |
| `data/practice_docs/` | 12 practice vendor documents |
| `data/practice_key.json` | Answer key for the practice documents |
| `data/exam_docs/` | 10 exam vendor documents |
| `data/prices.json` | gpt-6-luna token prices |
| `data/my_attacks/` | Our own booby-trapped documents (Problem 7): `a1_westville_invoice.html`, `a2_bluehen_confirmation.pdf`, bonus `bonus/a3_yorkst_quote.html`, and `my_attacks_key.json` |
| `output/` | Run results and simulated email/payment logs |
| `AI_prompts.md` | Log of prompts given to the AI coding assistant (Problem 1) |
| `estimate_handbook.py` | Counts handbook tokens and prices them (Problem 2) |
| `output/handbook_estimate.md` | Handbook token count and cost estimate (Problem 2) |
| `agent.py` | Entry point: model/Portkey config, the agent, cost and logging (Problem 3) |
| `tools.py` | `read_document` plus the two trap tools, `send_email` and `approve_payment` (Problem 3; human-only since Problem 6) |
| `models.py` | `VendorRecommendation` (Problem 3), `ExtractedQuote` and `DeskAnswer` (Problem 6) |
| `prompts/prompt.md` | Defended agent instructions plus the Safety rules; the handbook is appended on every call (Problems 3, 6) |
| `prompts/prompt_p3_undefended.md` | The original Problem 3 instructions, used by `--undefended` |
| `screen.py` | Defense layer 1: rebuilds what a person sees, cuts hidden text, fact-checks and cleans answers (Problem 6) |
| `rules.py` | Defense layer 2: the handbook's four purchasing checks, applied in code (Problem 6) |
| `output/usage_log.json`, `output/audit_trail.json`, `output/trap_calls.json` | Per-run logs; trap calls should stay `[]` (Problem 3) |
| `cache_test.py` | Runs all 12 practice docs with and without cache (Problem 4); `agent.py --no-cache` runs one doc uncached |
| `output/cache_test.json`, `output/cache_test.md` | Every model call from both cache setups, and the cost analysis (Problem 4) |
| `attack_test.py` | Runs the undefended agent on the 12 practice docs and checks answers, traps and hidden text (Problem 5) |
| `output/attack_results.json`, `output/attack_results.md` | Attack results per document, and what fooled the agent and where (Problem 5) |
| `defense_test.py` | Reruns the 12 practice docs with no defenses, each layer alone, and all layers (Problem 6) |
| `output/defense_results.json`, `output/defense_results.md` | Before/after results, what each layer catches, cost per layer (Problem 6) |
| `make_attacks.py`, `red_team_test.py` | Build our attack documents and run them against the undefended and defended agent (Problem 7) |
| `output/red_team.json`, `output/red_team.md`, `output/red_team_after_fix.json` | Red-team results, write-up, and the rerun after fixing the holes it found (Problem 7) |
| `test_screen.py` | Offline self-test ($0): 45 hiding tricks and normal page features the screening must handle (Problems 6-7) |
| `run_exam.py` | Runs the final defended agent on the 10 exam documents (Problem 8) |
| `output/exam_results.json`, `output/exam_details.json` | Exam results in the required format, plus review flags and a consistency rerun (Problem 8) |
| `build_report.py`, `report/template.html` | Build the results page from the result files (Problem 9) |
| `output/hw6_report.html` | The results page: one self-contained file, opens offline by double-click (Problem 9) |
| `output/harness.md` | How the agent works, updated each problem (Safety section since Problem 6) |
