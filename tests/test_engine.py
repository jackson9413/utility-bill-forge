"""Smoke tests for the utility bill analyzer engine."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.engine import analyze, analyze_bill, split_bills
from forge.exporter import to_markdown
from forge.parser import parse_bill
from forge.samples import BY_ID, SAMPLES


class TestParser(unittest.TestCase):
    def test_parses_a_simple_charge_line(self):
        bill = parse_bill("  Electric Usage - 415 kWh @ 13.10c              $54.37")
        self.assertEqual(len(bill.items), 1)
        item = bill.items[0]
        self.assertEqual(item.role, "charge")
        self.assertAlmostEqual(item.amount, 54.37, places=2)
        self.assertAlmostEqual(item.quantity or 0, 415, places=1)
        self.assertAlmostEqual(item.unit_rate or 0, 0.1310, places=4)

    def test_finds_total_and_usage(self):
        bill = parse_bill("Total Usage: 690 kWh\nAmount Due  $175.43")
        self.assertAlmostEqual(bill.total_stated or 0, 175.43, places=2)
        self.assertAlmostEqual(bill.usage.get("kWh", 0), 690, places=1)

    def test_negative_amounts_are_credits(self):
        bill = parse_bill("Payments Received - Automatic Payment    -$175.43")
        self.assertEqual(bill.items[0].role, "payment")

    def test_ignores_non_bill_lines(self):
        bill = parse_bill("NORTHERN GRID ELECTRIC COMPANY\nStatement Period: 10/03/2026 - 11/02/2026")
        self.assertEqual(len(bill.items), 0)


class TestCategorize(unittest.TestCase):
    def test_buckets(self):
        from forge.categorize import categorize
        from forge.parser import Charge
        cases = [
            ("Residential Service Charge", "base"),
            ("Energy Charge - First 600 kWh @ 11.24c", "energy"),
            ("Delivery Charge - 690 kWh @ 5.02c", "delivery"),
            ("Demand Charge - 3.2 kW @ $27.50", "demand"),
            ("State Electric Tax", "tax"),
            ("Late Payment Fee", "fee"),
            ("Renewable Energy Standard", "rider"),
            ("Deposit - New Service", "deposit"),
            ("Fuel Cost Adjustment", "fuel"),
        ]
        for label, expected in cases:
            ch = Charge(label=label, amount=1.0)
            self.assertEqual(categorize(ch), expected, label)


class TestTierDetection(unittest.TestCase):
    def test_tier_boundaries(self):
        result = analyze_bill(BY_ID["tiered_residential"]["text"])
        tiers = result["structure"]["tiers"]
        self.assertEqual(len(tiers), 2, "should find two energy tiers")
        self.assertAlmostEqual(tiers[0]["from_kwh"] or 0, 0, places=1)
        self.assertAlmostEqual(tiers[0]["to_kwh"] or 0, 600, places=1)
        self.assertAlmostEqual(tiers[1]["from_kwh"] or 0, 600, places=1)

    def test_marginal_rate_is_the_current_tier(self):
        result = analyze_bill(BY_ID["tiered_residential"]["text"])
        m = result["metrics"]
        self.assertAlmostEqual(m["usage"], 690, places=0)
        # 690 kWh puts the last unit in tier 2 at 15.87c, not tier 1 at 11.24c
        self.assertAlmostEqual(m["marginal_rate"] or 0, 0.1587, places=3)

    def test_tier_floor_savings(self):
        result = analyze_bill(BY_ID["tiered_residential"]["text"])
        ti = result["metrics"]["tier_info"]
        self.assertAlmostEqual(ti["kwh_to_cheaper_tier"] or 0, 90, places=0)
        # Shedding the 90 kWh above the floor removes them at the top rate:
        # 90 * 15.87c = $14.28 (600 kWh of tier 1 is unchanged either way).
        self.assertAlmostEqual(ti["savings_at_cheaper_tier"] or 0, 90 * 0.1587, places=2)


class TestScoring(unittest.TestCase):
    def test_clean_bill_scores_well(self):
        result = analyze_bill(BY_ID["clean_bill"]["text"])
        self.assertGreater(result["score"]["overall"], 70)
        self.assertIn(result["score"]["verdict"],
                      ("clean_bill", "mostly_fine", "worth_a_call"))

    def test_bad_bill_scores_worse(self):
        good = analyze_bill(BY_ID["clean_bill"]["text"])["score"]["overall"]
        bad = analyze_bill(BY_ID["estimated_trueup"]["text"])["score"]["overall"]
        self.assertLess(bad, good)

    def test_score_is_bounded(self):
        for s in SAMPLES:
            result = analyze_bill(s["text"])
            self.assertGreaterEqual(result["score"]["overall"], 0.0)
            self.assertLessEqual(result["score"]["overall"], 100.0)
            for ax in result["score"]["axes"]:
                self.assertGreaterEqual(ax["score"], 0.0)
                self.assertLessEqual(ax["score"], 100.0)


class TestFindings(unittest.TestCase):
    def test_every_sample_produces_findings(self):
        for s in SAMPLES:
            result = analyze_bill(s["text"])
            self.assertIsInstance(result["findings"], list)
            for f in result["findings"]:
                self.assertIn(f["severity"], ("high", "medium", "low"))
                self.assertTrue(f["title"])
                self.assertTrue(f["fix"])
                self.assertIn(f["axis"], ("clarity", "correctness", "value", "structure", "savings"))

    def test_late_fee_detected(self):
        result = analyze_bill(BY_ID["tou_ev"]["text"])
        ids = [f["id"] for f in result["findings"]]
        self.assertIn("late_fee", ids)

    def test_trueup_detected(self):
        result = analyze_bill(BY_ID["estimated_trueup"]["text"])
        ids = [f["id"] for f in result["findings"]]
        self.assertIn("trueup", ids)

    def test_demand_charge_detected(self):
        result = analyze_bill(BY_ID["commercial_demand"]["text"])
        self.assertTrue(result["structure"]["has_demand_charge"])


class TestSavings(unittest.TestCase):
    def test_scenarios_have_basis(self):
        result = analyze_bill(BY_ID["tiered_residential"]["text"])
        self.assertTrue(result["savings"])
        for s in result["savings"]:
            self.assertIn(s["confidence"], ("high", "medium", "low"))
            self.assertTrue(s["basis"])
            self.assertTrue(s["steps"])

    def test_tier_scenario_present(self):
        result = analyze_bill(BY_ID["tiered_residential"]["text"])
        ids = [s["id"] for s in result["savings"]]
        self.assertIn("tier_cliff", ids)


class TestMultiBill(unittest.TestCase):
    def test_split(self):
        parts = split_bills(BY_ID["two_bill_compare"]["text"])
        self.assertEqual(len(parts), 2)

    def test_comparison_flags_trend(self):
        result = analyze(BY_ID["two_bill_compare"]["text"])
        self.assertEqual(result["bill_count"], 2)
        self.assertIsNotNone(result["comparison"])
        notes = [n["id"] for n in result["comparison"]["notes"]]
        self.assertIn("usage_trend", notes)


class TestCallScript(unittest.TestCase):
    def test_every_bill_gets_questions(self):
        for s in SAMPLES:
            result = analyze_bill(s["text"])
            script = result["call_script"]
            self.assertTrue(script["questions"], s["id"])
            self.assertTrue(script["prep"], s["id"])
            self.assertTrue(script["dispute_hint"], s["id"])

    def test_questions_are_deduplicated(self):
        result = analyze_bill(BY_ID["tou_ev"]["text"])
        qs = [q["question"] for q in result["call_script"]["questions"]]
        self.assertEqual(len(qs), len(set(qs)))

    def test_dispute_hint_reflects_reconciliation(self):
        broken = (
            "ELECTRIC BILL\n"
            "Energy Charge - 500 kWh @ 10.00c   $50.00\n"
            "Total Current Charges                    $75.00\n"
            "Total Usage: 500 kWh\n"
        )
        script = analyze_bill(broken)["call_script"]
        self.assertIn("do not reconcile", script["dispute_hint"])

    def test_high_severity_questions_come_first(self):
        result = analyze_bill(BY_ID["tou_ev"]["text"])
        severities = [q["severity"] for q in result["call_script"]["questions"]]
        ranks = {"high": 0, "medium": 1, "low": 2}
        ordered = [ranks.get(s, 3) for s in severities]
        self.assertEqual(ordered, sorted(ordered))


class TestExport(unittest.TestCase):
    def test_markdown(self):
        result = analyze(BY_ID["tiered_residential"]["text"])
        md = to_markdown(result)
        self.assertIn("Utility Bill Audit", md)
        self.assertIn("Cost breakdown", md)
        self.assertIn("Findings", md)
        self.assertIn("Savings scenarios", md)
        self.assertIn("Questions to ask your utility", md)

    def test_markdown_multi(self):
        result = analyze(BY_ID["two_bill_compare"]["text"])
        md = to_markdown(result)
        self.assertIn("Multi-bill comparison", md)


class TestRobustness(unittest.TestCase):
    def test_empty_input(self):
        result = analyze("")
        self.assertEqual(result["bill_count"], 0)

    def test_garbage_input_does_not_crash(self):
        result = analyze("hello world\nthis is not a bill\n42")
        self.assertGreaterEqual(result["bill_count"], 1)

    def test_very_long_input(self):
        text = BY_ID["clean_bill"]["text"] * 20
        result = analyze(text)
        self.assertGreaterEqual(result["bill_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
