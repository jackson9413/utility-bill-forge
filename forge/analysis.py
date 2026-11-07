"""Analysis engine: cost decomposition, findings, scoring, and savings scenarios."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .benchmarks import (
    BENCHMARKS,
    DEMAND_REDUCTION_SHARE,
    EV_PATTERNS,
    SHIFTABLE_PEAK_SHARE,
    UTILITY_TO_BENCHMARK,
)
from .categorize import BUCKET_LABELS, FIXED_BUCKETS, classify_bill, detect_structure
from .parser import ParsedBill, parse_bill

# ---------------------------------------------------------------------------
# Finding helpers
# ---------------------------------------------------------------------------


def _finding(
    fid: str,
    severity: str,
    title: str,
    evidence: str,
    why: str,
    fix: str,
    axis: str,
    savings: Optional[float] = None,
    confidence: str = "high",
) -> Dict[str, Any]:
    return {
        "id": fid,
        "severity": severity,
        "title": title,
        "evidence": evidence.strip()[:220],
        "why": why,
        "fix": fix,
        "axis": axis,
        "annual_savings": round(savings, 2) if savings else None,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------


def _primary_usage(bill: ParsedBill) -> Tuple[Optional[float], Optional[str]]:
    for unit in ("kWh", "therm", "MMBtu", "ccf", "gal", "m3", "cuft"):
        if bill.usage.get(unit):
            return bill.usage[unit], unit
    return None, None


def analyze_tiers(tiers: List[Dict[str, Any]], usage: Optional[float]) -> Dict[str, Any]:
    """Work out where this customer sits in the tier ladder.

    Returns the tier that contains the last unit consumed, how many units they
    must shed to fall back into a cheaper tier, and what that saves.
    """
    info: Dict[str, Any] = {
        "ladder": [],
        "current_tier": None,
        "current_rate": None,
        "kwh_into_tier": None,
        "tier_floor": None,
        "kwh_to_next_tier": None,
        "next_tier_rate": None,
        "kwh_to_cheaper_tier": None,
        "savings_at_cheaper_tier": None,
        "next_tier_kwh_away": None,
    }
    if not tiers:
        return info

    ladder = []
    for idx, t in enumerate(tiers):
        rate = t.get("rate")
        ladder.append({
            "index": idx,
            "label": t.get("label"),
            "from_kwh": t.get("from_kwh"),
            "to_kwh": t.get("to_kwh"),
            "rate": rate,
            "amount": t.get("amount"),
            "quantity": t.get("quantity"),
        })
    info["ladder"] = ladder

    if usage is None:
        # No usage: fall back to the top of the ladder as the marginal rate.
        rates = [t.get("rate") for t in ladder if t.get("rate") is not None]
        if rates:
            info["current_rate"] = max(rates)
        return info

    # Locate the tier containing the final unit consumed.
    current = None
    for t in ladder:
        lo = t.get("from_kwh")
        hi = t.get("to_kwh")
        if lo is None and hi is None:
            continue
        if lo is not None and usage < lo:
            continue
        if hi is not None and usage > hi:
            continue
        current = t
        break

    if current is None:
        current = ladder[-1]

    info["current_tier"] = current["index"]
    info["current_rate"] = current.get("rate")
    info["tier_floor"] = current.get("from_kwh")
    if current.get("from_kwh") is not None:
        info["kwh_into_tier"] = round(usage - current["from_kwh"], 2)

    # The tier above (if any): how far away, and what it costs.
    idx = ladder.index(current)
    if idx + 1 < len(ladder):
        nxt = ladder[idx + 1]
        info["next_tier_rate"] = nxt.get("rate")
        if nxt.get("from_kwh") is not None:
            info["next_tier_kwh_away"] = round(max(0.0, nxt["from_kwh"] - usage), 2)

    # Falling back one tier: shed everything above this tier's floor.
    if current.get("from_kwh") is not None and usage > current["from_kwh"]:
        shed = usage - current["from_kwh"]
        below = ladder[idx - 1] if idx > 0 else None
        if below is not None and below.get("rate") is not None and current.get("rate") is not None:
            # Shedding the usage above the floor removes those units at the
            # top rate entirely - the saving is the full marginal rate.
            saving = shed * current["rate"]
            info["kwh_to_cheaper_tier"] = round(shed, 2)
            info["savings_at_cheaper_tier"] = round(saving, 2)
            info["tier_rate_gap"] = round(current["rate"] - below["rate"], 6)
        else:
            # No cheaper tier below; shedding just avoids the top rate.
            if current.get("rate") is not None:
                info["kwh_to_cheaper_tier"] = round(shed, 2)
                info["savings_at_cheaper_tier"] = round(shed * current["rate"], 2)
                info["tier_rate_gap"] = 0.0

    return info


def compute_metrics(bill: ParsedBill, structure: Dict[str, Any]) -> Dict[str, Any]:
    buckets = classify_bill(bill)
    usage, unit = _primary_usage(bill)

    total = bill.total_stated if bill.total_stated is not None else bill.sum_of_charges
    supply = buckets.get("energy", 0.0)
    delivery = buckets.get("delivery", 0.0)
    fuel = buckets.get("fuel", 0.0)
    demand = buckets.get("demand", 0.0)
    taxes = buckets.get("tax", 0.0)
    fees = buckets.get("fee", 0.0)
    riders = buckets.get("rider", 0.0)
    base = buckets.get("base", 0.0)
    credits = buckets.get("credit", 0.0)
    deposits = buckets.get("deposit", 0.0)
    adjustments = buckets.get("adjustment", 0.0)
    unclassified = buckets.get("unclassified", 0.0)

    variable = supply + delivery + fuel + riders + taxes
    fixed = base + demand + deposits
    commodity = supply + fuel

    # One-off items (deposits, true-ups, late fees) are not part of a
    # per-unit rate, so they are excluded from the recurring total.
    one_time = round(
        deposits
        + sum(c.amount for c in bill.items
              if c.role == "charge" and c.category == "fee"
              and re.search(r"late|penalt", c.label.lower()))
        + sum(c.amount for c in bill.items
              if c.role == "charge" and c.category == "adjustment"),
        2,
    )
    recurring_total = round(max(0.0, total - one_time), 2)

    all_in_rate = (recurring_total / usage) if (usage and recurring_total) else None
    commodity_rate = (commodity / usage) if (usage and commodity) else None
    delivery_rate = (delivery / usage) if (usage and delivery) else None
    tax_rate = (taxes / usage) if (usage and taxes) else None

    fixed_share = (fixed / total) if total else None
    variable_share = (variable / total) if total else None
    commodity_share = (commodity / total) if total else None
    tax_share = (taxes / total) if total else None
    fee_share = (fees / total) if total else None
    rider_share = (riders / total) if total else None

    # Marginal vs average: on a tiered bill the marginal rate is the tier the
    # customer's *last* unit falls in, not the highest rate on the bill.
    marginal_rate = None
    tier_gap = None
    tiers = structure.get("tiers") or []
    tier_info = analyze_tiers(tiers, usage)
    if tier_info.get("current_rate") is not None:
        marginal_rate = tier_info["current_rate"]
        if commodity_rate and commodity_rate > 0:
            tier_gap = marginal_rate / commodity_rate
    elif tiers:
        rates = [t["rate"] for t in tiers if t.get("rate") is not None]
        if rates:
            marginal_rate = max(rates)
    tou = structure.get("tou") or {}
    if marginal_rate is None and tou.get("on_peak_rate") is not None:
        marginal_rate = tou["on_peak_rate"]
    if marginal_rate is None and commodity_rate:
        # A flat rate: every unit costs the same, so the marginal rate is the
        # commodity rate.
        marginal_rate = commodity_rate

    peak_kwh = tou.get("on_peak_kwh") or 0.0
    offpeak_kwh = tou.get("off_peak_kwh") or 0.0
    tou_total = peak_kwh + offpeak_kwh
    peak_share = (peak_kwh / tou_total) if tou_total else None

    # Reconciliation: do the line items add up to the stated total?
    delta = None
    if bill.total_stated is not None:
        delta = round(bill.total_stated - bill.sum_of_charges, 2)

    return {
        "total": round(total, 2),
        "recurring_total": recurring_total,
        "one_time": one_time,
        "stated_total": bill.total_stated,
        "line_item_sum": bill.sum_of_charges,
        "reconciliation_delta": delta,
        "usage": usage,
        "unit": unit,
        "usage_estimated": bill.usage_estimated,
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "bucket_labels": BUCKET_LABELS,
        "commodity": round(commodity, 2),
        "delivery": round(delivery, 2),
        "demand": round(demand, 2),
        "taxes": round(taxes, 2),
        "fees": round(fees, 2),
        "riders": round(riders, 2),
        "base": round(base, 2),
        "credits": round(credits, 2),
        "deposits": round(deposits, 2),
        "adjustments": round(adjustments, 2),
        "unclassified": round(unclassified, 2),
        "variable": round(variable, 2),
        "fixed": round(fixed, 2),
        "all_in_rate": all_in_rate,
        "commodity_rate": commodity_rate,
        "delivery_rate": delivery_rate,
        "tax_rate": tax_rate,
        "marginal_rate": marginal_rate,
        "tier_gap": tier_gap,
        "tier_info": tier_info,
        "fixed_share": fixed_share,
        "variable_share": variable_share,
        "commodity_share": commodity_share,
        "tax_share": tax_share,
        "fee_share": fee_share,
        "rider_share": rider_share,
        "peak_share": peak_share,
        "period_days": bill.period_days,
        "period_start": bill.period_start,
        "period_end": bill.period_end,
    }


# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------

RULED_OUT_RE = re.compile(
    r"\b(estimated|estimate|prior|previous|last\s+month|month\s+ago|arrears?)\b", re.IGNORECASE
)


def run_rules(bill: ParsedBill, m: Dict[str, Any], structure: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    total = m["total"] or 0.0
    items = [c for c in bill.items if c.role == "charge"]
    low = text.lower()

    # --- reconciliation -----------------------------------------------------
    if m["reconciliation_delta"] is not None and abs(m["reconciliation_delta"]) > 1.0:
        out.append(_finding(
            "recon_mismatch", "high",
            "Line items do not add up to the stated total",
            f"Stated total {m['stated_total']:.2f} vs sum of line items {m['line_item_sum']:.2f} "
            f"(difference {m['reconciliation_delta']:+.2f})",
            "A bill that does not reconcile means either a line was missed in the paste, a charge is "
            "mislabeled, or the utility made an error. Until it reconciles you cannot trust any rate "
            "computed from it.",
            "Re-check the paste for dropped lines, then ask customer service for an itemized PDF of "
            "this bill and confirm which line is missing.",
            "correctness",
        ))

    # --- unclassified money --------------------------------------------------
    if m["unclassified"] > 0.5:
        share = m["unclassified"] / total if total else 0
        if share > 0.08:
            out.append(_finding(
                "unclassified_charges", "medium" if share < 0.25 else "high",
                f"{share*100:.0f}% of the bill is unrecognised",
                "; ".join(c.raw for c in items if c.category == "unclassified")[:200],
                "Unlabelled charges cannot be evaluated, challenged, or optimised. They are usually "
                "a renamed rider, a fuel pass-through, or a mis-scraped line.",
                "Ask the utility to identify each charge by name and by tariff provision.",
                "clarity",
            ))

    # --- late fee -----------------------------------------------------------
    for c in items:
        if c.category == "fee" and re.search(r"late|penalt", c.label.lower()):
            annual = abs(c.amount) * 12
            out.append(_finding(
                "late_fee", "high" if abs(c.amount) > 25 else "medium",
                "Late payment fee on the bill",
                c.raw,
                "A late fee is pure loss and usually also blocks a lower rate or a payment-plan "
                "option you would otherwise qualify for.",
                "Switch to autopay or a due-date reminder, and ask whether the fee can be waived "
                "as a first occurrence.",
                "correctness",
                savings=annual,
            ))
            break

    # --- estimated usage ----------------------------------------------------
    if m["usage_estimated"]:
        out.append(_finding(
            "estimated_read", "medium",
            "Usage was estimated, not read from the meter",
            "Billing period flagged as estimated",
            "An estimate can be materially wrong in either direction, and in most jurisdictions you "
            "have a right to a true-up once an actual meter read arrives.",
            "Request an actual meter read for this period, and keep the bill until the next cycle "
            "confirms the real number.",
            "correctness",
        ))

    # --- true-up / adjustment ------------------------------------------------
    if m["adjustments"] > 0.5:
        out.append(_finding(
            "trueup", "medium",
            "A true-up or bill adjustment is included",
            "; ".join(c.raw for c in items if c.category == "adjustment")[:200],
            "True-ups reconcile an earlier estimate against actual use. They are legitimate but they "
            "can hide a recurring pattern - if your bill is estimated every month, you are paying "
            "interest on an imaginary number.",
            "Ask for the original estimate and the actual read that caused the adjustment, and ask "
            "whether a fixed-budget billing plan is available instead.",
            "correctness",
        ))

    # --- deposit ------------------------------------------------------------
    if m["deposits"] > 0:
        out.append(_finding(
            "deposit", "low",
            "A deposit is on the account",
            "; ".join(c.raw for c in items if c.category == "deposit")[:160],
            "Deposits are refundable, but they tie up cash and they inflate the amount due on the "
            "bill that carries them.",
            "Confirm the deposit is credited to your final bill and ask for the refund timeline if "
            "you are moving or closing the account.",
            "clarity",
        ))

    # --- fixed cost dominance ------------------------------------------------
    if m["fixed_share"] is not None and m["fixed_share"] > 0.45 and total > 20:
        out.append(_finding(
            "fixed_dominant", "medium",
            "Most of this bill is fixed charges, not usage",
            f"Fixed {m['fixed']:.2f} of {total:.2f} ({m['fixed_share']*100:.0f}%)",
            "When fixed charges dominate, cutting kWh barely moves the bill - you are working "
            "against a floor. Efficiency work has to target the fixed portion, which means plan "
            "changes rather than behaviour changes.",
            "Compare your fixed charges against a different rate plan or a smaller meter/service "
            "size; shifting a few kWh will not fix this bill.",
            "structure",
        ))

    # --- tier cliff ---------------------------------------------------------
    ti = m.get("tier_info") or {}
    if ti.get("kwh_to_cheaper_tier") and ti.get("current_rate"):
        out.append(_finding(
            "tier_cliff", "high",
            "You are paying the top tier rate on part of your usage",
            f"Usage of {m['usage']:.0f} {m['unit']} sits "
            f"{(ti.get('kwh_into_tier') or 0):.0f} {m['unit']} into a tier that starts at "
            f"{(ti.get('tier_floor') or 0):.0f} {m['unit']} and bills "
            f"{ti['current_rate']*100:.2f}c",
            "On a tiered rate the last kWh you use can cost several times what the average kWh "
            "costs. Shedding the kWh above the tier floor puts you back on the cheaper rate for "
            "every one of them, so the saving is the rate difference, not just the value of the "
            "energy you stop using.",
            f"Target the {ti['kwh_to_cheaper_tier']:.0f} {m['unit']} that push you over the "
            f"{(ti.get('tier_floor') or 0):.0f} {m['unit']} threshold - one shifted load cycle is "
            f"usually enough.",
            "structure",
            savings=(ti.get("savings_at_cheaper_tier") or 0) * 12,
        ))
    elif m["tier_gap"] is not None and m["tier_gap"] > 1.35:
        out.append(_finding(
            "tier_cliff", "high",
            "Your marginal rate is far above your average rate",
            f"Marginal {m['marginal_rate']*100:.2f}c vs commodity average "
            f"{(m['commodity_rate'] or 0)*100:.2f}c per {m['unit']}",
            "On a tiered rate the last kWh you use can cost several times what the average kWh "
            "costs. If your usage sits just above a tier boundary, a small cut in usage can drop "
            "you back to the cheaper tier and save far more than the cut itself is worth.",
            "Compute the exact kWh you need to shed to fall back under the tier threshold, and "
            "target that before trying to reduce overall consumption.",
            "structure",
        ))

    # --- TOU exposure --------------------------------------------------------
    if m["peak_share"] is not None and m["peak_share"] > 0.50:
        out.append(_finding(
            "peak_exposure", "medium",
            "Most of your usage lands in peak hours",
            f"{m['peak_share']*100:.0f}% of metered usage is on-peak",
            "Time-of-use rates punish you for using power when the grid is busiest. Households that "
            "cannot shift laundry, dishwashing and EV charging end up paying a premium rate for "
            "usage they could have moved.",
            "Shift the flexible loads (washer, dishwasher, EV charging, water heater) into "
            "off-peak windows with a smart plug, a timer, or the utility's own scheduling app.",
            "structure",
        ))

    # --- demand charge ------------------------------------------------------
    if structure.get("has_demand_charge") and m["demand"] > 0:
        share = m["demand"] / total if total else 0
        if share > 0.25:
            out.append(_finding(
                "demand_heavy", "high" if share > 0.40 else "medium",
                "Demand charges are a large slice of this bill",
                f"Demand {m['demand']:.2f} of {total:.2f} ({share*100:.0f}%)",
                "Demand charges are billed on your highest peak interval, not on total usage. "
                "Cutting steady-state consumption does nothing; only shifting or smoothing the "
                "single worst moment helps.",
                "Stagger large loads so they do not start at once, avoid restarting heavy equipment "
                "in a cycle, and ask whether a smaller contracted demand is available.",
                "structure",
            ))

    # --- rate benchmark -----------------------------------------------------
    bench_key = UTILITY_TO_BENCHMARK.get((bill.utility, "commercial" if m.get("customer_class") == "commercial" else "residential"))
    if bench_key and m["all_in_rate"] and m["unit"] == BENCHMARKS[bench_key]["unit"]:
        b = BENCHMARKS[bench_key]
        if m["all_in_rate"] > b["high"]:
            sev = "high" if m["all_in_rate"] > b["high"] * 1.35 else "medium"
            out.append(_finding(
                "rate_above_band", sev,
                "Your all-in rate is above the typical band",
                f"{m['all_in_rate']*100:.2f}c per {m['unit']} vs typical {b['low']*100:.1f}-{b['high']*100:.1f}c",
                f"{b['note']} Being above the band is not proof of overbilling, but it means a plan "
                "comparison is worth ten minutes of your time.",
                "Request a rate comparison from your utility and, where the market is deregulated, "
                "get a competitive supplier quote for the same usage profile.",
                "value",
            ))
        elif m["all_in_rate"] < b["low"] * 0.6:
            out.append(_finding(
                "rate_below_band", "low",
                "Your rate looks unusually low - verify the bill is complete",
                f"{m['all_in_rate']*100:.2f}c per {m['unit']} vs typical {b['low']*100:.1f}-{b['high']*100:.1f}c",
                "A rate far below the band usually means the paste is missing charges rather than "
                "that you found a bargain.",
                "Compare against a full PDF statement to make sure no line items are missing.",
                "value",
                confidence="medium",
            ))

    # --- rider stack ---------------------------------------------------------
    if m["rider_share"] is not None and m["rider_share"] > 0.10 and total > 30:
        out.append(_finding(
            "rider_stack", "medium",
            "Policy riders are a meaningful chunk of the bill",
            f"Riders {m['riders']:.2f} of {total:.2f} ({m['rider_share']*100:.0f}%)",
            "Renewable, reliability and environmental riders are usually pass-through costs you "
            "cannot avoid, but they compound: each one is a separate line the utility can adjust "
            "without a rate-case hearing.",
            "Ask for the dollar impact of each rider and check your state PUC's public rate-case "
            "docket for pending changes to them.",
            "value",
        ))

    # --- tax check -----------------------------------------------------------
    if m["taxes"] > 0 and m["tax_rate"] is not None:
        implied_base = m["taxes"] / 0.06 if m["tax_rate"] < 0.2 else None
        if implied_base and m["commodity"] > 0 and implied_base < m["commodity"] * 0.4:
            out.append(_finding(
                "tax_base_narrow", "low",
                "Tax is applied to a narrower base than the commodity charge",
                f"Tax {m['taxes']:.2f} implies a taxable base near {implied_base:.2f} vs commodity "
                f"{m['commodity']:.2f}",
                "Many utilities tax only the commodity portion, not delivery. If your bill shows "
                "tax on the full amount, that is worth understanding - but it is also common and "
                "usually not contestable.",
                "Confirm your jurisdiction's taxable basis with the utility's tax unit.",
                "correctness",
                confidence="medium",
            ))

    # --- missing commodity / delivery split ---------------------------------
    if bill.utility == "electric" and m["commodity"] <= 0.5 and m["total"] > 15:
        out.append(_finding(
            "no_commodity_split", "medium",
            "No separate energy-supply charge was found",
            "Bill total {:.2f} with no line item classified as commodity".format(m["total"]),
            "Bundled bills hide whether you are paying a fair commodity rate, and they make a "
            "supplier comparison impossible.",
            "Ask for the commodity and delivery components of your rate, even if the bill combines "
            "them.",
            "clarity",
        ))
    if bill.utility == "electric" and m["delivery"] <= 0.5 and m["total"] > 15 and m["commodity"] > 0:
        out.append(_finding(
            "no_delivery_split", "low",
            "No separate delivery or distribution charge was found",
            "Bill total {:.2f} with no line item classified as delivery".format(m["total"]),
            "Delivery is the part of the bill that goes to the wires and is usually the part you "
            "cannot shop. Knowing the split tells you whether shopping a supplier is worth it.",
            "Ask what portion of your rate is commodity versus delivery.",
            "clarity",
            confidence="medium",
        ))

    # --- duplicate-looking charges -------------------------------------------
    seen: Dict[str, List] = {}
    for c in items:
        key = re.sub(r"\W+", " ", c.label.lower()).strip()
        if key:
            seen.setdefault(key, []).append(c)
    for key, group in seen.items():
        if len(group) > 1 and all(abs(g.amount - group[0].amount) < 0.01 for g in group):
            out.append(_finding(
                "duplicate_charge", "medium",
                "The same charge appears more than once",
                f"{group[0].label} x{len(group)} at {group[0].amount:.2f} each",
                "Identical repeated lines are sometimes a legitimate multi-meter bill, but they are "
                "also the classic shape of a double charge.",
                "Confirm whether this covers a second meter or unit before paying it, and ask for a "
                "breakdown if there is only one service point.",
                "correctness",
                confidence="medium",
            ))
            break

    # --- EV charging --------------------------------------------------------
    if any(re.search(p, low) for p in EV_PATTERNS):
        out.append(_finding(
            "ev_present", "medium",
            "EV charging appears on this account",
            "EV / charging language detected in the bill text",
            "EV charging is one of the largest and most shiftable loads on a home bill. On a "
            "time-of-use rate, charging off-peak is usually the single biggest lever available.",
            "Confirm your rate has a separate EV or overnight period and schedule charging to start "
            "after the off-peak window opens.",
            "savings",
        ))

    # --- credit that does not net out ----------------------------------------
    NAMED_CREDIT_RE = re.compile(
        r"\b(solar|net\s+metering|export|rebate|deposit|assistance|low\s+income|"
        r"interruptible|off-?peak|demand|energy\s+credit|generation|true-?up)\b",
        re.IGNORECASE,
    )
    credit_lines = [c for c in items if c.category == "credit"]
    anonymous_credits = [c for c in credit_lines if not NAMED_CREDIT_RE.search(c.label)]
    if anonymous_credits and abs(m["credits"]) > 0.5:
        out.append(_finding(
            "credit_unexplained", "medium",
            "A credit is on the bill but its origin is unclear",
            "; ".join(c.raw for c in anonymous_credits)[:200],
            "Solar export credits, rebates and good-standing credits have very different rules - "
            "some expire, some are recalculated annually, and some are worth less than retail. "
            "A credit you cannot name is a credit you cannot plan around.",
            "Ask what each credit is worth and whether it expires or is re-billed at true-up.",
            "value",
            confidence="medium",
        ))

    # --- period sanity -------------------------------------------------------
    if m["period_days"] is not None and (m["period_days"] < 20 or m["period_days"] > 45):
        out.append(_finding(
            "odd_period", "medium",
            "This bill covers an unusual number of days",
            f"{m['period_days']} days of service",
            "A short or long billing period makes every per-unit rate and every comparison "
            "misleading, because the usage is not a month of usage.",
            "Normalise before comparing, and ask why the period is not a normal cycle.",
            "correctness",
        ))

    return out
