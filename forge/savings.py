"""Quantified savings scenarios derived from the bill itself.

Every estimate states the assumption it rests on and degrades its confidence
according to how much of that assumption the bill actually supports.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .benchmarks import DEMAND_REDUCTION_SHARE, EV_PATTERNS, SHIFTABLE_PEAK_SHARE


def _scn(
    sid: str,
    title: str,
    detail: str,
    basis: str,
    annual: Optional[float],
    confidence: str,
    steps: List[str],
    effort: str = "low",
) -> Dict[str, Any]:
    return {
        "id": sid,
        "title": title,
        "detail": detail,
        "basis": basis,
        "annual_estimate": round(annual, 2) if annual else None,
        "monthly_estimate": round(annual / 12.0, 2) if annual else None,
        "confidence": confidence,
        "effort": effort,
        "steps": steps,
    }


def build_savings(
    m: Dict[str, Any],
    structure: Dict[str, Any],
    findings: List[Dict[str, Any]],
    text: str,
    customer_class: str = "residential",
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    low = text.lower()
    total = m["total"] or 0.0
    unit = m.get("unit") or "kWh"

    # 1. Late fee avoidance -------------------------------------------------
    for f in findings:
        if f["id"] == "late_fee" and f.get("annual_savings"):
            out.append(_scn(
                "late_fee", "Stop paying the late fee",
                "A late fee repeats every cycle until autopay handles it. "
                + str(f.get("annual_savings")) + " a year is the run rate of one missed payment.",
                "Directly observed on this bill.",
                f["annual_savings"], "high",
                ["Turn on autopay or at least a payment reminder.",
                 "Ask customer service to waive this occurrence as a first-time courtesy.",
                 "Confirm the fee does not recur on the next statement."],
            ))
            break

    # 2. Tier cliff avoidance ------------------------------------------------
    tiers = structure.get("tiers") or []
    ti = m.get("tier_info") or {}
    if tiers and ti.get("kwh_to_cheaper_tier") and ti.get("savings_at_cheaper_tier"):
        shed = ti["kwh_to_cheaper_tier"]
        monthly = ti["savings_at_cheaper_tier"]
        annual = monthly * 12
        floor = ti.get("tier_floor")
        gap_c = (ti.get("tier_rate_gap") or 0) * 100
        detail = (
            "You are " + format(shed, ".0f") + " " + unit + " into your most expensive tier, which "
            "bills " + format((ti.get("current_rate") or 0) * 100, ".2f") + "c per " + unit + ". Shedding "
            "that usage puts you back under the " + format(floor, ".0f") + " " + unit + " threshold and "
            "removes those units at the top rate entirely, worth about $" + format(monthly, ".2f")
            + " a month. The rate cliff itself is worth " + format(gap_c, ".2f") + "c per " + unit
            + ", so ask the utility whether the threshold can be raised or the tier softened."
        )
        out.append(_scn(
            "tier_cliff", "Fall back one tier",
            detail,
            "Tier boundaries, rates and usage read directly off the tiered lines of this bill.",
            annual, "medium",
            ["Measure your usage over a week to find the specific loads that push you past the threshold.",
             "Shift or automate one high-draw activity (EV charge, dryer run, pool pump, HVAC) to before the threshold.",
             "Re-check the next bill: your marginal rate should drop back to the lower tier."],
            effort="medium",
        ))
    elif tiers and m.get("tier_gap") and m["tier_gap"] > 1.2 and m.get("usage"):
        rates = [(t.get("quantity") or 0, t.get("rate") or 0) for t in tiers]
        rates = [r for r in rates if r[0] and r[1]]
        if len(rates) >= 2:
            rates.sort()
            base_qty, base_rate = rates[0]
            top_qty, top_rate = rates[-1]
            marginal_kwh = max(0.0, (m["usage"] or 0) - base_qty)
            delta = top_rate - base_rate
            if marginal_kwh > 0 and delta > 0:
                annual = marginal_kwh * delta * 12
                out.append(_scn(
                    "tier_cliff", "Stay under the tier threshold",
                    "You are about " + format(marginal_kwh, ".0f") + " " + unit + " into the top tier, "
                    "where each unit costs " + format(delta * 100, ".2f") + "c more than the tier below. "
                    "Shedding that usage drops you back to the cheaper rate, so the saving is the whole "
                    "rate difference, not the value of the energy you stop using.",
                    "Quantities and rates read directly off the tiered lines of this bill.",
                    annual, "medium",
                    ["Measure your usage over a week to find when you cross the threshold.",
                     "Shift or automate one high-draw activity (EV charge, dryer run, pool pump) to before the threshold.",
                     "Re-check the next bill: the marginal rate should fall back to the lower tier."],
                    effort="medium",
                ))

    # 3. Time-of-use shifting -----------------------------------------------
    tou = structure.get("tou") or {}
    if tou.get("on_peak_rate") and tou.get("off_peak_rate") and tou.get("on_peak_kwh"):
        gap = tou["on_peak_rate"] - tou["off_peak_rate"]
        if gap > 0:
            shiftable = tou["on_peak_kwh"] * SHIFTABLE_PEAK_SHARE
            annual = shiftable * gap * 12
            out.append(_scn(
                "tou_shift", "Move flexible loads off peak",
                format(tou["on_peak_kwh"], ".0f") + " " + unit + " are billed at the on-peak rate. If you "
                "can move " + format(SHIFTABLE_PEAK_SHARE * 100, ".0f") + "% of that to off-peak hours - "
                "laundry, dishwashing, EV charging, water heating - each shifted unit saves "
                + format(gap * 100, ".2f") + "c.",
                "On-peak and off-peak rates and quantities read from this bill.",
                annual, "medium",
                ["Pick two loads you control the timing of and set timers for off-peak hours.",
                 "Schedule EV charging to start when the off-peak window opens.",
                 "Check whether the utility offers a free or cheap automation programme."],
                effort="low",
            ))

    # 4. Demand charge reduction ---------------------------------------------
    if structure.get("has_demand_charge") and m.get("demand"):
        annual = m["demand"] * DEMAND_REDUCTION_SHARE * 12
        out.append(_scn(
            "demand_reduce", "Lower your billed peak demand",
            "Demand charges of $" + format(m["demand"], ".2f") + " are billed on your single highest peak "
            "interval, not on your total usage. Spreading large loads so they never stack can shave "
            + format(DEMAND_REDUCTION_SHARE * 100, ".0f") + "% off that peak.",
            "Demand charge total read directly from this bill.",
            annual, "medium",
            ["List every load above 5 kW and stagger their start times so they never overlap.",
             "Avoid restarting a large motor or HVAC compressor inside the same peak window as other heavy loads.",
             "Ask the utility for your billed-demand interval data and what the peak was."],
            effort="medium",
        ))

    # 5. EV charging off-peak -------------------------------------------------
    if any(re.search(p, low) for p in EV_PATTERNS):
        if tou.get("off_peak_rate") is not None and tou.get("on_peak_rate"):
            gap = tou["on_peak_rate"] - tou["off_peak_rate"]
            ev_kwh = 1000.0
            annual = ev_kwh * gap * 12
            out.append(_scn(
                "ev_shift", "Schedule EV charging into the off-peak window",
                "At roughly 1,000 " + unit + " a month of charging, every unit billed at the on-peak "
                "rate instead of off-peak costs " + format(gap * 100, ".2f") + "c extra.",
                "EV detected in the bill text; charging volume is a stated assumption, not a measurement.",
                annual, "low",
                ["Check whether your plan has an EV or overnight period and schedule charging into it.",
                 "Set the charger's start time to the off-peak window open.",
                 "Verify on the next bill that the charging kWh landed in the cheap period."],
                effort="low",
            ))

    # 6. Usage reduction on the commodity portion ---------------------------
    if m.get("commodity_rate") and m.get("usage") and m.get("commodity_rate") > 0:
        pct = 0.05
        annual = m["usage"] * m["commodity_rate"] * pct * 12
        out.append(_scn(
            "usage_cut_5", "Cut consumption by 5%",
            "A 5% reduction in usage saves " + format(m["commodity_rate"] * 100, ".2f") + "c on the "
            "commodity portion each cycle. This only touches the energy cost - fixed charges and "
            "demand charges do not move.",
            "Commodity rate of " + format(m["commodity_rate"] * 100, ".2f") + "c per unit and usage of "
            + format(m["usage"], ".0f") + " " + unit + " read from this bill.",
            annual, "high",
            ["Start with the biggest single load - HVAC, water heating, or a second fridge.",
             "Set the thermostat 2 degrees off for 8 hours a night.",
             "Measure next month to confirm the change stuck before scaling it up."],
            effort="medium",
        ))

    # 7. Fixed-charge reduction ---------------------------------------------
    if m.get("fixed_share") and m["fixed_share"] > 0.35 and m.get("base") > 5:
        out.append(_scn(
            "fixed_reduction", "Renegotiate the fixed part of your rate",
            "$" + format(m["base"], ".2f") + " of this bill is base and facility charges that do not "
            "depend on how much you use. Efficiency work cannot touch them; only a rate change, a "
            "smaller service size, or self-supply can.",
            "Base-charge total read directly from this bill.",
            None, "low",
            ["Ask what the fixed portion of your rate is and whether a lower-demand or tiered "
             "service size would reduce it.",
             "Get a written comparison of at least three rate plans for your exact usage profile."],
            effort="medium",
        ))

    # 8. True-up avoidance ----------------------------------------------------
    if any(f["id"] == "trueup" for f in findings):
        out.append(_scn(
            "trueup_avoid", "Move off estimated billing",
            "True-ups mean you are being billed on an estimate and settling the difference later. "
            "Budget billing fixes the estimate at your historical average instead, so you stop "
            "getting large seasonal reconciliation charges.",
            "True-up line observed on this bill.",
            None, "low",
            ["Ask whether budget billing or a level-payment plan is available.",
             "Give the utility your actual meter reads so the estimate stays close to reality."],
            effort="low",
        ))

    # 9. Unclassified charge investigation ----------------------------------
    if m.get("unclassified") and total and m["unclassified"] / total > 0.08:
        out.append(_scn(
            "clarify_charges", "Get every charge named",
            "$" + format(m["unclassified"], ".2f") + " of this bill is on lines that could not be "
            "identified. Some of it may be optional, subsidised, or something you can change; none "
            "of it can be evaluated while it is anonymous.",
            "Unclassified total computed from the parsed line items.",
            None, "low",
            ["Ask customer service for an itemised tariff breakdown of every line on the bill.",
             "Ask which charges are pass-through, which are discretionary, and which are regulated."],
            effort="low",
        ))

    # 10. Rider review --------------------------------------------------------
    if m.get("riders") and total and m["riders"] / total > 0.06:
        out.append(_scn(
            "rider_review", "Audit the rider stack",
            "$" + format(m["riders"], ".2f") + " sits on policy riders. These are usually pass-through "
            "costs, but they move independently of your rate case and they accumulate.",
            "Rider total read directly from this bill.",
            None, "low",
            ["Ask for the dollar impact of each rider individually.",
             "Check your state PUC docket for pending rider changes before you plan capital work "
             "like solar or an EV."],
            effort="low",
        ))

    out.sort(key=lambda s: (s["annual_estimate"] is None, -(s["annual_estimate"] or 0)))
    return out
