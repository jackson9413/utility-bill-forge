"""Five-axis scoring with structural caps."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .benchmarks import BENCHMARKS, UTILITY_TO_BENCHMARK

AXES = [
    ("clarity", "Clarity", "Can you read what you are paying for?"),
    ("correctness", "Correctness", "Does the arithmetic and the billing hold up?"),
    ("value", "Value", "Is the rate itself competitive?"),
    ("structure", "Structure", "Does the rate design fit how you use power?"),
    ("control", "Control", "How much of this bill can you actually move?"),
]

# Profiles shift the axis weights to match what matters for that customer type.
PROFILE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "residential": {"clarity": 0.20, "correctness": 0.26, "value": 0.22, "structure": 0.17, "control": 0.15},
    "commercial": {"clarity": 0.15, "correctness": 0.20, "value": 0.20, "structure": 0.25, "control": 0.20},
    "landlord": {"clarity": 0.22, "correctness": 0.26, "value": 0.22, "structure": 0.15, "control": 0.15},
}

SEVERITY_WEIGHT = {"high": 1.0, "medium": 0.55, "low": 0.22}


def _axis_scores(m: Dict[str, Any], findings: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    scores: Dict[str, Dict[str, Any]] = {}

    # ---- clarity ----------------------------------------------------------
    clarity = 100.0
    total = m["total"] or 0.0
    if total > 0 and m["unclassified"] > 0:
        share = m["unclassified"] / total
        clarity -= min(45.0, share * 120)
    if m["total"] is None or m["stated_total"] is None:
        clarity -= 22
    if not m["usage"]:
        clarity -= 18
    if len(m["buckets"]) <= 3 and total > 0:
        clarity -= 10
    clarity -= sum(6.0 * SEVERITY_WEIGHT[f["severity"]] for f in findings if f["axis"] == "clarity")
    scores["clarity"] = {"score": max(0.0, min(100.0, clarity))}

    # ---- correctness ------------------------------------------------------
    correct = 100.0
    delta = m["reconciliation_delta"]
    if delta is not None:
        if abs(delta) > 1.0:
            correct -= min(40.0, 12 + abs(delta))
        elif abs(delta) > 0.05:
            correct -= 6
    if not m["usage"]:
        correct -= 25
    if m["usage_estimated"]:
        correct -= 10
    if m["period_days"] is not None and (m["period_days"] < 20 or m["period_days"] > 45):
        correct -= 8
    correct -= sum(11.0 * SEVERITY_WEIGHT[f["severity"]] for f in findings if f["axis"] == "correctness")
    scores["correctness"] = {"score": max(0.0, min(100.0, correct))}

    # ---- value ------------------------------------------------------------
    value = 100.0
    bench_key = UTILITY_TO_BENCHMARK.get((m.get("utility"), m.get("customer_class", "residential")))
    b = BENCHMARKS.get(bench_key or "")
    if b and m["all_in_rate"] and m["unit"] == b["unit"]:
        lo, hi = b["low"], b["high"]
        r = m["all_in_rate"]
        if r < lo:
            value = 100.0 - min(18.0, (lo - r) / max(lo, 1e-9) * 40)
        elif r <= hi:
            value = 100.0 - 12.0 * (r - lo) / max(hi - lo, 1e-9)
        else:
            over = (r - hi) / max(hi, 1e-9)
            value = 88.0 - min(58.0, over * 110)
    else:
        value = 55.0
    value -= sum(9.0 * SEVERITY_WEIGHT[f["severity"]] for f in findings if f["axis"] == "value")
    scores["value"] = {"score": max(0.0, min(100.0, value))}

    # ---- structure --------------------------------------------------------
    structure = 100.0
    if m["tier_gap"] is not None and m["tier_gap"] > 1.25:
        structure -= min(40.0, (m["tier_gap"] - 1.25) * 70)
    if m["peak_share"] is not None and m["peak_share"] > 0.5:
        structure -= min(28.0, (m["peak_share"] - 0.5) * 70)
    if m.get("structure_kind") == "demand_based":
        structure -= 10
    if m["fixed_share"] is not None and m["fixed_share"] > 0.45:
        structure -= 14
    structure -= sum(9.0 * SEVERITY_WEIGHT[f["severity"]] for f in findings if f["axis"] == "structure")
    scores["structure"] = {"score": max(0.0, min(100.0, structure))}

    # ---- control ----------------------------------------------------------
    control = 100.0
    if m["variable_share"] is not None:
        control = 100.0 - (1.0 - m["variable_share"]) * 55.0
    if m["peak_share"] is not None and m["peak_share"] > 0.5:
        control -= min(22.0, (m["peak_share"] - 0.5) * 60)
    control -= sum(8.0 * SEVERITY_WEIGHT[f["severity"]] for f in findings if f["axis"] == "savings")
    scores["control"] = {"score": max(0.0, min(100.0, control))}

    return scores


def _verdict(score: float) -> Tuple[str, str, str]:
    if score >= 85:
        return "clean_bill", "Clean bill", "Nothing on this bill needs chasing."
    if score >= 70:
        return "mostly_fine", "Mostly fine", "A couple of things are worth a phone call."
    if score >= 55:
        return "worth_a_call", "Worth a call", "There is real money on the table here."
    if score >= 40:
        return "review_needed", "Review needed", "Do not pay this without understanding it."
    return "dispute_candidate", "Dispute candidate", "This bill has a problem you should contest."


def score_bill(m: Dict[str, Any], findings: List[Dict[str, Any]], profile: str) -> Dict[str, Any]:
    axes = _axis_scores(m, findings)
    weights = PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["residential"])

    # Structural caps: you cannot score well by skipping the hard part.
    caps: List[Dict[str, Any]] = []

    def cap(axis: str, limit: float, reason: str) -> None:
        if axis == "overall":
            caps.append({"axis": "overall", "limit": limit, "reason": reason})
        else:
            cur = axes[axis]["score"]
            if cur > limit:
                axes[axis]["score"] = limit
                axes[axis]["capped"] = True
                caps.append({"axis": axis, "limit": limit, "reason": reason})

    if not m["usage"]:
        cap("correctness", 45, "No usage was found, so the rate cannot be verified")
        cap("value", 45, "No usage was found, so no rate can be computed")
    if m["reconciliation_delta"] is not None and abs(m["reconciliation_delta"]) > 1.0:
        cap("correctness", 45, "Line items do not reconcile with the stated total")
    if m["stated_total"] is None:
        cap("correctness", 52, "No stated total on the bill")
    if total_share(m, "unclassified") > 0.25:
        cap("clarity", 50, "More than a quarter of the bill is unrecognised")
    if total_share(m, "unclassified") > 0.45:
        cap("overall", 58, "Most of the bill cannot be identified")
    if m["usage_estimated"]:
        cap("correctness", 78, "Usage is an estimate, not a meter read")

    # A high-severity finding means money is being lost or an error is being
    # paid. No bill carrying one should read as "mostly fine", however tidy
    # the rest of it looks.
    high = sum(1 for f in findings if f["severity"] == "high")
    if high >= 3:
        cap("overall", 50, f"{high} high-severity findings")
    elif high == 2:
        cap("overall", 58, "2 high-severity findings")
    elif high == 1:
        cap("overall", 68, "1 high-severity finding")

    overall = sum(axes[key]["score"] * w for key, w in weights.items())
    overall = round(max(0.0, min(100.0, overall)), 1)
    if any(c["axis"] == "overall" for c in caps):
        limit = min(c["limit"] for c in caps if c["axis"] == "overall")
        overall = round(min(overall, limit), 1)

    verdict, verdict_label, blurb = _verdict(overall)

    axis_list = []
    for key, label, desc in AXES:
        entry = dict(axes[key])
        entry["key"] = key
        entry["label"] = label
        entry["description"] = desc
        entry["weight"] = weights[key]
        entry["score"] = round(entry["score"], 1)
        axis_list.append(entry)

    return {
        "overall": overall,
        "verdict": verdict,
        "verdict_label": verdict_label,
        "verdict_blurb": blurb,
        "axes": axis_list,
        "weights": weights,
        "caps": caps,
        "high_findings": high,
    }


def total_share(m: Dict[str, Any], bucket: str) -> float:
    total = m.get("total") or 0.0
    if not total:
        return 0.0
    return (m.get(bucket) or 0.0) / total
