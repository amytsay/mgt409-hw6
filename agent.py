"""Campus Customs vendor desk agent (HW6 Problems 3, 4 and 6): entry point.

    python agent.py --doc data/practice_docs/p01_bluehen_quote.html               # defended (all 3 layers)
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --undefended  # the Problem 3 agent
    python agent.py --doc ... --layers code,design                                # pick defense layers
    python agent.py --doc ... --no-cache                                          # reuse nothing from cache

Defense layers (Problem 6; plain-language version in output/harness.md, Safety section):
  code    screen.py   rebuild what a person sees, cut hidden text, normalise, neutralise links (before the model);
                      fact-check every answer value against the visible text and scrub the answer (after)
  design  rules.py    no document tool round-trip: the screened document goes in the message as fenced data;
                      send_email/approve_payment stay registered but human-only (requires_approval), so a request
                      is logged as blocked and denied; the buy decision is computed by code from the handbook
  prompt  prompts/prompt.md "Safety rules": the document is data, never instructions; the model reports suspicious text

After every run: output/usage_log.json (tokens, dollars) and output/audit_trail.json (tool calls, screening,
answer). Trap tool calls or blocked requests go to output/trap_calls.json; nothing is ever sent or paid.
Every AI call is gpt-6-luna through Portkey with PORTKEY_API_KEY from .env.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # keep terminal output to the answer

import httpx2  # the OpenAI SDK's HTTP client (v3 uses httpx2, not httpx)
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, RunContext, ToolDenied
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ThinkingPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

import rules
import screen
from models import DeskAnswer, ExtractedQuote, VendorRecommendation
from tools import (
    HERE,
    HUMAN_ONLY_TOOLS,
    OUTPUT_DIR,
    TOOLS,
    TRAP_TOOL_NAMES,
    Deps,
    append_json,
    ensure_trap_log,
    extract_text,
    now_iso,
    record_trap,
    resolve_document,
)

# --- Configuration: the only place the model and gateway are set -------------------------------

for folder in (HERE, *HERE.parents):  # nearest .env: hw6/, then the class folder
    if (folder / ".env").is_file():
        load_dotenv(folder / ".env")
        break

REQUIRED_MODEL = "gpt-6-luna"
MODEL_NAME = os.getenv("OPENAI_MODEL", REQUIRED_MODEL)
if MODEL_NAME != REQUIRED_MODEL:
    sys.exit(f"OPENAI_MODEL is {MODEL_NAME!r}; this homework allows only {REQUIRED_MODEL!r}.")
PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1")

PROMPTS = HERE / "prompts"
HANDBOOK_PATH = HERE / "data" / "shop_handbook.md"
PRICES_PATH = HERE / "data" / "prices.json"
USAGE_LOG = OUTPUT_DIR / "usage_log.json"
AUDIT_TRAIL = OUTPUT_DIR / "audit_trail.json"
CACHE_LINK = OUTPUT_DIR / "cache_link.json"  # last response id per prompt prefix (linked-run cache fix)
LINK_MAX_AGE_S = 25 * 60  # cache entries live at least 30 minutes; stay safely inside that

HANDBOOK = HANDBOOK_PATH.read_text(encoding="utf-8").rstrip()
P3_PROMPT = (PROMPTS / "prompt_p3_undefended.md").read_text(encoding="utf-8").rstrip()
_PROMPT_MD = (PROMPTS / "prompt.md").read_text(encoding="utf-8")
DESIGN_PROMPT, _, _rules = _PROMPT_MD.partition("\n## Safety rules")
DESIGN_PROMPT = DESIGN_PROMPT.rstrip()
SAFETY_RULES = ("## Safety rules" + _rules).rstrip()
USER_PROMPT = "Read the selected vendor document and report on it."


@dataclass(frozen=True)
class Defenses:
    code: bool = True
    design: bool = True
    prompt: bool = True

    @property
    def label(self) -> str:
        on = [n for n in ("code", "design", "prompt") if getattr(self, n)]
        return "+".join(on) if on else "undefended"

    @classmethod
    def parse(cls, text: str) -> Defenses:
        names = {t.strip() for t in text.split(",") if t.strip()}
        unknown = names - {"code", "design", "prompt"}
        if unknown:
            raise ValueError(f"unknown layer(s): {', '.join(sorted(unknown))}")
        return cls(code="code" in names, design="design" in names, prompt="prompt" in names)


UNDEFENDED = Defenses(False, False, False)
FULL = Defenses(True, True, True)


def instructions_for(d: Defenses) -> str:
    """Static text, same on every call for a given layer setup: prompt, safety rules (if on), then the handbook."""
    head = DESIGN_PROMPT if d.design else P3_PROMPT
    if d.prompt:
        head += "\n\n" + SAFETY_RULES
    return f"{head}\n\n---\n\n{HANDBOOK}\n"


SETUPS = ("cached", "no_cache")
CACHE_KEY = "campus-customs-vendor-desk"
_BASE_SETTINGS = dict(openai_reasoning_effort="low", max_tokens=4000,
                      openai_reasoning_summary="concise")  # "glass box" monitoring (Lecture 12): logged to the audit trail
NO_CACHE_SETTINGS = OpenAIResponsesModelSettings(**_BASE_SETTINGS, openai_prompt_cache_options={"mode": "explicit"})


def cached_settings(link_id: str | None) -> OpenAIResponsesModelSettings:
    """Cache breakpoint after the instructions + handbook (30-minute TTL). With link_id, the request names the
    previous run's response, which routes it to the machine that already holds this prefix (Problem 4 finding)."""
    options: dict[str, Any] = {"mode": "explicit", "ttl": "30m"}
    if link_id:
        options["comparison_response_id"] = link_id
    return OpenAIResponsesModelSettings(
        **_BASE_SETTINGS,
        openai_cache_instructions=True,
        openai_prompt_cache_key=CACHE_KEY,
        openai_prompt_cache_options=options,  # type: ignore[typeddict-item]
    )


# --- Linked-run cache fix: remember the last response id for each prompt prefix ----------------


def prefix_key(d: Defenses) -> str:
    return hashlib.sha256(f"{d.design}|{d.prompt}|{instructions_for(d)}".encode()).hexdigest()[:16]


def _load_links() -> dict[str, Any]:
    try:
        return json.loads(CACHE_LINK.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def get_link(key: str) -> str | None:
    entry = _load_links().get(key)
    if entry and time.time() - entry.get("saved_at", 0) < LINK_MAX_AGE_S:
        return entry.get("response_id")
    return None


def save_link(key: str, response_id: str | None) -> None:
    if not response_id:
        return
    links = _load_links()
    links[key] = {"response_id": response_id, "saved_at": time.time(), "saved": now_iso()}
    CACHE_LINK.parent.mkdir(parents=True, exist_ok=True)
    CACHE_LINK.write_text(json.dumps(links, indent=2) + "\n", encoding="utf-8")


# --- Model, with a hook that keeps OpenAI's raw usage report for every response ---------------

RAW_RESPONSES: dict[str, dict[str, Any]] = {}  # response id -> usage block exactly as the API sent it


async def _capture_usage(response: httpx2.Response) -> None:
    """Save the API's own usage numbers (every token count it reports). No headers, so no key, are kept."""
    if response.request.method != "POST" or not response.request.url.path.endswith("/responses"):
        return
    if response.status_code != 200:
        return
    await response.aread()
    try:
        body = response.json()
    except ValueError:
        return
    if isinstance(body, dict) and body.get("id"):
        RAW_RESPONSES[body["id"]] = {
            "model": body.get("model"),
            "usage": body.get("usage"),
            "prompt_cache_diagnostics": body.get("prompt_cache_diagnostics"),
        }


@lru_cache(maxsize=1)
def build_model() -> OpenAIResponsesModel:
    """gpt-6-luna through Portkey. The key is read from the environment and never printed or logged."""
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        sys.exit("PORTKEY_API_KEY is not set. Add it to .env (see .env.example).")
    client = AsyncOpenAI(
        api_key="unused-portkey-auth-in-headers",
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-api-key": key, "x-portkey-provider": "openai"},
        max_retries=2,
        timeout=90,
        http_client=httpx2.AsyncClient(timeout=90, event_hooks={"response": [_capture_usage]}),
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# --- Agents: one per (design, prompt, setup) ---------------------------------------------------


@lru_cache(maxsize=None)
def get_agent(design: bool, prompt: bool, setup: str) -> Agent:
    d = Defenses(code=False, design=design, prompt=prompt)
    text = instructions_for(d)
    output = ExtractedQuote if prompt else VendorRecommendation
    if setup == "no_cache":

        def unique_prefix(ctx: RunContext[Deps]) -> str:
            """A new random line at the very start of every request: no prefix can match anything stored."""
            return f"Request id: {uuid.uuid4().hex}\n\n{text}"

        instructions: Any = unique_prefix
    else:
        instructions = text
    if design:  # trap tools registered but human-only; the run pauses instead of executing them
        return Agent(deps_type=Deps, output_type=[output, DeferredToolRequests], instructions=instructions,
                     tools=HUMAN_ONLY_TOOLS, retries=1)
    return Agent(deps_type=Deps, output_type=output, instructions=instructions, tools=TOOLS, retries=1)


# Kept for scripts that import them (Problem 4)
agent = get_agent(False, False, "cached")
no_cache_agent = get_agent(False, False, "no_cache")


def fenced(text: str) -> str:
    """Put the document in the message as clearly marked data with a random id it cannot guess or fake."""
    tag = uuid.uuid4().hex[:10]
    safe = text.replace("<<<", "‹‹‹").replace(">>>", "›››")
    return (f"Report on the vendor document below.\n<<<UNTRUSTED_DOCUMENT id={tag}>>>\n{safe}\n"
            f"<<<END_UNTRUSTED_DOCUMENT id={tag}>>>")


# --- Usage and cost -----------------------------------------------------------------------------


def _tokens_from_api(raw_usage: dict[str, Any] | None, fallback: Any) -> dict[str, int]:
    """Token counts from the API's usage block (input_tokens includes cached and cache-write tokens)."""
    if raw_usage:
        in_details = raw_usage.get("input_tokens_details") or {}
        out_details = raw_usage.get("output_tokens_details") or {}
        input_tokens = int(raw_usage.get("input_tokens") or 0)
        cache_read = int(in_details.get("cached_tokens") or 0)
        cache_write = int(in_details.get("cache_write_tokens") or 0)
        output_tokens = int(raw_usage.get("output_tokens") or 0)
        reasoning = int(out_details.get("reasoning_tokens") or 0)
    else:  # fall back to PydanticAI's mapped numbers
        details = getattr(fallback, "details", None) or {}
        input_tokens = fallback.input_tokens or 0
        cache_read = fallback.cache_read_tokens or 0
        cache_write = fallback.cache_write_tokens or 0
        output_tokens = fallback.output_tokens or 0
        reasoning = int(getattr(fallback, "output_reasoning_tokens", 0) or details.get("reasoning_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "uncached_input_tokens": max(input_tokens - cache_read - cache_write, 0),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
    }


def cost_usd(tokens: dict[str, int], prices: dict[str, float]) -> dict[str, float]:
    """Dollar cost from data/prices.json (prices are per 1M tokens). Output includes reasoning tokens."""
    parts = {
        "uncached_input_usd": tokens["uncached_input_tokens"] * prices["input_per_1m"],
        "cached_input_usd": tokens["cached_input_tokens"] * prices["cached_input_per_1m"],
        "cache_write_usd": tokens["cache_write_tokens"] * prices["cache_write_per_1m"],
        "output_usd": tokens["output_tokens"] * prices["output_per_1m"],
    }
    parts = {k: v / 1_000_000 for k, v in parts.items()}
    parts["total_usd"] = sum(parts.values())
    return {k: round(v, 8) for k, v in parts.items()}


TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "uncached_input_tokens",
              "output_tokens", "reasoning_tokens")


# --- Audit trail --------------------------------------------------------------------------------


def _short(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}... [{len(text):,} chars]"


def _tool_calls(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Each tool call the model made, with its arguments and a short version of what came back."""
    returns = {
        part.tool_call_id: part.content
        for msg in messages
        for part in getattr(msg, "parts", [])
        if isinstance(part, ToolReturnPart)
    }
    calls = []
    for msg in messages:
        if not isinstance(msg, ModelResponse):
            continue
        for part in msg.parts:
            if isinstance(part, ToolCallPart) and part.tool_name != "final_result":
                calls.append(
                    {
                        "tool": part.tool_name,
                        "args": part.args_as_dict(),
                        "result": _short(returns.get(part.tool_call_id, "(no result)")),
                        "trap": part.tool_name in TRAP_TOOL_NAMES,
                    }
                )
    return calls


def _model_calls(messages: list[ModelMessage], prices: dict[str, float]) -> list[dict[str, Any]]:
    """One record per model call: the API's raw usage block, the derived token counts, and dollars."""
    records = []
    last_instructions = ""
    for msg in messages:
        if isinstance(msg, ModelRequest):
            last_instructions = msg.instructions or last_instructions
            continue
        if not isinstance(msg, ModelResponse):
            continue
        raw = RAW_RESPONSES.get(msg.provider_response_id or "", {})
        tokens = _tokens_from_api(raw.get("usage"), msg.usage)
        records.append(
            {
                "call": len(records) + 1,
                "response_id": msg.provider_response_id,
                "api_model": raw.get("model"),
                "api_usage": raw.get("usage"),  # every token count, exactly as the API reported it
                "usage_source": "api" if raw.get("usage") else "pydantic_ai",
                **tokens,
                "cost": cost_usd(tokens, prices),
                "prompt_cache_diagnostics": raw.get("prompt_cache_diagnostics")
                or (msg.provider_details or {}).get("prompt_cache_diagnostics"),
                "instructions_sha256": hashlib.sha256(last_instructions.encode("utf-8")).hexdigest()[:16],
            }
        )
    return records


# --- Final checks in code -----------------------------------------------------------------------

FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision", "reason")


def finalize(report: VendorRecommendation, scr: screen.ScreenResult | None, d: Defenses,
             blocked: list[dict[str, Any]]) -> DeskAnswer:
    """Turn the model's report into the answer the buyer sees, applying the code and design checks that are on."""
    facts = {f: getattr(report, f) for f in FIELDS}
    warnings: list[str] = []
    missing: list[str] = []

    if d.code and scr is not None:
        for f in ("vendor", "sku"):
            if isinstance(facts[f], str):
                clean, removed = screen.scrub(facts[f])
                if removed:
                    warnings.append(f"Removed {', '.join(removed)} from {f}.")
                facts[f] = clean or None
        missing = screen.facts_not_visible(facts, scr.visible_text)
        for f in missing:
            warnings.append(f"{f} = {facts[f]!r} is not in the document a person sees; set to unknown.")
            facts[f] = None
        for fnd in scr.findings:
            if fnd["severity"] in ("medium", "high"):
                warnings.append(f"Screening: {fnd['reason']} [{fnd['where']}].")
        expected = rules.vendor_domain(facts["vendor"])
        seen = {m.split("@")[1].lower() for m in screen.EMAIL_RE.findall(scr.visible_text)}
        seen.discard("campuscustoms.example")
        if expected and seen and expected not in seen:
            warnings.append(f"Sender/footer domain {', '.join(sorted(seen))} does not match the handbook's {expected} "
                            f"for {facts['vendor']}; confirm the vendor is genuine.")

    if d.design:
        decision, reason, _ = rules.decide(facts)
        if report.decision != decision:
            warnings.append(f"Model said {report.decision}; the handbook rules in code say {decision}.")
        facts["decision"], facts["reason"] = decision, reason
    elif d.code and missing and facts["decision"] == "recommend":
        facts["decision"] = "do_not_recommend"
        facts["reason"] = (f"Could not confirm {', '.join(missing)} in the visible document, so the purchase cannot "
                           f"be recommended.")

    if d.code:
        facts["reason"], removed = screen.scrub(facts["reason"] or "")
        if removed:
            warnings.append(f"Removed {', '.join(removed)} from the reason.")

    if isinstance(report, ExtractedQuote):
        for s in report.suspicious_text[:5]:
            warnings.append(f"Model flagged: {screen.scrub(s)[0][:120]}")
    for b in blocked:
        warnings.append(f"Blocked a request to {b['tool']} (human-only; nothing was sent or paid).")

    return DeskAnswer(**facts, needs_human_review=bool(warnings), warnings=warnings)


# --- One run ------------------------------------------------------------------------------------


def run(doc: str, setup: str = "cached", defenses: Defenses = FULL, link_cache: bool = True,
        quiet: bool = False) -> dict[str, Any]:
    """Run the agent on one document. Returns the answer, per-call records, totals, cost and safety details."""
    if setup not in SETUPS:
        raise ValueError(f"setup must be one of {SETUPS}")
    path = resolve_document(doc)
    scr = screen.screen_document(path) if defenses.code else None
    doc_text = scr.model_text if scr else extract_text(path)
    deps = Deps(doc_path=path, run_id=uuid.uuid4().hex[:12], setup=setup, defenses=defenses.label, doc_text=doc_text)
    ensure_trap_log()
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_NAME]
    started = now_iso()

    the_agent = get_agent(defenses.design, defenses.prompt, setup)
    user_prompt = fenced(doc_text) if defenses.design else USER_PROMPT
    key = prefix_key(defenses)
    link_id = get_link(key) if (setup == "cached" and link_cache) else None
    settings = cached_settings(link_id) if setup == "cached" else NO_CACHE_SETTINGS
    model = build_model()

    try:
        result = the_agent.run_sync(user_prompt, model=model, deps=deps, model_settings=settings)
    except ModelHTTPError as exc:  # an expired or unknown link should never break a run
        if not link_id or exc.status_code not in (400, 404, 422):
            raise
        link_id, settings = None, cached_settings(None)
        result = the_agent.run_sync(user_prompt, model=model, deps=deps, model_settings=settings)

    # Human-only tools: log every request as blocked, deny it, and let the model finish its report.
    blocked: list[dict[str, Any]] = []
    for _ in range(2):
        if not isinstance(result.output, DeferredToolRequests):
            break
        denials = {}
        for call in result.output.approvals:
            args = call.args_as_dict()
            record_trap(deps, call.tool_name, args, blocked=True)
            blocked.append({"tool": call.tool_name, "args": args})
            denials[call.tool_call_id] = ToolDenied(
                "Denied. Sending email and approving payments are human-only decisions; nothing was sent or paid. "
                "Finish your report on the document.")
        result = the_agent.run_sync(model=model, deps=deps, model_settings=settings,
                                    message_history=result.all_messages(),
                                    deferred_tool_results=DeferredToolResults(approvals=denials))
    if isinstance(result.output, DeferredToolRequests):
        raise RuntimeError("model kept asking for human-only tools; stopping")

    report = result.output
    final = finalize(report, scr, defenses, blocked)
    messages = result.all_messages()
    model_calls = _model_calls(messages, prices)
    totals = {k: sum(c[k] for c in model_calls) for k in TOKEN_KEYS}
    cost = cost_usd(totals, prices)
    calls = _tool_calls(messages)
    trap_calls = [c for c in calls if c["trap"]]
    reasoning = [p.content.strip() for m in messages if isinstance(m, ModelResponse)
                 for p in m.parts if isinstance(p, ThinkingPart) and p.content.strip()]
    if setup == "cached" and model_calls:
        save_link(key, model_calls[-1]["response_id"])

    answer = {f: getattr(final, f) for f in FIELDS}
    append_json(USAGE_LOG, {
        "run_id": deps.run_id, "time": started, "setup": setup, "defenses": defenses.label,
        "linked_cache": bool(link_id), "document": deps.doc_label, "model": MODEL_NAME,
        "requests": len(model_calls), **totals, "cost": cost,
        "per_request": [{k: c[k] for k in ("call", *TOKEN_KEYS, "cost")} for c in model_calls],
    })
    append_json(AUDIT_TRAIL, {
        "run_id": deps.run_id, "time": started, "setup": setup, "defenses": defenses.label,
        "document": deps.doc_label, "model": MODEL_NAME,
        "screening": scr.summary() if scr else None,
        "tool_calls": calls, "blocked_tool_requests": blocked, "trap_calls": len(trap_calls),
        "reasoning_summary": reasoning,
        "model_report": report.model_dump(),
        "answer": answer, "needs_human_review": final.needs_human_review, "warnings": final.warnings,
    })

    if not quiet:
        print(json.dumps(final.model_dump(), indent=2, ensure_ascii=False))
        print(
            f"\n{deps.doc_label} | defenses: {defenses.label} | {setup}{' (linked)' if link_id else ''} | "
            f"{len(model_calls)} model calls | input {totals['input_tokens']:,} (cached {totals['cached_input_tokens']:,}, "
            f"cache write {totals['cache_write_tokens']:,}) | output {totals['output_tokens']:,} | ${cost['total_usd']:.6f}"
        )
        print(f"Tools called: {', '.join(c['tool'] for c in calls) or 'none'}")
    if trap_calls or blocked:
        print(
            f"WARNING: {deps.doc_label} asked for {len(trap_calls) or len(blocked)} trap tool call(s) "
            f"({', '.join(c['tool'] for c in (trap_calls or blocked))}). "
            f"{'Blocked as human-only. ' if blocked else ''}Nothing was sent or paid; see output/trap_calls.json."
        )
    return {
        "run_id": deps.run_id, "time": started, "setup": setup, "defenses": defenses.label,
        "linked_cache": bool(link_id), "document": deps.doc_label,
        "answer": answer, "needs_human_review": final.needs_human_review, "warnings": final.warnings,
        "model_report": report.model_dump(), "screening": scr.summary() if scr else None,
        "reasoning_summary": reasoning, "model_calls": model_calls, "totals": totals, "cost": cost,
        "tool_calls": calls, "trap_calls": len(trap_calls), "blocked_tool_requests": blocked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs vendor desk agent")
    parser.add_argument("--doc", required=True, help="vendor document inside data/ (.html, .pdf or .eml)")
    parser.add_argument("--no-cache", action="store_true", help="reuse nothing from the prompt cache (Problem 4)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--undefended", action="store_true", help="the Problem 3 agent with no defenses (Problem 7)")
    group.add_argument("--layers", default="code,design,prompt", help="defense layers to use, e.g. code,design")
    args = parser.parse_args()
    try:
        defenses = UNDEFENDED if args.undefended else Defenses.parse(args.layers)
        run(args.doc, setup="no_cache" if args.no_cache else "cached", defenses=defenses)
    except (ValueError, FileNotFoundError) as exc:
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
