"""Built-in sample bills used by the demo loader and the test suite.

These are synthetic, modelled on the layout conventions of real US utility
statements. They exist so the tool can be exercised end-to-end without a
customer's real paperwork.
"""

from __future__ import annotations

from typing import Any, Dict, List

SAMPLES: List[Dict[str, Any]] = [
    {
        "id": "tiered_residential",
        "title": "Tiered residential electric - just over a tier threshold",
        "utility": "auto",
        "customer_class": "residential",
        "profile": "residential",
        "note": "The classic tier-cliff bill: usage sits just above the 600 kWh threshold, so the "
                "top rate is running on the last 90 kWh.",
        "text": """NORTHERN GRID ELECTRIC COMPANY
Statement Period: 10/03/2026 - 11/02/2026
Days of Service: 31
Account: 77-1234567
Service Address: 841 Chestnut Ave, Springfield, IL 62704

CURRENT CHARGES
  Residential Service Charge                 $18.50
  Energy Charge - First 600 kWh @ 11.24c    $67.44
  Energy Charge - Next 90 kWh @ 15.87c     $14.28
  Delivery Charge - 690 kWh @ 5.02c         $34.64
  Fuel Cost Adjustment                       $3.19
  Renewable Energy Standard                  $1.42
  Public Utility Commission Tax             $0.95
  State Electric Tax                         $1.68

  Total Current Charges                     $142.10
  Previous Balance                            $0.00
  Payments Received - Automatic Payment    -$142.10

  Amount Due                                  $0.00

Total Usage: 690 kWh
""",
    },
    {
        "id": "tou_ev",
        "title": "Time-of-use with EV charging - heavy peak exposure",
        "utility": "auto",
        "customer_class": "residential",
        "profile": "residential",
        "note": "A TOU plan where the EV and the dryer run in peak hours, so most usage is billed "
                "at the expensive rate.",
        "text": """PACIFIC GAS & ELECTRIC
Your Summary Bill
Billing Period: September 2 - October 1, 2026
Account Number: 0123456789
Service Address: 2200 Harrison Street, San Francisco, CA 94110

ELECTRIC CHARGES
  Electric Delivery Base Charge                    $23.90
  On-Peak Energy - 245 kWh @ 32.11c              $78.67
  EV Peak Charging - 300 kWh @ 32.11c            $96.33
  Off-Peak Energy - 410 kWh @ 17.43c             $71.46
  Demand Charge - 3.2 kW @ $27.50                 $88.00
  Power Factor Adjustment                          $2.10
  Renewable Portfolio Standard                     $3.85
  California Energy Commission Tax                $1.24
  San Francisco Franchise Tax                      $4.03

  Total Current Charges                          $369.58
  Late Payment Fee                                  $9.50

  New Charges                                    $379.08
  Amount Due                                     $379.08

Total Electric Usage: 955 kWh
""",
    },
    {
        "id": "commercial_demand",
        "title": "Small commercial - demand charges dominate",
        "utility": "auto",
        "customer_class": "commercial",
        "profile": "commercial",
        "note": "A bakery with a heavy demand charge and a large fixed base charge, which is where "
                "efficiency work stops helping.",
        "text": """METRO POWER & LIGHT - COMMERCIAL
Service Address: 1900 Industrial Way, Columbus, OH 43219
Billing Period: 09/01/2026 - 09/30/2026
Account: 55-9900112

CURRENT CHARGES
  General Service Demand Charge - 48 kW @ $14.25  $684.00
  Secondary Energy Charge - 12,400 kWh @ 7.42c  $920.08
  Primary Service Charge                         $145.00
  Delivery Charge - 12,400 kWh @ 3.11c          $385.64
  Capacity Charge - 30 kW @ $5.50               $165.00
  Fuel Cost Adjustment - 12,400 kWh @ 2.85c     $353.40
  Interruptible Power Credit                     -$41.20
  Environmental Compliance Fee                   $18.75
  Ohio Excise Tax                                $62.90
  Ohio Sales Tax - 5.75%                        $117.23
  Municipal Tax                                  $34.10

  Total Current Charges                        $2,844.90
  Previous Balance                             $2,844.90
  Payment Received - ACH                       -$2,844.90

  Amount Due                                      $0.00

Total Usage: 12,400 kWh
""",
    },
    {
        "id": "estimated_trueup",
        "title": "Estimated read with a true-up - the reconciliation trap",
        "utility": "auto",
        "customer_class": "residential",
        "profile": "residential",
        "note": "An estimated read that produced a true-up, plus a line nobody can identify and a "
                "deposit still being held.",
        "text": """CRESCENT VALLEY GAS COMPANY
Monthly Bill Summary
Service Period: 09/05/2026 - 10/04/2026
Account: 4102-88
Service Address: 15 Orchard Lane, Mesa, AZ 85201

CURRENT GAS CHARGES
  Customer Charge                               $12.25
  Gas Distribution Charge - 84 therms @ $0.62   $52.08
  Gas Commodity Charge - 84 therms @ $0.98      $82.32
  Transportation Service Charge - 84 therms     $18.90
  Infrastructure Replacement Charge             $16.40
  Gas Tax (AZ)                                  $4.28
  APS Renewable Energy Charge                   $1.10
  Miscellaneous Service Charge                  $24.75

  Total Current Charges                        $212.08
  Prior Month True-Up Adjustment                 $43.20
  Credit - Low Income Energy Assistance        -$18.50
  Deposit - New Service                          $40.00

  New Charges                                   $276.78
  Amount Due                                    $276.78

Total Usage: 84 therms (Estimated)
""",
    },
    {
        "id": "clean_bill",
        "title": "Clean flat-rate residential bill - nothing to chase",
        "utility": "auto",
        "customer_class": "residential",
        "profile": "residential",
        "note": "A straightforward bill with a full breakdown and a sensible rate. The tool should "
                "find essentially nothing.",
        "text": """RIVERBEND MUNICIPAL ELECTRIC
Statement Period: October 1 - October 31, 2026
Account Number: 66-4321098
Service Address: 302 Maple Court, Madison, WI 53703

CURRENT CHARGES
  Residential Electric Service                    $14.00
  Electric Usage - 415 kWh @ 13.10c              $54.37
  Delivery - 415 kWh @ 4.85c                     $20.13
  Municipal Franchise Tax                         $1.62
  State Public Benefits Fee                       $0.88

  Total Current Charges                          $91.00
  Payments Received - AutoPay                    -$91.00

  Amount Due                                      $0.00

Total Usage: 415 kWh
""",
    },
    {
        "id": "two_bill_compare",
        "title": "Two bills side by side - usage up, rate up",
        "utility": "auto",
        "customer_class": "residential",
        "profile": "residential",
        "note": "Two consecutive bills separated by a divider, showing a usage spike and a rate "
                "increase at the same time.",
        "text": """BLUE RIDGE POWER
Statement Period: 08/01/2026 - 08/31/2026
Account: 12-3456789

CURRENT CHARGES
  Residential Service Charge                 $16.00
  Energy Charge - 520 kWh @ 10.90c           $56.68
  Delivery Charge - 520 kWh @ 4.70c          $24.44
  Fuel Adjustment                             $2.10
  Renewable Energy Charge                     $1.05
  State Utility Tax                           $1.22

  Total Current Charges                      $101.49
  Amount Due                                 $101.49

Total Usage: 520 kWh

------------------------------------------------------------

BLUE RIDGE POWER
Statement Period: 09/01/2026 - 09/30/2026
Account: 12-3456789

CURRENT CHARGES
  Residential Service Charge                 $16.00
  Energy Charge - 790 kWh @ 12.60c           $99.54
  Delivery Charge - 790 kWh @ 5.10c          $40.29
  Fuel Adjustment                             $3.10
  Renewable Energy Charge                     $1.35
  State Utility Tax                           $1.74

  Total Current Charges                      $162.02
  Amount Due                                 $162.02

Total Usage: 790 kWh
""",
    },
]

BY_ID = {s["id"]: s for s in SAMPLES}
