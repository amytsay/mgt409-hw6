# Handbook Size and Cost Estimate (HW6 Problem 2)

The vendor desk agent sends `data/shop_handbook.md` (the Campus Customs Shop Handbook) to `gpt-6-luna`
on **every** call. This file estimates what that handbook alone costs. Problem 4 will check these numbers
against the token counts reported by real runs.

## 1. Token count

**Handbook = 10,058 tokens**

### How I got it

I tokenized the full file locally with OpenAI's `tiktoken` library (v0.14.0), using the `o200k_base`
encoding. That is the tokenizer used by OpenAI's current GPT model families, so it is the best local stand-in
for `gpt-6-luna`. Counting locally makes no API call and costs $0.

Reproduce it from `hw6/` with:

```
python estimate_handbook.py
```

`estimate_handbook.py` reads the handbook as UTF-8 text, runs `len(tiktoken.get_encoding("o200k_base").encode(text))`,
then applies the prices from `data/prices.json`.

### Cross-checks

| Method | Count | Notes |
|---|---:|---|
| `tiktoken` `o200k_base` (used) | **10,058** | Tokenizer for current OpenAI models |
| `tiktoken` `cl100k_base` | 10,184 | Older GPT-4 tokenizer, +1.3%. The answer barely depends on which tokenizer |
| Rule of thumb: words × 4/3 | 6,127 × 1.33 ≈ 8,169 | Underestimates by about 19% |
| Rule of thumb: characters ÷ 4 | 28,903 ÷ 4 ≈ 7,226 | Underestimates by about 28% |

The rules of thumb come in low because the handbook is mostly tables. Pipes (`|`), SKU codes (`CC-HD-006`),
prices and dates split into many short tokens. Real tokenization was worth doing: guessing from word count
would have understated the cost by about 20%.

## 2. Prices used

From `data/prices.json` (gpt-6-luna, OpenAI Standard pricing, per 1M tokens):

| Price | $ per 1M tokens | $ per token |
|---|---:|---:|
| Input, not cached | $0.10 | $0.0000001 |
| Cache write (first time the handbook is stored) | $0.125 | $0.000000125 |
| Cached input (later calls that reuse it) | $0.01 | $0.00000001 |

## 3. Formulas

Let **T** = handbook tokens = 10,058, and **N** = number of calls.

```
cost per call, no cache    = T × input_price        / 1,000,000
cost per call, cache write = T × cache_write_price  / 1,000,000
cost per call, cache read  = T × cached_input_price / 1,000,000

N calls, no cache = N × T × input_price / 1,000,000
N calls, cached   = (1 cache write) + (N − 1 cache reads)
                  = [T × cache_write_price + (N − 1) × T × cached_input_price] / 1,000,000
```

Assumption for the cached case: the first call writes the handbook into the cache, and every later call reads
it back. That requires the handbook to sit at the **start** of the prompt, word-for-word the same on every call,
and calls close enough together that the cache does not expire.

## 4. One call

| Case | Math | Cost |
|---|---|---:|
| **No cache** | 10,058 × $0.10 / 1,000,000 | **$0.00100580** |
| **Cached (warm cache, read)** | 10,058 × $0.01 / 1,000,000 | **$0.00010058** |
| Cache write (first call ever) | 10,058 × $0.125 / 1,000,000 | $0.00125725 |

So one call costs about **one-tenth of a cent** without caching and **one-hundredth of a cent** when the
handbook is read from cache.

Note: the very first call costs *more* with caching ($0.00125725 vs $0.00100580), because the cache write
price is 25% above the normal input price. Caching pays off from the second call on.

## 5. 1,000 calls

**No cache**

```
1,000 × 10,058 × $0.10 / 1,000,000
= 10,058,000 tokens × $0.10 / 1,000,000
= $1.0058
```

**With cache** (1 write + 999 reads)

```
write:  1   × 10,058 × $0.125 / 1,000,000 = $0.00125725
reads:  999 × 10,058 × $0.01  / 1,000,000 = 10,047,942 × $0.01 / 1,000,000 = $0.10047942
total:  $0.00125725 + $0.10047942          = $0.10173667  ≈ $0.1017
```

## 6. Summary

| | 1 call | 1,000 calls |
|---|---:|---:|
| **Without cached tokens** | $0.00100580 | **$1.0058** |
| **With cached tokens** | $0.00010058 (warm) / $0.00125725 (first call writes the cache) | **$0.1017** |
| **Savings from caching** | 90% per warm call | $0.9041 saved (**89.9%**) |

Savings at 1,000 calls: ($1.0058 − $0.1017) / $1.0058 = 89.9%.

## 7. What this does not include (for the Problem 4 check)

These estimates cover **only the handbook**. A real call also sends, and pays for:

- **The system prompt and the vendor document.** The document changes every call, so it is never cached.
- **Message framing.** The chat format adds a few tokens per message, so a real run will report slightly more
  than 10,058 input tokens.
- **Output tokens**, including reasoning, at $0.50 per 1M. That is 5× the input price, so long answers add up.
- **OpenAI cache rules.** OpenAI only caches prompts of 1,024+ tokens, and counts cached tokens in 128-token
  steps after the first 1,024. At most 1,024 + ⌊(10,058 − 1,024) / 128⌋ × 128 = **9,984** handbook tokens show up as
  cached; the last 74 are billed at the full price. That makes a warm call about 9,984 × $0.01/1M + 74 × $0.10/1M
  = $0.00010724, and 1,000 calls about **$0.1084** instead of $0.1017. The real gain comes from the shared
  prefix (system prompt + handbook) as a whole, so Problem 4's `cached_tokens` will tell us the actual number.
- **Cache expiry.** A cache that goes cold after a few idle minutes means another full-price write. Batch the
  calls close together to keep it warm.

**Design rule for the agent:** put the handbook first in the prompt, unchanged byte-for-byte, and put the
changing vendor document after it. Anything that changes before the handbook (a timestamp, a document name)
breaks the cache and puts the cost back up near $1.01 per 1,000 calls.
