# Utility Bill Forge

**Paste a utility bill. Find out what you actually pay, what is wrong with it, and what to do about it.**

A local-first utility bill analyzer. It reads a pasted bill, rebuilds the cost
structure, works out what your *next* unit of usage costs (not just the average),
flags the things worth contesting, quantifies the money on the table, and writes
you a call script.

No API keys. No LLM. No network calls. Your bill text never leaves your machine.

---

## Why this exists

A utility bill is deliberately hard to read. The number at the bottom is the
only one most people look at, and it tells you almost nothing about what to do.

The thing that actually matters is the **marginal rate**: what the *next* kWh
costs, not the average of everything you used this month. On a tiered rate those
are very different numbers. A household 90 kWh past a tier threshold sees an
average rate of 12.31c and a marginal rate of 15.87c - the bill understates
what their usage actually costs by 29%. On a time-of-use rate the gap between
on-peak and off-peak can be 2x. On a commercial bill, the demand charge is
billed on a single worst interval and can be a third of the total.

This tool reads those structures off the bill itself and tells you where the
cliff is, how many kWh you need to shed to get back under it, and what that is
worth in dollars per year.

## What it does

**Cost decomposition.** Every line item is classified into a billing bucket -
energy/commodity, delivery/distribution, fuel adjustment, demand charge,
taxes, fees and penalties, policy riders, fixed base charges, credits,
deposits, adjustments, and anything it could not identify. You get the
all-in rate, the commodity rate, the marginal rate, and the fixed/variable
split, each with its share of the bill.

**Rate structure detection.** Flat, tiered, time-of-use, demand-based and
net-metering designs are inferred from the bill's own wording. For tiered
bills it reads the tier boundaries ("First 600 kWh", "Next 300 kWh",
"Over 1,500 kWh", "0-500 kWh") and works out which tier your *last* unit fell
into, how many units you must shed to fall back to a cheaper one, and what
that saves.

**Findings.** 20+ rules covering reconciliation failures, unclassified
charges, late fees, estimated reads, true-ups, tier cliffs, peak-hour exposure,
demand-charge dominance, rate bands, rider stacks, tax bases, duplicate
charges, deposits, odd billing periods and more. Every finding carries the
evidence that triggered it, why it matters, and a concrete thing to do.

**Savings scenarios.** Quantified from the bill's own numbers: fall back one
tier, shift flexible loads off peak, schedule EV charging into the off-peak
window, lower billed peak demand, cut consumption, renegotiate the fixed part
of the rate, move off estimated billing, audit the rider stack. Each states
the assumption it rests on and degrades its confidence accordingly.

**A call script.** The findings are turned into the exact questions to ask
customer service, ordered so the highest-value question comes first, with a
prep list and an honest note on whether disputing is even worth it.

**Multi-bill comparison.** Paste several bills separated by a line of dashes
and it will chart the usage trend, the rate trend, and fixed-charge creep, and
flag the moves that need explaining.

**A five-axis scorecard.** Clarity, correctness, value, structure and control,
with structural caps so a bill cannot score well by skipping the hard part -
no usage found caps correctness and value, an unreconciled bill caps
correctness, an estimated read caps correctness.

## Quick start

```bash
git clone https://github.com/jackson9413/utility-bill-forge.git
cd utility-bill-forge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:8787>.

Paste a bill and press **Analyze bill**, or click **Load a sample** to try it
against the six built-in synthetic bills.

## Using it on your own bill

1. Open the bill as a PDF and copy the text, or screenshot it and paste
   whatever you can read. The line items matter most - the header does not.
2. Include the usage line ("Total Usage: 690 kWh") if you can find it.
3. Include the total amount due.
4. Press Analyze.

Nothing is uploaded. The engine runs in-process against your text.

## Samples

| Sample | What it exercises |
| --- | --- |
| `tiered_residential` | Tier cliff - 90 kWh past a 600 kWh threshold |
| `tou_ev` | Time-of-use with EV charging at peak, a late fee, a demand charge |
| `commercial_demand` | Demand charges and fixed service charges dominating |
| `estimated_trueup` | Estimated read, true-up, deposit, unidentifiable charges |
| `clean_bill` | A tidy bill - the tool should find nothing |
| `two_bill_compare` | Two periods side by side, with a usage and rate change |

## Tech stack

- **Backend:** Python 3.9+, Flask. The analysis engine is pure standard
  library - no pandas, no numpy, no external parsing libraries.
- **Frontend:** vanilla HTML/CSS/JS. No build step, no framework, no CDN.
- **Storage:** SQLite, for a local log of past analyses with star ratings and
  notes.
- **Exports:** Markdown and JSON, with a `Content-Disposition` download header.

## Project layout

```
app.py                    Flask app and REST API
forge/
  parser.py               Bill text -> structured line items
  categorize.py           Line items -> billing buckets, rate structure detection
  analysis.py             Metrics, tier-ladder maths, findings rules
  scoring.py              Five-axis scorecard with structural caps
  savings.py              Quantified savings scenarios
  callscript.py           Findings -> questions to ask the utility
  benchmarks.py           Static reference rate bands
  engine.py               Orchestration, multi-bill comparison
  exporter.py             Markdown / JSON export
  store.py                SQLite session log
  samples.py              Built-in sample bills
templates/index.html
static/style.css, static/app.js
tests/
  test_engine.py          Engine unit tests
  api_smoke.py            End-to-end API test
  contract_check.py       Verifies every field the UI reads exists
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | The app |
| GET | `/api/health` | Liveness check |
| GET | `/api/samples` | List built-in samples |
| GET | `/api/sample/<id>` | One sample bill |
| POST | `/api/analyze` | Analyse bill text; returns the full result |
| GET | `/api/sessions` | List past analyses |
| GET | `/api/sessions/<id>` | One past analysis |
| PATCH | `/api/sessions/<id>` | Set star rating and/or notes |
| DELETE | `/api/sessions/<id>` | Delete a past analysis |
| GET | `/api/export/<id>?fmt=md|json` | Download an export |

`POST /api/analyze` takes `{"text": "...", "utility": "auto",
"customer_class": "auto", "profile": "residential"}`. All three options
default to automatic detection.

## Tests

```bash
python3 -m unittest discover -s tests   # 28 engine tests
python3 tests/api_smoke.py              # end-to-end API checks
python3 tests/contract_check.py         # frontend/backend field contract
```

## A note on the benchmarks

The reference rate bands in `forge/benchmarks.py` are approximate static US
averages, not live tariff data, and they are a sanity band rather than a quote.
State-level electricity prices vary enormously - roughly 8c/kWh in cheap hydro
states to 35c in expensive coastal ones - so a bill outside the band means
"worth comparing plans", not "you are being overcharged". Every band can be
overridden by editing that file.

## License

MIT
