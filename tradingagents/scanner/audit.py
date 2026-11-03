"""The auditor: checks every call against the plan's rules and the data behind it.

A call is CORRECT when nothing is wrong, QUESTIONABLE when something deserves a
second look (the user decides), and WRONG when it breaks a rule of the plan.
"""

from __future__ import annotations

SWING_STOP = (5.0, 10.0)
SWING_TARGET = (10.0, 20.0)


def audit_swing(idea: dict, market: dict) -> dict:
    wrong, doubts, ok = [], [], []
    risk, reward, rr = idea["risk_pct"], idea["reward_pct"], idea["rr"]
    if not SWING_STOP[0] - 0.05 <= risk <= SWING_STOP[1] + 0.05:
        wrong.append(f"stop {risk:.1f}% is outside the 5-10% swing band")
    else:
        ok.append(f"stop {risk:.1f}% inside 5-10%")
    if not SWING_TARGET[0] - 0.05 <= reward <= SWING_TARGET[1] + 0.05:
        wrong.append(f"target +{reward:.1f}% is outside the 10-20% band")
    else:
        ok.append(f"target +{reward:.1f}% inside 10-20%")
    if rr < 1.8:
        wrong.append(f"reward:risk {rr:.1f} is below 1.8")
    verdict = idea.get("verdict", "")
    if idea["grade"] == "C" and verdict.startswith("TAKE"):
        wrong.append("a grade C setup marked TAKE: its strategy is losing lately")
    if idea.get("earnings_in_window") and verdict.startswith("TAKE"):
        wrong.append(f"results on {idea['earnings_date']} fall inside the hold but the call is TAKE")
    if idea.get("earnings_in_window"):
        doubts.append(f"results {idea['earnings_date']} inside the hold: gap risk")
    if str(idea.get("news_flag", "")).startswith(("negative", "mixed")):
        doubts.append(f"headlines: {idea['news_flag']}")
    if not market.get("filter_on", True):
        doubts.append("Nifty below its 50-DMA: setups fail more often")
    elif market.get("nifty", 0) < market.get("nifty_sma200", 0):
        doubts.append("Nifty below its 200-DMA: weak tape")
    if idea["cap"] == "Small":
        doubts.append("small cap: wider gaps through the stop")
    if idea.get("quantity", 0) <= 0:
        wrong.append("quantity 0: the stop is too wide for the risk budget")
    status = "WRONG" if wrong else "QUESTIONABLE" if doubts else "CORRECT"
    return {"status": status, "wrong": wrong, "doubts": doubts, "ok": ok}


def audit_core(pick: dict, regime_on: bool, mode: str) -> dict:
    wrong, doubts = [], []
    if pick["action"].startswith("BUY") and not regime_on and mode == "safe":
        wrong.append("a BUY in safe mode while the regime is off")
    if abs(pick["stop"] / pick["entry"] - 0.85) > 0.002:
        wrong.append("stop is not 15% below the entry")
    if pick["cap"] == "Small":
        doubts.append("small cap inside the core: expect larger swings")
    if not regime_on and pick["action"].startswith("BUY"):
        doubts.append(f"bought in {mode} mode with the Nifty below its 200-DMA (tested deeper drawdowns)")
    status = "WRONG" if wrong else "QUESTIONABLE" if doubts else "CORRECT"
    return {"status": status, "wrong": wrong, "doubts": doubts}


def audit_value(pick: dict) -> dict:
    wrong, doubts = [], []
    if not SWING_STOP[0] - 0.05 <= pick["risk_pct"] <= SWING_STOP[1] + 0.05:
        wrong.append("stop outside 5-10%")
    if pick.get("earnings_growth_pct") and pick["earnings_growth_pct"] > 100:
        doubts.append("earnings growth over 100% may be one-off")
    if pick.get("pe") and pick.get("sector_pe") and pick["pe"] > pick["sector_pe"]:
        doubts.append("P/E above its sector median")
    doubts.append("value screen is not backtested")
    status = "WRONG" if wrong else "QUESTIONABLE" if doubts else "CORRECT"
    return {"status": status, "wrong": wrong, "doubts": doubts}
