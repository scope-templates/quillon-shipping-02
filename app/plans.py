"""The three plans a shop can be on: what each costs a month and what comes with it.

A plan sets how many calls a live key may make in a minute, how many live keys the account may
have (None is no limit), whether the shop's logo goes on its labels, and what a parcel costs as a
percentage of the card. The rate card is the list price; the plan's percentage is taken where a
parcel is priced, so the card itself never changes with the plan.
"""

import calendar
from datetime import datetime
from typing import Any, Dict

PLANS: Dict[str, Dict[str, Any]] = {
    "payg": {
        "monthly_fee_pence": 0,
        "live_requests_per_minute": 120,
        "live_keys": 1,
        "logo_on_label": False,
        "card_percent": 115,
    },
    "standard": {
        "monthly_fee_pence": 2900,
        "live_requests_per_minute": 300,
        "live_keys": 3,
        "logo_on_label": True,
        "card_percent": 100,
    },
    "volume": {
        "monthly_fee_pence": 19900,
        "live_requests_per_minute": 1000,
        "live_keys": None,
        "logo_on_label": True,
        "card_percent": 92,
    },
}

# A signup from the website starts here. A trial stays open until the billing provider starts a
# plan or cancels it.
TRIAL_PLAN = "payg"
TRIAL_DAYS = 30


def fee_for(plan: str) -> int:
    return PLANS[plan]["monthly_fee_pence"]


def parcel_price(plan: str, list_pence: int) -> int:
    """The card price at the plan's percentage, to the nearest 5p, which is how the card is set."""
    percent = PLANS[plan]["card_percent"]
    if percent == 100:
        return list_pence
    return int(round(list_pence * percent / 100 / 5.0)) * 5


def one_month_on(moment: datetime) -> datetime:
    """The same day next month, or the last day of it when next month is shorter."""
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)
