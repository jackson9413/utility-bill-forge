"""Generate the questions to ask the utility.

A finding tells you what is wrong; this turns it into the exact wording to
use on the phone, ordered so the highest-value question comes first.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Questions keyed by the finding that raises them. Each is written the way you
# would actually say it to a customer-service rep.
QUESTIONS: Dict[str, List[str]] = {
    "recon_mismatch": [
        "I need an itemised breakdown of every charge on this bill - my copy does not add up to the amount due.",
    ],
    "unclassified_charges": [
        "There are charges on my bill I cannot identify. For each one, what is the tariff provision it comes from, and is it pass-through or discretionary?",
    ],
    "late_fee": [
        "I was charged a late payment fee. Can this be waived, and what is the grace period and late-payment policy on my account?",
    ],
    "estimated_read": [
        "My usage this period was estimated, not metered. When will you take an actual read, and how is the true-up calculated?",
    ],
    "trueup": [
        "This bill contains a true-up. What was the original estimate, what actual read caused it, and can I move to budget billing instead?",
    ],
    "deposit": [
        "I have a deposit on my account. What is it being held for, when is it refunded, and how is it credited?",
    ],
    "tier_cliff": [
        "My usage crosses a rate tier threshold this month. What is the exact threshold, and what options do I have to move to a rate plan without that cliff for my usage level?",
    ],
    "peak_exposure": [
        "What are my on-peak and off-peak windows and their rates? Is there a plan with an EV or overnight period, and how do I get on it?",
    ],
    "demand_heavy": [
        "My demand charge is a large share of this bill. Can you tell me my metered peak interval, what drove it, and whether a lower contracted demand is available?",
    ],
    "rate_above_band": [
        "Can you give me a written comparison of at least three rate plans for my exact usage profile, and a tariff sheet for each?",
    ],
    "rider_stack": [
        "Can you break down the dollar impact of each rider on my bill individually, and tell me which are regulated and which are discretionary?",
    ],
    "credit_unexplained": [
        "There is a credit on my bill I cannot identify. What is it worth, what is it tied to, and does it expire or get re-billed?",
    ],
    "odd_period": [
        "This bill covers an unusual number of days. Why is the period not a normal cycle, and can you confirm the usage was not prorated?",
    ],
    "tax_base_narrow": [
        "What is the taxable basis for the taxes on my bill - is it the commodity charge only, or the full delivered amount?",
    ],
    "no_commodity_split": [
        "Can you tell me what portion of my rate is commodity and what portion is delivery, even if the bill combines them?",
    ],
    "no_delivery_split": [
        "Can you tell me what portion of my rate is commodity and what portion is delivery, even if the bill combines them?",
    ],
    "duplicate_charge": [
        "I see the same charge twice on this bill. Does this cover a second meter or unit, or is it a duplicate?",
    ],
    "fixed_dominant": [
        "What is the fixed portion of my rate, and would a smaller service size or a different rate plan reduce it?",
    ],
    "ev_present": [
        "Do I have a separate EV or overnight charging period on my account, and how do I confirm my charging is being billed in it?",
    ],
}

GENERIC = [
    "Can you send me a tariff sheet for my current rate, and tell me when it was last filed with the regulatory commission?",
    "What is my current rate plan name and tariff number, and what alternatives am I eligible for?",
]


def build_call_script(findings: List[Dict[str, Any]], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Build an ordered call script from the findings on this bill."""
    order = {"high": 0, "medium": 1, "low": 2}
    ranked = sorted(findings, key=lambda f: (order.get(f.get("severity", "low"), 3),
                                             f.get("id", "")))

    questions: List[Dict[str, Any]] = []
    seen = set()
    for f in ranked:
        for q in QUESTIONS.get(f.get("id", ""), []):
            if q in seen:
                continue
            seen.add(q)
            questions.append({"question": q, "because": f.get("title"), "severity": f.get("severity")})

    for q in GENERIC:
        if q not in seen:
            seen.add(q)
            questions.append({"question": q, "because": "Always worth asking", "severity": "low"})

    prep: List[str] = []
    total = metrics.get("total")
    if total:
        prep.append("Have this bill and your account number in front of you.")
    if metrics.get("usage"):
        prep.append("Know your usage: " + "{0:,.0f} {1} this period.".format(
            metrics["usage"], metrics.get("unit") or ""))
    if metrics.get("all_in_rate"):
        prep.append("Know your all-in rate: " + "{0}".format(
            round(metrics["all_in_rate"] * 100, 2)) + "c per " + str(metrics.get("unit") or "unit")
            + " (or " + str(round(metrics["all_in_rate"], 3)) + " for non-electric utilities).")
    if metrics.get("period_start"):
        prep.append("Know your billing period: " + str(metrics["period_start"]) + " to "
                    + str(metrics.get("period_end") or "?") + ".")
    prep.append("Ask for a reference number for every call. If anything is disputed, ask for the "
                "dispute process in writing.")

    return {
        "questions": questions,
        "prep": prep,
        "dispute_hint": _dispute_hint(findings, metrics),
    }


def _dispute_hint(findings: List[Dict[str, Any]], metrics: Dict[str, Any]) -> str:
    """A short, honest note on whether disputing is worth it."""
    ids = {f.get("id") for f in findings}
    delta = metrics.get("reconciliation_delta")
    if delta is not None and abs(delta) > 1.0:
        return ("The line items do not reconcile with the total, so this bill has a concrete "
                "error to point at. Get an itemised PDF and ask for the missing line. If they "
                "cannot produce one that adds up, escalate to your state public utility "
                "commission.")
    if "estimated_read" in ids:
        return ("The usage is an estimate, not a meter read. This is usually not a dispute - it is "
                "a true-up. Ask for the actual read date and let the next bill correct it.")
    if "tier_cliff" in ids:
        return ("Nothing here is wrong - the bill is correct. The issue is that the rate structure "
                "punishes your usage level, which is a plan-change conversation rather than a "
                "complaint. Ask for a written plan comparison instead of disputing the charge.")
    if "rate_above_band" in ids:
        return ("The rate is above a typical band but is not by itself an error. The productive "
                "path is shopping for a different plan rather than disputing this bill.")
    if not findings:
        return ("Nothing on this bill is worth disputing. Save the analysis so you can compare it "
                "against future bills and catch a rate change when it happens.")
    return ("No single item here is clearly an error. Take the questions above, get written "
            "answers, and if the answers do not add up, escalate to your state public utility "
            "commission.")
