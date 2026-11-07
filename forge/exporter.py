"""Markdown / JSON export of an analysis result."""

from __future__ import annotations

import json
from typing import Any, Dict


def to_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, indent=2, default=str)


def to_markdown(result: Dict[str, Any]) -> str:
    primary = result.get("primary") or {}
    m = primary.get("metrics") or {}
    s = primary.get("score") or {}
    bill = primary.get("bill") or {}
    lines: list = []

    lines.append("# Utility Bill Audit")
    lines.append("")
    lines.append("**Verdict:** {label} ({verdict}) - score {score}/100".format(
        label=s.get("verdict_label", "?"), verdict=s.get("verdict", "?"), score=s.get("overall", 0)))
    lines.append("")
    lines.append(s.get("verdict_blurb", ""))
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    period = "-".join(x for x in [bill.get("period_start"), bill.get("period_end")] if x)
    lines.append("| Utility | {0} |".format(bill.get("utility", "unknown")))
    lines.append("| Billing period | {0} ({1} days) |".format(period or "unknown", bill.get("period_days") or "?"))
    lines.append("| Usage | {0} {1} |".format(
        format(m.get("usage"), ",.0f") if m.get("usage") else "not found", m.get("unit") or ""))
    lines.append("| Total | 0 |".format(format(m.get("total") or 0, ",.2f")))
    if m.get("all_in_rate"):
        lines.append("| All-in rate | {0}c per {1} |".format(
            format(m["all_in_rate"] * 100, ".2f"), m.get("unit")))
    if m.get("commodity_rate"):
        lines.append("| Commodity rate | {0}c per {1} |".format(
            format(m["commodity_rate"] * 100, ".2f"), m.get("unit")))
    if m.get("marginal_rate"):
        lines.append("| Marginal rate | {0}c per {1} |".format(
            format(m["marginal_rate"] * 100, ".2f"), m.get("unit")))
    if m.get("fixed_share") is not None:
        lines.append("| Fixed share of bill | {0}% |".format(format(m["fixed_share"] * 100, ".0f")))
    lines.append("")

    lines.append("## Scorecard")
    lines.append("")
    lines.append("| Axis | Score | Weight |")
    lines.append("| --- | --- | --- |")
    for ax in s.get("axes") or []:
        lines.append("| {0} | {1} | {2} |".format(
            ax.get("label"), ax.get("score"), format(ax.get("weight", 0) * 100, ".0f") + "%"))
    lines.append("")
    for c in s.get("caps") or []:
        lines.append("- Cap applied to **{0}** at {1}: {2}".format(
            c.get("axis"), c.get("limit"), c.get("reason")))
    lines.append("")

    lines.append("## Cost breakdown")
    lines.append("")
    lines.append("| Category | Amount |")
    lines.append("| --- | --- |")
    labels = m.get("bucket_labels") or {}
    for key, amount in (m.get("buckets") or {}).items():
        if abs(amount) < 0.01:
            continue
        lines.append("| {0} | 1 |".format(labels.get(key, key), format(amount, ",.2f")))
    lines.append("")

    findings = primary.get("findings") or []
    lines.append("## Findings ({0})".format(len(findings)))
    lines.append("")
    if not findings:
        lines.append("No findings. Nothing on this bill needs chasing.")
        lines.append("")
    for f in findings:
        lines.append("### [{0}] {1}".format(f.get("severity", "").upper(), f.get("title")))
        lines.append("")
        lines.append("- **Evidence:** {0}".format(f.get("evidence")))
        lines.append("- **Why it matters:** {0}".format(f.get("why")))
        lines.append("- **Fix:** {0}".format(f.get("fix")))
        if f.get("annual_savings"):
            lines.append("- **Estimated annual savings:** 0".format(format(f["annual_savings"], ",.2f")))
        lines.append("")

    savings = primary.get("savings") or []
    lines.append("## Savings scenarios")
    lines.append("")
    if not savings:
        lines.append("No quantified scenarios found.")
        lines.append("")
    for sc in savings:
        head = "### {0}".format(sc.get("title"))
        if sc.get("annual_estimate"):
            head += " - about 0/yr".format(format(sc["annual_estimate"], ",.0f"))
        lines.append(head)
        lines.append("")
        lines.append(sc.get("detail", ""))
        lines.append("")
        lines.append("- **Basis:** {0} (confidence: {1})".format(sc.get("basis"), sc.get("confidence")))
        if sc.get("steps"):
            lines.append("- **Steps:**")
            for st in sc["steps"]:
                lines.append("  - {0}".format(st))
        lines.append("")

    script = primary.get("call_script") or {}
    if script.get("questions"):
        lines.append("## Questions to ask your utility")
        lines.append("")
        lines.append("Bring these. They are ordered so the highest-value question comes first.")
        lines.append("")
        for q in script.get("questions") or []:
            lines.append("- {0}".format(q.get("question")))
        lines.append("")
        if script.get("prep"):
            lines.append("### Before you call")
            lines.append("")
            for p in script.get("prep"):
                lines.append("- {0}".format(p))
            lines.append("")
        if script.get("dispute_hint"):
            lines.append("### Is it worth disputing?")
            lines.append("")
            lines.append(script["dispute_hint"])
            lines.append("")

    comp = result.get("comparison")
    if comp:
        lines.append("## Multi-bill comparison")
        lines.append("")
        lines.append("| Bill | Period | Usage | Total | All-in rate | Score |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in comp.get("rows") or []:
            lines.append("| {0} | {1} | {2} | {3} | {4} | {5} |".format(
                r["index"] + 1,
                r.get("period_start") or "?",
                (format(r["usage"], ",.0f") + " " + str(r.get("unit") or "")) if r.get("usage") else "?",
                "0".format(format(r.get("total") or 0, ",.2f")),
                (format(r["all_in_rate"] * 100, ".2f") + "c") if r.get("all_in_rate") else "?",
                r.get("score"),
            ))
        lines.append("")
        for n in comp.get("notes") or []:
            lines.append("- **{0}** ({1}): {2}".format(n.get("title"), n.get("severity"), n.get("detail")))
        lines.append("")

    return "\n".join(lines) + "\n"
