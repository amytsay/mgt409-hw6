# With and Without Cached Tokens (HW6 Problem 4)

All 12 practice documents were run through the vendor desk agent twice: once with the handbook reused from
the prompt cache, once with nothing reused. Every model call (48 in total: 12 documents × 2 calls × 2 setups)
is in `output/cache_test.json`. Each record holds the setup, the document, the API's own `usage` block (every
token count it reported) and the dollar cost from `data/prices.json`. Script: `cache_test.py`.

Prices (gpt-6-luna, per 1M tokens): input $0.10 · cache write $0.125 · cached input $0.01 · output $0.50.

## 1. The two setups, and proof each did what it was meant to

| Setup | How it is built | What the API reported (all 24 calls) | Verdict |
|---|---|---|---|
| **Cached** | Instructions + handbook are static and identical on every call, with a cache breakpoint after them (PydanticAI `cache=CacheConfig(messages=False)`, 30-minute TTL) | Same prefix on every call (one `instructions_sha256` for all 24). **11 calls read 10,717 cached tokens**; 13 calls wrote the prefix to cache | Handbook reused from cache ✔ |
| **No cache** | Two locks: (1) OpenAI `prompt_cache_options.mode = "explicit"` with no breakpoint, so nothing is stored; (2) a random `Request id` line at the very start of every request, so no request's prefix can match anything stored earlier | **`cached_tokens` = 0 and `cache_write_tokens` = 0 on all 24 calls**; 24 different prefixes | Nothing reused from cache ✔ |

The token counts come straight from the API's `usage.input_tokens_details` (`cached_tokens`, `cache_write_tokens`),
captured from each raw response, not from a library estimate (`checks.all_usage_from_api = true` in the JSON).

## 2. Total cost and cost per document

| | Cached | No cache |
|---|---:|---:|
| Documents / model calls | 12 / 24 | 12 / 24 |
| Input tokens (all) | 263,942 | 264,496 |
| …read from cache | 117,887 | **0** |
| …written to cache | 139,321 | **0** |
| …uncached | 6,734 | 264,496 |
| Output tokens (incl. reasoning) | 1,717 (423) | 1,766 (419) |
| **Total cost** | **$0.020126** | **$0.027333** |
| **Cost per document** | **$0.001677** | **$0.002278** |
| Cost per model call | $0.000839 | $0.001139 |

**Percent saved with cache: 26.4%** = ($0.027333 − $0.020126) / $0.027333.

Where the cached setup's money went: cache writes $0.017415 (**86.5%**), cached reads $0.001179 (5.9%),
output $0.000859 (4.3%), uncached input $0.000673 (3.3%). Nearly all of it is the 1.25× write on each run's first call.

Per document, every cached run followed the same pattern (p01 shown):

| Call | What it does | Input | Cached | Written | Cost |
|---|---|---:|---:|---:|---:|
| 1 | Reads the instructions + handbook, asks for `read_document` | 10,857 | 0 | 10,717 | $0.001361 |
| 2 | Gets the document back, returns the answer | 11,297 | 10,717 | 0 | $0.000217 |

Answers were the same in both setups: caching changes cost, not what the model sees. Both setups got 8 of 12 answers fully right (all facts and the
decision); counting decisions alone, cached got 9 (p07's right only by luck) and no-cache 8. p02, p03, p07 and p12 were fooled by hidden text in the documents. That is Problem 5.

## 3. Measured numbers vs. the Problem 2 estimate

| Item | Problem 2 estimate | Measured | Why they differ |
|---|---:|---:|---|
| Tokens reused from cache each call | 10,058 (handbook) | **10,717** | The cached prefix is more than the handbook: prompt.md instructions (424) + separator, then tool definitions and message framing (234). Instructions plus handbook are 10,483 tokens |
| Handbook prefix, one uncached call | $0.0010058 | $0.0010717 | Same price, 6.6% more tokens |
| Handbook prefix, one cached read | $0.00010058 | $0.00010717 | Same price, 6.6% more tokens |
| Cache write | $0.00125725 | $0.00133963 | Same 1.25× price, 6.6% more tokens |
| One model call, no cache (everything) | $0.0010058 (handbook only) | $0.0011389 | Adds the document, the agent's own messages and output tokens |
| **Calls per document** | 1 (assumed) | **2** | The agent reads the document with a tool: call 1 asks for it, call 2 answers. The handbook is sent twice per document |
| Cost per document, no cache | $0.0010058 | **$0.0022777** | 2.26×: two calls, plus everything besides the handbook |
| 1,000 calls with cache | $0.1017 (1 write + 999 reads) | **$0.8386** as tested | Problem 2 assumed one write ever. In practice every run wrote once (13 writes in 24 calls) |
| 128-token rounding (Problem 2 note) | 9,984 cached tokens | 10,717 exactly | gpt-6-luna (GPT-5.6+) reports the exact breakpoint, no 128-token rounding |

The handbook math from Problem 2 held up: price × tokens matches to the cent. What it missed is how the agent
runs: two calls per document, and caches that are not shared from one run to the next (section 5).

## 4. Projection: 1,000 documents a day for 30 days (30,000 documents)

| Setup | Cost per document | Per day | **30 days** | vs. no cache |
|---|---:|---:|---:|---:|
| No cache (as tested) | $0.002278 | $2.28 | **$68.33** | baseline |
| Cached, as tested (each run writes once) | $0.001677 | $1.68 | **$50.31** | −$18.02 (26.4%) |
| Cached + linked runs (section 5 fix, measured on 4 runs) | $0.000331 | $0.33 | **$9.93** | −$58.40 (85.5%) |
| Naive "no cache": random prefix but default caching left on (section 5) | $0.002828 | $2.83 | **$84.85** | +$16.52 (24% more) |

Assumptions: the same mix and size of documents as the 12 practice docs, 2 model calls per document, prices
from `data/prices.json`. 1,000 documents a day is about 0.7 per minute, well under the 15 requests a minute
where OpenAI starts sending requests to other machines. If the desk sits idle for more than 30 minutes the
cache expires and the next run pays one write ($0.0013); even once an hour that adds only $0.96 over the month (24 × 30 × $0.00134).

## 5. What surprised us, and why

**1. Caching saved 26%, not the ~90% Problem 2 predicted.** Every run's first call wrote the handbook to the cache
again instead of reading the copy the previous run had stored seconds earlier.
- *Not our prompt:* two back-to-back p01 runs sent **byte-identical** request bodies (a 0-line diff), and the second
  run still wrote instead of reading.
- *Why:* OpenAI keeps each cache entry on one machine, and a hit requires the request to reach that machine. A brand-new
  conversation's first request is routed without knowing where the last copy lives, so it misses and pays the 1.25×
  write. The second call in the same run goes back to the same machine and reads (11 of 12 runs). In p02 the second call
  missed too, so that run wrote twice.
- *Proof and fix:* we pointed each run at the previous run's response with `prompt_cache_options.comparison_response_id`.
  That is a free diagnostics option, but it also sends the request to the machine that served the earlier response. With
  it, **4 of 4 linked runs read the cache on their first call**, and a document cost $0.00033 instead of $0.00168.
  Caveat: OpenAI documents this option for diagnostics. It routing to the cache is behavior we measured, not a
  documented guarantee. (Experiments: `follow_up_experiments` in `cache_test.json`.)

**2. A cached first call costs *more* than an uncached one.** Writing costs 1.25× the plain input price, so call 1 of a
cached run ($0.00136) costs more than call 1 with no cache (about $0.00109). Caching only pays off when a later call
actually reads what was written. With two calls per run and no reuse between runs, one cheap read has to make up for one
expensive write, which is why the savings were only 26%.

**3. A "no cache" setup can cost more than the plain input price.** The obvious way to switch caching off is to make every
prefix unique, so nothing can ever be read back. But gpt-6-luna's default (implicit) mode still *stores* every prompt and
bills it as a cache write at 1.25×, even though the copy is never read. We measured it: random prefix only, default
caching on, gave 0 cached tokens but 10,751 + 11,191 tokens written, **$0.00283 per document, 24% more than true no-cache
($0.00228)**. Our no-cache setup avoids this with the second lock: `mode = "explicit"` and no breakpoint means nothing
is stored at all, which the zero `cache_write_tokens` on all 24 calls confirms. "No reads" and "no writes" are different
things, and only "no writes" gets you the plain $0.10/1M price.

**4. Two model calls per document doubles the handbook bill.** Problem 2 priced one call per document. Because the
document is fetched with a tool, the model is called once to ask for it and again to answer, and the 10,717-token prefix
goes out both times. Input tokens are 97% of the no-cache cost; output is only about 147 tokens per document (3%).

**5. Smaller surprises.**
- No 128-token rounding: the API reported exactly 10,717 cached tokens, so Problem 2's 9,984 sensitivity case does not
  apply to this model.
- OpenAI's `prompt_cache_diagnostics` field came back empty through Portkey, so the cause in point 1 was found by
  experiment rather than read from the API.
- Reasoning at "low" effort used only about 18 reasoning tokens per call, so output cost stayed tiny.

**Bottom line for the shop:** caching works, but only if runs land where the cache is. As built, cache saves 26%
($18 a month at 1,000 documents a day). Linking runs to the previous response brings it to about 86% ($58 a month), and a
careless "no cache" setting would *add* 24%. The token counts the API sends back are the only way to tell these apart,
so the agent logs them on every call.
