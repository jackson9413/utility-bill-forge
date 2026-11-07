"""Top-level analysis engine: single bill and multi-bill comparison."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .analysis import compute_metrics, run_rules
from .benchmarks import BENCHMARKS, UTILITY_TO_BENCHMARK
from .callscript import build_call_script
from .categorize import classify_bill, detect_structure
from .parser import ParsedBill, parse_bill
from .savings import build_savings
from .scoring import score_bill

# Bills can be separated by a line of dashes / equals / "bill N" marker.
BILL_SPLIT_RE = re.compile(
    r"^\s*(?:[-=]{5,}|\*{5,}|#{2,}\s*bill\s*\d+.*|bill\s*\d+\s*[-–—:]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

COMMERCIAL_MARKERS = re.compile(
    r"\b(business|commercial|industrial|restaurant|office|warehouse|store|billing account|"
    r"master meter|multifamily|multi-family|small business)\b",
    re.IGNORECASE,
)


def detect_customer_class(text: str, usage: Optional[float] = None) -> str:
    if COMMERCIAL_MARKERS.search(text):
        return "commercial"
    if usage is not None and usage > 3000:
        return "commercial"
    return "residential"


def split_bills(text: str) -> List[str]:
    parts = [p.strip() for p in BILL_SPLIT_RE.split(text)]
    parts = [p for p in parts if p and len(p.splitlines()) >= 3]
    return parts or ([text.strip()] if text.strip() else [])


def analyze_bill(
    text: str,
    utility_hint: str = "auto",
    customer_class: str = "auto",
    profile: str = "residential",
) -> Dict[str, Any]:
    bill = parse_bill(text, utility_hint if utility_hint != "auto" else None)
    structure = detect_structure(bill)
    metrics = compute_metrics(bill, structure)

    cls = customer_class
    if cls == "auto":
        cls = detect_customer_class(text, metrics.get("usage"))
    metrics["customer_class"] = cls
    metrics["utility"] = bill.utility
    metrics["structure_kind"] = structure["kind"]

    findings = run_rules(bill, metrics, structure, text)
    score = score_bill(metrics, findings, profile)
    savings = build_savings(metrics, structure, findings, text, cls)
    call_script = build_call_script(findings, metrics)

    bench_key = UTILITY_TO_BENCHMARK.get((bill.utility, cls))
    metrics["benchmark"] = BENCHMARKS.get(bench_key) if bench_key else None

    return {
        "bill": bill.to_dict(),
        "structure": structure,
        "metrics": metrics,
        "findings": findings,
        "score": score,
        "savings": savings,
        "call_script": call_script,
    }


def analyze(text: str, utility_hint: str = "auto", customer_class: str = "auto",
            profile: str = "residential") -> Dict[str, Any]:
    chunks = split_bills(text)
    results = [
        analyze_bill(chunk, utility_hint, customer_class, profile)
        for chunk in chunks
    ]
    comparison = None
    if len(results) > 1:
        comparison = compare_bills(results)

    if not results:
        return {
            "bill_count": 0,
            "bills": [],
            "primary": None,
            "comparison": None,
            "error": "No bill content was found. Paste the bill text (including the line items) and try again.",
        }

    primary = results[0]
    return {
        "bill_count": len(results),
        "bills": results,
        "primary": primary,
        "comparison": comparison,
    }


# ---------------------------------------------------------------------------
# Multi-bill comparison
# ---------------------------------------------------------------------------


def compare_bills(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for idx, res in enumerate(results):
        m = res["metrics"]
        rows.append({
            "index": idx,
            "period_start": m.get("period_start"),
            "period_end": m.get("period_end"),
            "period_days": m.get("period_days"),
            "total": m.get("total"),
            "usage": m.get("usage"),
            "unit": m.get("unit"),
            "all_in_rate": m.get("all_in_rate"),
            "commodity_rate": m.get("commodity_rate"),
            "fixed": m.get("fixed"),
            "score": res["score"]["overall"],
            "verdict": res["score"]["verdict"],
            "utility": m.get("utility"),
        })

    notes: List[Dict[str, Any]] = []

    # Usage trend
    usage_series = [(r["index"], r["usage"]) for r in rows if r.get("usage")]
    if len(usage_series) >= 2:
        first, last = usage_series[0][1], usage_series[-1][1]
        if first:
            pct = (last - first) / first * 100
            if abs(pct) >= 15:
                direction = "higher" if pct > 0 else "lower"
                notes.append({
                    "id": "usage_trend",
                    "severity": "medium" if abs(pct) >= 30 else "low",
                    "title": "Usage moved " + direction + " across these bills",
                    "detail": "Usage went from " + format(first, ".0f") + " to " + format(last, ".0f")
                              + " (" + format(pct, "+.1f") + "%). A large move is worth explaining before "
                              "you assume it is a rate problem - a new appliance, a habit change, a "
                              "cold snap, or an estimated read all look the same here.",
                })

    # Rate trend
    rate_series = [(r["index"], r["all_in_rate"]) for r in rows if r.get("all_in_rate")]
    if len(rate_series) >= 2:
        r0 = rate_series[0][1]
        r1 = rate_series[-1][1]
        if r0:
            pct = (r1 - r0) / r0 * 100
            if abs(pct) >= 8:
                direction = "higher" if pct > 0 else "lower"
                notes.append({
                    "id": "rate_trend",
                    "severity": "medium" if abs(pct) >= 20 else "low",
                    "title": "Your all-in rate moved " + direction,
                    "detail": "The all-in rate went from " + format(r0 * 100, ".2f") + "c to "
                              + format(r1 * 100, ".2f") + "c per unit (" + format(pct, "+.1f") + "%). "
                              "If usage stayed flat, the rate itself is what changed.",
                })

    # Fixed cost creep
    fixed_series = [(r["index"], r["fixed"]) for r in rows if r.get("fixed") is not None]
    if len(fixed_series) >= 2:
        f0 = fixed_series[0][1]
        f1 = fixed_series[-1][1]
        if f0 and abs(f1 - f0) / f0 > 0.15:
            notes.append({
                "id": "fixed_creep",
                "severity": "medium",
                "title": "Fixed charges moved without your usage moving",
                "detail": "Fixed charges went from $" + format(f0, ".2f") + " to $" + format(f1, ".2f")
                          + ". Fixed costs do not respond to conservation, so if your total bill rose "
                          "while usage stayed flat, this is where it came from.",
            })

    best = min(rows, key=lambda r: r["all_in_rate"] or 9e9) if any(r.get("all_in_rate") for r in rows) else None
    worst = max(rows, key=lambda r: r["all_in_rate"] or -9e9) if any(r.get("all_in_rate") for r in rows) else None

    return {
        "rows": rows,
        "notes": notes,
        "best_bill": best["index"] if best else None,
        "worst_bill": worst["index"] if worst else None,
        "best_rate": best["all_in_rate"] if best else None,
        "worst_rate": worst["all_in_rate"] if worst else None,
        "rate_spread": (worst["all_in_rate"] - best["all_in_rate"])
        if (best and worst and best["all_in_rate"] and worst["all_in_rate"]) else None,
    }
