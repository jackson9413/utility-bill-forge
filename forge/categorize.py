"""Classify parsed charge lines into billing buckets and detect rate structure."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .parser import Charge, ParsedBill

# Bucket order matters: the first matching keyword group wins, so more specific
# patterns are listed before broader ones.
BUCKETS: List[Tuple[str, str]] = [
    ("demand", r"\bdemand\b|\bkw\s*(charge|billing)|maximum\s+demand|\breactive\b|\bkva\b"
               r"|\bcapacity\s+charge\b|\bpower\s+factor\b"),
    ("deposit", r"\bdeposit\b|\bsecurity\s+deposit\b|\bconnection\s+deposit\b|\bapply\s+deposit\b"),
    ("fee", r"\blate\s+(payment\s+)?(fee|charge|penalty)\b|\b\w+\s+fee\b|\breconnect\b|\bdisconnect\b|\badministration\b|\badmin\s+fee\b"
           r"|\bservice\s+fee\b|\bmeter\s+(fee|charge)\b|\bdisconnection\b|\bcredit\s+card\s+fee\b"
           r"|\bprocessing\s+fee\b|\breturned\s+payment\b|\bstop\s+payment\b|\bnewsletter\b"
           r"|\bpaperless\b|\bopt\s*out\b|\bexpedited\b|\bmedical\s+certificate\b|\btest\b"),
    ("tax", r"\b(sales\s+tax|state\s+tax|city\s+tax|county\s+tax|local\s+tax|excise\s+tax|"
            r"utility\s+tax|public\s+utility\s+commission|\bpuc\b|tax\b|gross\s+receipts?\s+tax"
            r"|\bfranchise\s+tax\b|\btransit\s+tax\b|\bproperty\s+tax\b)"),
    ("rider", r"\brenewable\s+energy\b|\brenewable\s+portfolio\b|\brps\b|\bcarbon\b|\bemission\b"
              r"|\breliability\b|\bgreen\s+power\b|\bgreen\s+premium\b|\bclean\s+energy\b"
              r"|\bsustainability\b|\benvironment\b|\brider\b|\bbiodiversity\b|\bstorm\s+recovery\b"
              r"|\benergy\s+assistance\b|\blow\s+income\b|\benergy\s+credit\b|\bsolar\s+credit\b"
              r"|\benergy\s+benefit\b"),
    ("fuel", r"\bfuel\s+(cost|charge|adjustment)\b|\bgas\s+(cost|supply|commodity)\b|\bcommodity\s+charge\b"
            r"|\bgas\s+cost\s+adjustment\b|\bbalancing\s+charge\b"),
    ("delivery", r"\bdelivery\b|\bdistribution\b|\btransmission\b|\btransportation\b|\bwires?\b|\bnetwork\s+charge\b"
                r"|\bgrid\s+charge\b|\bdistribution\s+charge\b|\bdelivery\s+service\b|\bline\s+charge\b"
                r"|\bprimary\s+service\b|\bsecondary\s+service\b|\bstandby\s+service\b"),
    ("base", r"\bcustomer\s+charge\b|\bbasic\s+service\b|\bmonthly\s+charge\b|\bfixed\s+charge\b"
            r"|\baccount\s+charge\b|\bconnection\s+charge\b|\bmeter\s+charge\b|\baccess\s+charge\b"
            r"|\bcustomer\s+facility\b|\bstanding\s+charge\b|\bminimum\s+(bill|charge)\b"
            r"|\bresidential\b.*\bservice\b|\bgeneral\s+service\b|\bbasic\s+rate\b"
            r"|\bhandling\b|\bcontract\s+demand\b|\bsubscriber\s+charge\b"),
    ("adjustment", r"\btrue-?up\b|\bproration\b|\bbilling\s+correction\b|\brebill\b"
                   r"|\bprevious\s+period\b|\brevision\b|\bsupplemental\b"
                   r"|\bprior\s+month\b|\btrue\s*up\b"),
    ("credit", r"\bcredit\b|\bnet\s+metering\b|\bexport\s+credit\b|\bsolar\s+generation\b"
              r"|\brebate\b|\bcredit\s+applied\b|\brollover\b|\bbank\b|\bassistance\b"),
    ("energy", r"\benergy\s+(charge|cost|supply|service|rate)\b|\bcommodity\b|\bgeneration\b|\bsupply\s+charge\b"
              r"|\bkwh\s+charge\b|\bpower\s+charge\b|\bbasic\s+energy\b|\bwholesale\b|\bmarket\s+rate\b"
              r"|\bstandard\s+service\s+charge\b|\bbilling\s+charge\b|\bgas\s+service\s+charge\b"
              r"|\belectric\s+service\s+charge\b|\bblocks?\b|\btier\b"
              r"|\boff-?peak\b|\bon-?peak\b|\bpeak\b|\bshoulder\b|\bbase\s+rate\b|\busage\b"),
]

BUCKET_LABELS = {
    "energy": "Energy / commodity",
    "delivery": "Delivery / distribution",
    "fuel": "Fuel / commodity adjustment",
    "demand": "Demand charge",
    "tax": "Taxes",
    "fee": "Fees & penalties",
    "rider": "Policy riders",
    "base": "Fixed base charges",
    "credit": "Credits & offsets",
    "deposit": "Deposits",
    "adjustment": "Adjustments",
    "unclassified": "Unclassified",
}

FIXED_BUCKETS = {"base", "demand", "deposit"}


# Explicitly-fixed charge names. These are checked before the general buckets
# because "Electric Delivery Base Charge" is a fixed charge, not a delivery
# charge, and "Customer Charge" is not a commodity line.
BASE_STRONG_RE = re.compile(
    r"\bbase\s+charge\b|\bcustomer\s+charge\b|\bsubscriber\s+charge\b"
    r"|\bstanding\s+charge\b|\baccess\s+charge\b|\bconnection\s+charge\b"
    r"|\bmeter\s+charge\b|\bmonthly\s+charge\b|\bminimum\s+(bill|charge)\b"
    r"|\b(primary|secondary|general)\s+service\s+charge\b"
    r"|\bresidential\s+(electric\s+)?service\b|\bbasic\s+service\b"
    r"|\bprimary\s+service\b|\bdelivery\s+base\b",
    re.IGNORECASE,
)

# Commodity service charges are NOT fixed charges.
COMMODITY_SERVICE_RE = re.compile(
    r"\b(electric|gas|energy|standard|commodity)\s+service\s+charge\b",
    re.IGNORECASE,
)


# Buckets that must win before the fixed-charge patterns, because their
# labels often contain words like "service" ("General Service Demand Charge").
DEMAND_STRONG_RE = re.compile(
    r"\bdemand\b|\bkva\b|\breactive\b|\bpower\s+factor\b|\bcapacity\s+charge\b",
    re.IGNORECASE,
)
FEE_STRONG_RE = re.compile(r"\bfee\b|\blate\b|\bpenalt", re.IGNORECASE)
TAX_STRONG_RE = re.compile(r"\btax\b|\bexcise\b|\bfranchise\b", re.IGNORECASE)
DEPOSIT_STRONG_RE = re.compile(r"\bdeposit\b", re.IGNORECASE)
RIDER_STRONG_RE = re.compile(
    r"\brenewable\b|\bportfolio\b|\brps\b|\bcarbon\b|\bemission\b|\breliability\b"
    r"|\bgreen\b|\bclean\s+energy\b|\bsustainability\b|\benvironment\b|\brider\b"
    r"|\bbiodiversity\b|\bcompliance\b|\bassistance\b|\blow\s+income\b|\bbenefit\b",
    re.IGNORECASE,
)
ADJUSTMENT_STRONG_RE = re.compile(
    r"\btrue-?up\b|\bproration\b|\brebill\b|\bcorrection\b|\brevision\b"
    r"|\bsupplemental\b|\bprior\s+month\b|\bprevious\s+period\b",
    re.IGNORECASE,
)
FUEL_STRONG_RE = re.compile(
    r"\bfuel\b|\bcommodity\b|\bbalancing\b|\bgas\s+cost\b", re.IGNORECASE,
)
DELIVERY_STRONG_RE = re.compile(
    r"\bdelivery\b|\bdistribution\b|\btransmission\b|\btransportation\b|\bwires?\b"
    r"|\bnetwork\b|\bgrid\s+charge\b|\bline\s+charge\b|\bsecondary\s+service\b",
    re.IGNORECASE,
)


def categorize(ch: Charge) -> str:
    """Assign a billing bucket to a charge line.

    Order is deliberate: demand, fees, taxes and riders carry unambiguous
    words, so they are resolved first. Fixed base charges are resolved next,
    before the broader delivery/energy patterns, because bills say things like
    "Electric Delivery Base Charge" that would otherwise be misfiled.
    """
    if ch.role in ("total", "payment", "usage"):
        return ch.role
    # A negative line is money coming back, whatever it is called.
    if ch.amount < 0:
        return "credit"
    label = ch.label.lower()

    if DEMAND_STRONG_RE.search(label):
        return "demand"
    if DEPOSIT_STRONG_RE.search(label):
        return "deposit"
    if FEE_STRONG_RE.search(label):
        return "fee"
    if TAX_STRONG_RE.search(label):
        return "tax"
    if RIDER_STRONG_RE.search(label):
        return "rider"
    if ADJUSTMENT_STRONG_RE.search(label):
        return "adjustment"
    if FUEL_STRONG_RE.search(label):
        return "fuel"
    if BASE_STRONG_RE.search(label) and not COMMODITY_SERVICE_RE.search(label):
        return "base"
    if DELIVERY_STRONG_RE.search(label):
        return "delivery"
    for bucket, pattern in BUCKETS:
        if re.search(pattern, label):
            return bucket
    # Fallback: a priced energy unit is a commodity charge even when the label
    # is vague ("Electric Usage - 415 kWh @ 13.10c").
    if ch.unit_rate is not None and ch.unit in ("kWh", "therm", "MMBtu", "ccf", "gal", "m3", "cuft"):
        return "energy"
    return "unclassified"


def classify_bill(bill: ParsedBill) -> Dict[str, float]:
    """Assign a bucket to every item and return per-bucket dollar totals."""
    totals: Dict[str, float] = {}
    for ch in bill.items:
        ch.category = categorize(ch)
        if ch.role in ("payment", "total", "usage"):
            continue
        totals[ch.category] = round(totals.get(ch.category, 0.0) + ch.amount, 2)
    return totals


# ---------------------------------------------------------------------------
# Rate structure detection
# ---------------------------------------------------------------------------

TIER_PATTERNS = [
    r"tier\s*(1|2|3|4|one|two|three|four|i|ii|iii|iv)\b",
    r"\bblock\s*\d",
    r"first\s+\d[\d,]*\s*(kwh|therms?|ccf)",
    r"\bnext\s+\d[\d,]*\s*(kwh|therms?|ccf)",
    r"\bover\s+\d[\d,]*\s*(kwh|therms?|ccf)",
    r"\bup\s+to\s+\d[\d,]*\s*(kwh|therms?|ccf)",
    r"\b\d[\d,]*\s*[-–—]\s*\d[\d,]*\s*(kwh|therms?|ccf)",
    r"\bbasic\s+charge\b",
]

TOU_PATTERNS = [
    r"\bon-?peak\b",
    r"\boff-?peak\b",
    r"\bshoulder\b",
    r"\bpeak\s*(hour|period|rate|charge|window)",
    r"\btime[\s-]*of[\s-]*use\b",
    r"\btou\b",
    r"\bev\s*(rate|charging|plan|off-?peak)",
    r"\bovernight\b",
]

DEMAND_PATTERNS = [r"\bdemand\s*charge\b", r"\bbilling\s+demand\b", r"\bmaximum\s+demand\b",
                   r"\breactive\s+demand\b", r"\bkva\s+demand\b"]

SOLAR_PATTERNS = [r"\bnet\s+metering\b", r"\bsolar\b", r"\bexport\b", r"\bphotovoltaic\b", r"\bpv\b"]

TIER_RANGE_RE = re.compile(
    r"(?<![\d.])(\d[\d,]*)\s*(?:-|\u2013|\u2014|to)\s*(\d[\d,]*)\s*(kwh|therms?|ccf)",
    re.IGNORECASE,
)
TIER_FIRST_RE = re.compile(r"\bfirst\s+(\d[\d,]*)\s*(kwh|therms?|ccf)", re.IGNORECASE)
TIER_NEXT_RE = re.compile(r"\bnext\s+(\d[\d,]*)\s*(kwh|therms?|ccf)", re.IGNORECASE)
TIER_OVER_RE = re.compile(r"\bover\s+(\d[\d,]*)\s*(kwh|therms?|ccf)", re.IGNORECASE)
TIER_UPTO_RE = re.compile(r"\bup\s+to\s+(\d[\d,]*)\s*(kwh|therms?|ccf)", re.IGNORECASE)


def _num(txt: str) -> float:
    return float(txt.replace(",", ""))


def detect_structure(bill: ParsedBill) -> Dict[str, Any]:
    """Infer the rate design from the bill's own language."""
    text = " \n ".join(c.raw for c in bill.items).lower()
    labels = " | ".join(c.label.lower() for c in bill.items)

    tiers = _detect_tiers(bill)
    tou = _detect_tou(bill, text)
    demand_lines = [c for c in bill.items if any(re.search(p, c.label.lower()) for p in DEMAND_PATTERNS)]
    solar = any(re.search(p, text) for p in SOLAR_PATTERNS)

    if tiers:
        kind = "tiered"
    elif tou.get("detected"):
        kind = "time_of_use"
    elif demand_lines:
        kind = "demand_based"
    elif solar:
        kind = "net_metering"
    else:
        kind = "flat"

    return {
        "kind": kind,
        "tiers": tiers,
        "tou": tou,
        "has_demand_charge": bool(demand_lines),
        "demand_lines": [c.to_dict() for c in demand_lines],
        "has_solar_credit": solar,
        "labels_seen": labels[:1200],
    }


def _detect_tiers(bill: ParsedBill) -> List[Dict[str, Any]]:
    """Find tiered blocks and work out each tier's boundaries.

    Real tiered bills express the ladder several ways ("First 500 kWh",
    "0-500 kWh", "Next 1,000 kWh", "Over 1,500 kWh"). Reading the boundaries is
    what lets the analyzer say which tier the customer's last unit falls in and
    how many units they must shed to fall back to a cheaper one.
    """
    found: List[Dict[str, Any]] = []
    for ch in bill.items:
        if ch.role != "charge":
            continue
        raw = ch.raw
        lbl = ch.label.lower()
        is_tier = any(re.search(p, lbl) for p in TIER_PATTERNS)
        has_bound = bool(
            TIER_RANGE_RE.search(raw) or TIER_FIRST_RE.search(raw)
            or TIER_NEXT_RE.search(raw) or TIER_OVER_RE.search(raw)
            or TIER_UPTO_RE.search(raw)
        )
        if not (is_tier or has_bound):
            continue
        if ch.unit_rate is None:
            continue

        from_kwh: Optional[float] = None
        to_kwh: Optional[float] = None
        relative: Optional[str] = None
        width: Optional[float] = None

        m = TIER_RANGE_RE.search(raw)
        if m:
            from_kwh, to_kwh = _num(m.group(1)), _num(m.group(2))
        else:
            m = TIER_FIRST_RE.search(raw)
            if m:
                from_kwh, to_kwh = 0.0, _num(m.group(1))
            else:
                m = TIER_UPTO_RE.search(raw)
                if m:
                    from_kwh, to_kwh = 0.0, _num(m.group(1))
                else:
                    m = TIER_OVER_RE.search(raw)
                    if m:
                        from_kwh, to_kwh = _num(m.group(1)), None
                    else:
                        m = TIER_NEXT_RE.search(raw)
                        if m:
                            relative, width = "next", _num(m.group(1))

        found.append({
            "label": ch.label,
            "quantity": ch.quantity,
            "unit": ch.unit,
            "rate": ch.unit_rate,
            "basis": ch.rate_basis,
            "amount": ch.amount,
            "from_kwh": from_kwh,
            "to_kwh": to_kwh,
            "relative": relative,
            "width": width,
        })

    # Resolve "Next N kWh" into absolute bounds using a running cursor.
    cursor = 0.0
    for t in found:
        if t.get("relative") == "next":
            w = t.get("width") or 0.0
            t["from_kwh"] = cursor
            t["to_kwh"] = cursor + w
            cursor += w
        elif t.get("from_kwh") is not None and t.get("to_kwh") is not None:
            cursor = max(cursor, t["to_kwh"])

    found.sort(key=lambda t: (t.get("from_kwh") is None, t.get("from_kwh") or 0.0))
    return found


def _detect_tou(bill: ParsedBill, text: str) -> Dict[str, Any]:
    on_peak: List[Charge] = []
    off_peak: List[Charge] = []
    for ch in bill.items:
        if ch.role != "charge":
            continue
        lbl = ch.label.lower()
        if re.search(r"off-?peak|overnight|mid-?peak", lbl):
            off_peak.append(ch)
        elif re.search(r"on-?peak|peak", lbl):
            on_peak.append(ch)
    return {
        "detected": bool(on_peak or off_peak or any(re.search(p, text) for p in TOU_PATTERNS)),
        "on_peak": [c.to_dict() for c in on_peak],
        "off_peak": [c.to_dict() for c in off_peak],
        "on_peak_kwh": round(sum(c.quantity or 0 for c in on_peak), 2),
        "off_peak_kwh": round(sum(c.quantity or 0 for c in off_peak), 2),
        "on_peak_rate": _best_rate(on_peak),
        "off_peak_rate": _best_rate(off_peak),
    }


def _best_rate(lines: List[Charge]) -> Optional[float]:
    rates = [c.unit_rate for c in lines if c.unit_rate]
    if not rates:
        return None
    return max(rates)
