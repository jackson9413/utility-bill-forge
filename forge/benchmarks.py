"""Reference data used by the analyzer.

These are *approximate, static* reference ranges (US averages, 2024-2025 vintage)
compiled from public EIA-style aggregates. They are a sanity band, not live
tariff data, and every one of them can be overridden by the caller. The tool
never fetches anything.
"""

from __future__ import annotations

from typing import Any, Dict

# all-in cost per unit (dollars), low = efficient, high = expensive
BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "residential_electric": {
        "label": "Residential electric (all-in)",
        "unit": "kWh",
        "low": 0.115,
        "high": 0.250,
        "source": "Approximate US national average retail price, 2024-2025 vintage.",
        "note": "State spread is enormous (roughly 8c in cheap hydro states to 35c in expensive coastal states).",
    },
    "commercial_electric": {
        "label": "Commercial electric (all-in)",
        "unit": "kWh",
        "low": 0.082,
        "high": 0.178,
        "source": "Approximate US national average retail price, 2024-2025 vintage.",
        "note": "Demand charges can add 10-40% on top of this for mid-size loads.",
    },
    "residential_gas": {
        "label": "Residential natural gas (all-in)",
        "unit": "therm",
        "low": 1.05,
        "high": 2.60,
        "source": "Approximate US national average delivered price, 2024-2025 vintage.",
        "note": "Heating-season months run far above this band; this is an annual-average band.",
    },
    "commercial_gas": {
        "label": "Commercial natural gas (all-in)",
        "unit": "therm",
        "low": 0.55,
        "high": 1.85,
        "source": "Approximate US national average delivered price, 2024-2025 vintage.",
        "note": "Large industrial users can do far better; this band is for small commercial.",
    },
    "residential_water": {
        "label": "Residential water + sewer (all-in)",
        "unit": "gal",
        "low": 0.008,
        "high": 0.032,
        "source": "Approximate US national average, 2024-2025 vintage.",
        "note": "Includes sewer and stormwater where billed together.",
    },
}

# Which benchmark to use for a detected utility + customer class.
UTILITY_TO_BENCHMARK = {
    ("electric", "residential"): "residential_electric",
    ("electric", "commercial"): "commercial_electric",
    ("gas", "residential"): "residential_gas",
    ("gas", "commercial"): "commercial_gas",
    ("water", "residential"): "residential_water",
}

# Share of on-peak kWh a household realistically can shift off peak.
SHIFTABLE_PEAK_SHARE = 0.30

# Typical peak-period demand reduction from load management (non-firm, no capex).
DEMAND_REDUCTION_SHARE = 0.05

# Label keywords that suggest an EV charger on the account.
EV_PATTERNS = [
    r"\bev\b",
    r"\belectric\s+vehicle\b",
    r"\bcharging\s+(?:station|session|for)\b",
    r"\bcharger\b",
    r"\bvehicle\s+charging\b",
]

WATER_PROFILE = {
    "residential_electric": "residential_electric",
}
