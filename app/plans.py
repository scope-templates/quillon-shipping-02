"""The three plans a shop can be on: what each costs a month and what it takes off the card.

The rate card is the list price. A plan with a monthly fee takes a share off every parcel, and
that is done where a parcel is priced, so the card itself never changes with the plan.
"""

import calendar
from datetime import datetime
from typing import Dict

PLANS: Dict[str, Dict[str, int]] = {
    "payg": {"monthly_fee_pence": 0, "parcel_discount_percent": 0},
    "standard": {"monthly_fee_pence": 4900, "parcel_discount_percent": 5},
    "volume": {"monthly_fee_pence": 19900, "parcel_discount_percent": 12},
}

# A signup from the website starts here. A trial stays open until the billing provider starts a
# plan or cancels it.
TRIAL_PLAN = "payg"
TRIAL_DAYS = 30


def fee_for(plan: str) -> int:
    return PLANS[plan]["monthly_fee_pence"]


def parcel_price(plan: str, list_pence: int) -> int:
    """The card price less the plan's share, to the nearest 5p, which is how the card is set."""
    off = PLANS[plan]["parcel_discount_percent"]
    if not off:
        return list_pence
    return int(round(list_pence * (100 - off) / 100 / 5.0)) * 5


def one_month_on(moment: datetime) -> datetime:
    """The same day next month, or the last day of it when next month is shorter."""
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)
