"""Parse pasted utility bill text into a structured representation.

The engine is deliberately forgiving: real bills come from dozens of utilities
with wildly different layouts, so the parser works by *masking* known numeric
patterns (quantities, unit rates, totals) and then classifying whatever label
text is left over. Nothing here talks to the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Unit vocabulary
# ---------------------------------------------------------------------------

UNIT_ALIASES = {
    "kwh": "kWh",
    "kw-hr": "kWh",
    "kw-hrs": "kWh",
    "kw hr": "kWh",
    "kw hrs": "kWh",
    "therm": "therm",
    "therms": "therm",
    "mmbtu": "MMBtu",
    "ccf": "ccf",
    "gal": "gal",
    "gals": "gal",
    "gallon": "gal",
    "gallons": "gal",
    "m3": "m3",
    "m\u00b3": "m3",
    "kw": "kW",
    "kva": "kVA",
    "kvar": "kVAR",
    "cu ft": "cuft",
    "cubic feet": "cuft",
    "cu ft.": "cuft",
}

ENERGY_UNITS = {"kWh", "therm", "MMBtu", "gal", "ccf", "m3", "cuft"}
DEMAND_UNITS = {"kW", "kVA", "kVAR"}

UNIT_TO_UTILITY = {
    "kWh": "electric",
    "therm": "gas",
    "MMBtu": "gas",
    "ccf": "gas",
    "gal": "water",
    "m3": "water",
    "cuft": "water",
}

# ---------------------------------------------------------------------------
# Regex vocabulary
# ---------------------------------------------------------------------------

QTY_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"\s*"
    r"(?P<unit>kw-hrs?|kwh|m\u00b3|m3|therms?|mmbtu|cubic\s+feet|cu\.?\s*ft\.?|gallons?|gals?|ccf|kvar|kva|kw|kwh)\b",
    re.IGNORECASE,
)

RATE_CENTS_RE = re.compile(r"(?<![\d.])(?P<v>\d+(?:\.\d+)?)\s*(?:\u00a2|\u00a3|cents?\b|(?<![A-Za-z])c(?![A-Za-z]))", re.IGNORECASE)
RATE_DOLLAR_PER_RE = re.compile(
    r"(?<![\d.])(?P<cur>\$)?\s*(?P<v>\d+(?:\.\d{1,6})?)\s*(?:/|\bper\b)\s*"
    r"(?P<unit>kw-hrs?|kwh|therms?|mmbtu|ccf|gallons?|gals?|gal|kvar|kva|kw)\b",
    re.IGNORECASE,
)
RATE_AT_RE = re.compile(r"@\s*(?P<cur>\$)?\s*(?P<v>\d+(?:\.\d{1,6})?)")

AMOUNT_RE = re.compile(
    r"(?P<open>\()?\s*(?P<sign>[-\u2013\u2014])?\s*(?P<cur>\$)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"\s*(?P<close>\))?"
)

DATE_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
DATE_WORD_RE = re.compile(
    r"\b(?P<m1>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?P<d1>\d{1,2})"
    r"(?:,?\s+(?P<y1>\d{4}))?"
    r"\s*(?:-|\u2013|\u2014|to|through|thru)\s*"
    r"(?P<m2>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?P<d2>\d{1,2})"
    r"(?:,?\s+(?P<y2>\d{4}))?",
    re.IGNORECASE,
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Header lines are field labels at the START of a line. Anchoring there is far
# more precise than scanning the whole line for a keyword, because real bills
# contain both "Days of Service: 31" and "Service Charge $18.50".
HEADER_RE = re.compile(
    r"^\s*(?:"
    r"account\s*(?:number|no\.?|#|id|name)?|acct\.?|"
    r"service\s+address|billing\s+address|mailing\s+address|"
    r"statement\s+period|billing\s+period|service\s+period|statement\s+date|bill\s+date|"
    r"meter\s*(?:no\.?|number|#|id|serial|reading)\b|read\s+date|next\s+read|billing\s+cycle|"
    r"days\s+of\s+service|billing\s+days|issue\s+date|customer\s+service|"
    r"phone|toll\s+free|service\s+area|rate\s+plan|plan\s+name|"
    r"customer\s*(?:name|number|no\.?|#|id)|policy\s+number|contract\s+number|"
    r"previous\s+balance|prior\s+balance|payments?\s+received"
    r")\b",
    re.IGNORECASE,
)

TOTAL_RE = re.compile(
    r"\b(total\b|amount\s+due|new\s+charges|charges\s+due|total\s+due|please\s+pay|"
    r"balance\s+due|total\s+current|your\s+total|subtotal|net\s+amount|total\s+amount)\b",
    re.IGNORECASE,
)

PAYMENT_RE = re.compile(
    r"\b(payments?\s+received|payments?\s+applied|previous\s+balance|prior\s+balance|"
    r"credit\s+applied|debit\s+applied|refund|autopay|auto\s*pay|thank\s+you|"
    r"for\s+your\s+records|please\s+send\s+payment)\b",
    re.IGNORECASE,
)

# A late fee is a charge, not a payment - it must survive to be classified.
LATE_FEE_RE = re.compile(
    r"\blate\s+(payment\s+)?(fee|charge|penalty)\b|\bpast\s+due\s+(fee|charge)\b",
    re.IGNORECASE,
)

USAGE_LINE_RE = re.compile(
    r"\b(usage|used|consumption|consumed|delivered|total\s+kwh|your\s+usage|billed\s+usage|"
    r"actual\s+usage|estimated\s+usage|kwh\s+used|read|reading|meter)\b",
    re.IGNORECASE,
)

ESTIMATED_RE = re.compile(r"\b(estimated|estimate|projected|billing\s+estimate)\b", re.IGNORECASE)

CREDIT_TAIL_RE = re.compile(r"\b(CR|DR|CREDIT|DEBIT)\b")


def _norm_unit(raw: str) -> Optional[str]:
    key = re.sub(r"\s+", " ", raw.strip().lower()).rstrip(".")
    return UNIT_ALIASES.get(key)


def _mask(chars: List[str], start: int, end: int) -> None:
    for i in range(max(0, start), min(end, len(chars))):
        chars[i] = "\x00"


@dataclass
class Charge:
    label: str
    amount: float
    category: str = "unclassified"
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_rate: Optional[float] = None
    rate_basis: Optional[str] = None      # "cents" | "dollars"
    role: str = "charge"                  # charge | total | payment | usage
    raw: str = ""
    is_credit: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["amount"] = round(self.amount, 2)
        if self.unit_rate is not None:
            d["unit_rate"] = round(self.unit_rate, 6)
        if self.quantity is not None:
            d["quantity"] = round(self.quantity, 4)
        return d


@dataclass
class ParsedBill:
    utility: str = "unknown"
    utility_source: str = "unknown"
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    period_days: Optional[int] = None
    account_hint: Optional[str] = None
    items: List[Charge] = field(default_factory=list)
    usage: Dict[str, float] = field(default_factory=dict)      # unit -> quantity
    usage_estimated: bool = False
    total_stated: Optional[float] = None
    total_label: Optional[str] = None
    sum_of_charges: float = 0.0
    lines_seen: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "utility": self.utility,
            "utility_source": self.utility_source,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "period_days": self.period_days,
            "account_hint": self.account_hint,
            "items": [c.to_dict() for c in self.items],
            "usage": self.usage,
            "usage_estimated": self.usage_estimated,
            "total_stated": self.total_stated,
            "total_label": self.total_label,
            "sum_of_charges": round(self.sum_of_charges, 2),
            "lines_seen": self.lines_seen,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Line-level extraction
# ---------------------------------------------------------------------------


def _extract_rate(text: str) -> Tuple[Optional[float], Optional[str], Optional[str], Tuple[int, int]]:
    """Return (rate_value, basis, unit, span).

    basis is "cents" or "dollars" per unit.
    """
    best = None

    for m in RATE_DOLLAR_PER_RE.finditer(text):
        cur = m.group("cur")
        unit = _norm_unit(m.group("unit"))
        basis = "dollars" if cur else ("cents" if unit in {"kWh", "therm", "gal", "ccf", "MMBtu", "m3", "cuft"} else "dollars")
        val = float(m.group("v"))
        if cur:
            val = val
        elif basis == "cents":
            val = val / 100.0
        cand = (m.start(), m.end(), val, basis, unit)
        if best is None or (m.end() - m.start()) > (best[1] - best[0]):
            best = cand

    if best is None:
        for m in RATE_CENTS_RE.finditer(text):
            cand = (m.start(), m.end(), float(m.group("v")) / 100.0, "cents", None)
            if best is None or (m.end() - m.start()) > (best[1] - best[0]):
                best = cand

    if best is None:
        for m in RATE_AT_RE.finditer(text):
            cur = m.group("cur")
            cand = (m.start(), m.end(), float(m.group("v")), "dollars" if cur else None, None)
            if best is None or (m.end() - m.start()) > (best[1] - best[0]):
                best = cand

    if best is None:
        return None, None, None, (0, 0)
    return best[2], best[3], best[4], (best[0], best[1])


def _extract_amount(text: str, masked: List[Tuple[int, int]]) -> Tuple[Optional[float], Optional[int]]:
    """Pick the single most plausible money amount on a line."""
    cands = []
    for m in AMOUNT_RE.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in masked):
            continue
        raw = m.group(0).strip()
        num_txt = m.group("num")
        cur = m.group("cur")
        sign = m.group("sign")
        neg = bool(m.group("open")) or bool(sign)
        has_decimal = "." in num_txt
        try:
            val = float(num_txt.replace(",", ""))
        except ValueError:
            continue
        # Reject bare integers unless the line is otherwise a simple charge.
        if not cur and not has_decimal:
            cands.append((m.start(), m.end(), val, neg, False, "int"))
            continue
        cands.append((m.start(), m.end(), val, neg, True, "money"))

    money = [c for c in cands if c[4]]
    chosen = money[-1] if money else None
    if chosen is None:
        ints = [c for c in cands if not c[4]]
        # A bare integer is only an amount when it is the sole numeric token,
        # is short enough to plausibly be money, and is not part of a date.
        # This keeps account numbers, meter serials and zip codes out.
        if len(ints) == 1 and not re.search(r"\d{1,2}/\d{1,2}", text):
            raw_int = ints[0][0]
            digits = re.sub(r"\D", "", text[ints[0][0]:ints[0][1]])
            if len(digits) <= 4:
                chosen = ints[0]
    if chosen is None:
        return None, None
    val = chosen[2]
    if chosen[3]:
        val = -val
    return val, chosen[1]


def _clean_label(text: str) -> str:
    s = re.sub(r"[\x00]", " ", text)
    s = s.replace("@", " ")
    s = re.sub(r"\s{2,}", " ", s)
    s = s.replace("(", " ").replace(")", " ").replace(":", " ").replace("|", " ")
    s = re.sub(r"\s{2,}", " ", s)
    s = s.strip(" .,-_|")
    # Drop a trailing dangling separator left behind by a masked rate.
    s = re.sub(r"\s*[-–—]\s*$", "", s).strip(" .,-_|")
    return s.strip()


def parse_line(line: str) -> Optional[Charge]:
    raw = line.rstrip()
    if not raw.strip():
        return None
    if not re.search(r"\d", raw):
        return None

    text = raw
    chars = list(text)
    masked: List[Tuple[int, int]] = []

    qty = None
    unit = None
    qty_match = None
    rate_val, rate_basis, rate_unit, rate_span = _extract_rate(text)
    if rate_span[1] > rate_span[0]:
        masked.append(rate_span)
        _mask(chars, rate_span[0], rate_span[1])

    for m in QTY_RE.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in masked):
            continue
        u = _norm_unit(m.group("unit"))
        if u is None:
            continue
        try:
            q = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        qty, unit, qty_match = q, u, m
        masked.append((m.start(), m.end()))
        _mask(chars, m.start(), m.end())
        break

    amount, amount_end = _extract_amount(text, masked)

    # Build the label from what is left after masking quantities and rates.
    label = _clean_label("".join(chars))
    if not label:
        label = _clean_label(re.sub(r"\d[\d,.]*", " ", text))

    role = "charge"
    if TOTAL_RE.search(label):
        role = "total"
    elif PAYMENT_RE.search(label):
        role = "payment"
    if LATE_FEE_RE.search(raw):
        role = "charge"

    if role == "charge" and amount is not None and HEADER_RE.match(text):
        # Header lines ("Account Number: 0123456789", "Days of Service: 31")
        # carry identifiers, not charges. Payment and total lines are exempt:
        # their amounts are real money.
        amount = None
        amount_end = None
    elif amount_end is not None:
        # Mask the amount out of the label so it is not repeated in it.
        _mask(chars, amount_end - len(str(int(abs(amount)))), amount_end)
        label = _clean_label("".join(chars)) or label

    if amount is None:
        if qty is not None and unit in ENERGY_UNITS and USAGE_LINE_RE.search(label):
            role = "usage"
        else:
            return None

    ch = Charge(
        label=label or "(unlabelled)",
        amount=float(amount or 0.0),
        role=role,
        quantity=qty,
        unit=unit,
        unit_rate=rate_val,
        rate_basis=rate_basis,
        raw=raw.strip(),
    )
    if CREDIT_TAIL_RE.search(raw) and ch.amount > 0 and role == "charge":
        ch.is_credit = True
    if amount is not None and amount < 0 and role == "charge":
        ch.is_credit = True
    return ch


# ---------------------------------------------------------------------------
# Period detection
# ---------------------------------------------------------------------------


def _to_date(m: int, d: int, y: int) -> Optional[date]:
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, m, d)
    except ValueError:
        return None


def detect_period(text: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    head = "\n".join(text.splitlines()[:14])
    m = DATE_WORD_RE.search(head) or DATE_WORD_RE.search(text)
    if m:
        m1 = MONTHS.get(m.group("m1").lower())
        d1 = int(m.group("d1"))
        y1 = m.group("y1")
        m2 = MONTHS.get(m.group("m2").lower())
        d2 = int(m.group("d2"))
        y2 = m.group("y2")
        if m1 and m2:
            year = int(y1 or y2 or datetime.now().year)
            d0 = _to_date(m1, d1, year)
            d1v = _to_date(m2, d2, year)
            if d0 and d1v:
                if d1v < d0:
                    d1v = date(d1v.year + 1, d1v.month, d1v.day)
                return d0.isoformat(), d1v.isoformat(), (d1v - d0).days + 1
    dates = DATE_SLASH_RE.findall(head)
    if len(dates) >= 2:
        a = _to_date(int(dates[0][0]), int(dates[0][1]), int(dates[0][2]))
        b = _to_date(int(dates[1][0]), int(dates[1][1]), int(dates[1][2]))
        if a and b:
            if b < a:
                b = date(b.year + 1, b.month, b.day)
            return a.isoformat(), b.isoformat(), (b - a).days + 1
    if len(dates) == 1:
        a = _to_date(int(dates[0][0]), int(dates[0][1]), int(dates[0][2]))
        if a:
            nxt = date(a.year + (a.month == 12), a.month % 12 + 1, a.day)
            return a.isoformat(), nxt.isoformat(), (nxt - a).days
    dm = re.search(r"(\d{1,3})\s*days?\s+of\s+service|billing\s+period\s*:?\s*(\d{1,3})\s*days", text, re.IGNORECASE)
    if dm:
        return None, None, int(dm.group(1) or dm.group(2))
    return None, None, None


def _guess_utility(items: List[Charge], usage: Dict[str, float], text: str) -> Tuple[str, str]:
    for unit, qty in usage.items():
        if unit in UNIT_TO_UTILITY:
            return UNIT_TO_UTILITY[unit], "usage-unit:" + unit
    low = text.lower()
    if "kwh" in low:
        return "electric", "text:kWh"
    if "therm" in low or "mmbtu" in low or "natural gas" in low:
        return "gas", "text:gas"
    if "water" in low or "sewer" in low or "wastewater" in low:
        return "water", "text:water"
    return "unknown", "unknown"


# ---------------------------------------------------------------------------
# Bill level
# ---------------------------------------------------------------------------


def parse_bill(text: str, utility_hint: Optional[str] = None) -> ParsedBill:
    bill = ParsedBill()
    raw_lines = text.splitlines()
    bill.lines_seen = len([l for l in raw_lines if l.strip()])

    charges: List[Charge] = []
    usage_totals: Dict[str, float] = {}
    total_stated: Optional[float] = None
    total_label: Optional[str] = None

    for raw in raw_lines:
        ch = parse_line(raw)
        if ch is None:
            continue
        if ch.role == "total":
            # Prefer a total whose amount is at or above the running charge sum.
            if total_stated is None or ch.amount >= total_stated:
                total_stated = ch.amount
                total_label = ch.label
            charges.append(ch)
            continue
        if ch.role == "payment":
            charges.append(ch)
            continue
        if ch.role == "usage":
            if ch.unit and ch.quantity is not None:
                usage_totals[ch.unit] = usage_totals.get(ch.unit, 0.0) + ch.quantity
                if ESTIMATED_RE.search(ch.raw):
                    bill.usage_estimated = True
            charges.append(ch)
            continue
        charges.append(ch)

    bill.items = charges

    # Usage can also be inferred from a charge line that carries a quantity.
    for ch in charges:
        if ch.role != "charge":
            continue
        if ch.unit in ENERGY_UNITS and ch.quantity and ch.quantity > 0:
            lbl = ch.label.lower()
            if any(k in lbl for k in ("usage", "used", "delivered", "consumption", "total", "kwh", "therm", "m3", "gal")):
                if ch.unit not in usage_totals:
                    usage_totals[ch.unit] = ch.quantity

    # Energy charges on a tiered bill each carry a quantity; sum them.
    tier_qty = 0.0
    tier_unit = None
    for ch in charges:
        if ch.role == "charge" and ch.unit in ENERGY_UNITS and ch.quantity and ch.quantity:
            tier_qty += ch.quantity
            tier_unit = ch.unit
    if tier_unit and tier_unit not in usage_totals and tier_qty > 0:
        usage_totals[tier_unit] = tier_qty

    bill.usage = usage_totals

    bill.period_start, bill.period_end, bill.period_days = detect_period(text)
    bill.utility, bill.utility_source = _guess_utility(charges, usage_totals, text)
    if utility_hint and utility_hint != "auto":
        bill.utility = utility_hint
        bill.utility_source = "user"

    bill.total_stated = total_stated
    bill.total_label = total_label
    bill.sum_of_charges = round(sum(
        c.amount for c in charges
        if c.role == "charge" and not (c.is_credit and c.category == "credit")
    ), 2)

    if total_stated is None:
        bill.notes.append("No 'total amount due' line was found; totals were reconstructed from line items.")

    # Account hint from header lines.
    for raw in raw_lines[:10]:
        if re.search(r"\b(account|acct)\b", raw, re.IGNORECASE):
            m = re.search(r"([A-Z0-9]{6,})", raw.upper())
            if m:
                bill.account_hint = m.group(1)[:12]
                break

    return bill
