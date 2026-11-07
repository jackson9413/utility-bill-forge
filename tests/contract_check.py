"""Verify every field the frontend reads exists in the API payload.

A mismatch here would render as a blank card in the browser, so this is
checked in CI rather than left to the eye.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from forge.samples import BY_ID

client = app.test_client()
data = client.post("/api/analyze", json={"text": BY_ID["tiered_residential"]["text"]}).get_json()
multi = client.post("/api/analyze", json={"text": BY_ID["two_bill_compare"]["text"]}).get_json()
js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "app.js")).read()

metric_fields = ["total", "recurring_total", "one_time", "usage", "unit", "all_in_rate",
                 "commodity_rate", "marginal_rate", "tier_gap", "fixed_share", "fixed",
                 "buckets", "bucket_labels", "tier_info", "period_start", "period_end",
                 "utility", "customer_class"]
score_fields = ["overall", "verdict", "verdict_label", "verdict_blurb", "axes", "caps"]
finding_fields = ["id", "severity", "title", "evidence", "why", "fix", "annual_savings", "axis"]
saving_fields = ["id", "title", "detail", "basis", "annual_estimate", "confidence", "steps", "effort"]
tier_fields = ["label", "from_kwh", "to_kwh", "rate", "unit"]
ti_fields = ["current_tier", "kwh_to_cheaper_tier", "savings_at_cheaper_tier", "tier_floor"]
cmp_fields = ["rows", "notes"]
cmp_row_fields = ["index", "period_start", "usage", "unit", "total", "all_in_rate", "fixed", "score"]
session_fields = ["id", "created_at", "utility", "customer_class", "total", "usage", "unit",
                  "score", "verdict", "rating", "notes"]

m = data["primary"]["metrics"]
s = data["primary"]["score"]
missing = []

for f in metric_fields:
    if f not in m:
        missing.append("metrics." + f)
for f in score_fields:
    if f not in s:
        missing.append("score." + f)
for f in finding_fields:
    if data["primary"]["findings"] and f not in data["primary"]["findings"][0]:
        missing.append("finding." + f)
for f in saving_fields:
    if data["primary"]["savings"] and f not in data["primary"]["savings"][0]:
        missing.append("saving." + f)
for f in tier_fields:
    tiers = data["primary"]["structure"]["tiers"]
    if tiers and f not in tiers[0]:
        missing.append("tier." + f)
for f in ti_fields:
    if f not in m["tier_info"]:
        missing.append("tier_info." + f)
for f in cmp_fields:
    if f not in multi["comparison"]:
        missing.append("comparison." + f)
for f in cmp_row_fields:
    if f not in multi["comparison"]["rows"][0]:
        missing.append("cmp_row." + f)

hist = client.get("/api/sessions").get_json()["sessions"]
for f in session_fields:
    if hist and f not in hist[0]:
        missing.append("session." + f)

def has_js_key(key: str) -> bool:
    """True when the JS defines this key in one of the colour maps."""
    return re.search(r'["\']?' + re.escape(key) + r'["\']?\s*:', js) is not None


for k in m["buckets"]:
    if k not in m["bucket_labels"]:
        missing.append("bucket_labels." + k)
    if not has_js_key(k):
        missing.append("BUCKET_COLORS." + k)
if not has_js_key(s["verdict"]):
    missing.append("VERDICT_COLORS." + s["verdict"])
for a in s["axes"]:
    if not has_js_key(a["key"]):
        missing.append("AXIS_COLORS." + a["key"])

if missing:
    print("MISSING CONTRACT FIELDS:")
    for f in missing:
        print("  -", f)
    sys.exit(1)
print("Frontend contract satisfied - every field the UI reads is present.")
