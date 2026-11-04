"""The calls log: every published call, its real outcome, and your feedback.

Each `setups` run appends its calls to ``~/.tradingagents/calls.jsonl`` (once per
date, symbol and kind). ``review`` replays each swing/value call on the prices
that followed (same mechanics as the backtest: buy-stop or buy at the next open,
stop, target, time exit; swing calls since 2026-11-05: half at the target,
the rest on a 20-EMA close) and summarizes the hit rate by verdict and strategy.
``feedback`` attaches your notes. Together they show which calls
deserve more trust, and which need a rule change.
"""

from __future__ import annotations

import json
import os
from datetime import date

import pandas as pd


def calls_path() -> str:
    return os.environ.get("TRADINGAGENTS_CALLS_PATH") or os.path.join(
        os.path.expanduser("~"), ".tradingagents", "calls.jsonl"
    )


def _load(path: str | None = None) -> list[dict]:
    path = path or calls_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _save(rows: list[dict], path: str | None = None) -> None:
    path = path or calls_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    os.replace(tmp, path)


def record(setups: dict, path: str | None = None) -> int:
    """Log the swing, value and core calls of a ``setups`` result. Returns how many are new."""
    rows = _load(path)
    seen = {(r["as_of"], r["symbol"], r["kind"]) for r in rows}
    as_of = setups["as_of"]
    new = []
    for i in setups["swing"]["ideas"]:
        new.append({"as_of": as_of, "kind": "swing", "symbol": i["symbol"], "strategy": i["strategy"],
                    "grade": i["grade"], "cap": i["cap"], "entry_type": i["entry_type"], "entry": i["entry"],
                    "stop": i["stop"], "target": i["target"], "hold_sessions": i["hold_sessions"],
                    "verdict": i["verdict"], "exit": "half_ema20", "money_flow": i.get("money_flow")})
    for v in setups.get("value", {}).get("picks", []):
        new.append({"as_of": as_of, "kind": "value", "symbol": v["symbol"], "strategy": "value", "grade": "V",
                    "cap": v["cap"], "entry_type": "open", "entry": v["entry"], "stop": v["stop"],
                    "target": v["target"], "hold_sessions": 120, "verdict": v.get("verdict", "VALUE")})
    for p in setups.get("core", {}).get("picks", []):
        if p["action"].startswith(("BUY", "WAIT")):
            new.append({"as_of": as_of, "kind": "core", "symbol": p["symbol"], "strategy": "momentum",
                        "grade": "M", "cap": p["cap"], "entry_type": "open", "entry": p["close"],
                        "stop": p["stop"], "target": None, "hold_sessions": 63, "verdict": p["action"]})
    added = [r for r in new if (r["as_of"], r["symbol"], r["kind"]) not in seen]
    if added:
        _save(rows + added, path)
    return len(added)


def feedback(symbol: str, note: str, rating: str | None = None, as_of: str | None = None,
             path: str | None = None) -> dict:
    """Attach a note (and good/bad) to the latest call on ``symbol`` (or the one on ``as_of``)."""
    rows = _load(path)
    sym = symbol.upper()
    matches = [r for r in rows if r["symbol"].upper().removesuffix(".NS") == sym.removesuffix(".NS")
               and (as_of is None or r["as_of"] == as_of)]
    if not matches:
        raise ValueError(f"no logged call on {symbol}" + (f" from {as_of}" if as_of else ""))
    target = max(matches, key=lambda r: r["as_of"])
    target.setdefault("feedback", []).append({"on": date.today().isoformat(), "note": note, "rating": rating})
    _save(rows, path)
    return target


def outcome(call: dict, bars: pd.DataFrame) -> dict:
    """What happened after a swing/value/core call, on the daily bars that followed."""
    after = bars[bars.index > pd.Timestamp(call["as_of"])]
    if after.empty:
        return {"status": "pending"}
    first = after.iloc[0]
    if call["entry_type"] == "stop":
        if first["High"] < call["entry"]:
            return {"status": "not triggered"}
        entry = max(call["entry"], first["Open"])
    else:
        entry = first["Open"]
    stop, target = call["stop"], call.get("target")
    if call.get("exit") == "half_ema20" and target:
        return _outcome_trailing(bars, after, entry, stop, entry + (target - call["entry"]))
    window = after.iloc[: call["hold_sessions"]]
    for k, (_, b) in enumerate(window.iterrows()):
        if b["Low"] <= stop:
            px = min(stop, b["Open"]) if k > 0 else stop
            return {"status": "stop", "ret_pct": round((px / entry - 1) * 100, 2), "days": k + 1}
        if target and b["High"] >= target:
            px = max(target, b["Open"]) if k > 0 else target
            return {"status": "target", "ret_pct": round((px / entry - 1) * 100, 2), "days": k + 1}
    last = window.iloc[-1]
    if len(window) < call["hold_sessions"]:
        return {"status": "open", "ret_pct": round((last["Close"] / entry - 1) * 100, 2), "days": len(window)}
    return {"status": "time", "ret_pct": round((last["Close"] / entry - 1) * 100, 2), "days": len(window)}


def _outcome_trailing(bars: pd.DataFrame, after: pd.DataFrame, entry: float, stop: float,
                      target: float) -> dict:
    """The no-time-limit swing exit: half at the target, the rest on a 20-EMA close."""
    from tradingagents.scanner.strategies import run_exit

    ema20 = bars["Close"].ewm(span=20, adjust=False).mean().reindex(after.index)
    arr = [after[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close")]
    res = run_exit(*arr, ema20.to_numpy(dtype=float), 0, entry, stop, target)
    if res is None:
        hit = bool((after["High"] >= target).any())
        return {"status": "open", "ret_pct": round((after["Close"].iloc[-1] / entry - 1) * 100, 2),
                "days": len(after), "half_sold": hit}
    gross, j, outcome = res
    status = "stop" if outcome == "stop" else "target"
    return {"status": status, "exit_detail": outcome, "ret_pct": round(gross * 100, 2), "days": j + 1}


def review(bars_by_symbol: dict[str, pd.DataFrame], path: str | None = None) -> dict:
    rows = _load(path)
    out = []
    for r in rows:
        bars = bars_by_symbol.get(r["symbol"])
        res = outcome(r, bars) if bars is not None else {"status": "no data"}
        out.append({**r, **res})
    df = pd.DataFrame(out)
    if df.empty:
        return {"calls": 0, "rows": []}
    closed = df[df["status"].isin(["stop", "target", "time"])]

    def group(col):
        if closed.empty:
            return {}
        g = closed.groupby(col)["ret_pct"]
        return {str(k): {"n": int(len(v)), "win_rate": round(float((v > 0).mean() * 100), 0),
                         "avg_ret_pct": round(float(v.mean()), 2)} for k, v in g}

    return {
        "calls": int(len(df)),
        "by_status": df["status"].value_counts().to_dict(),
        "closed": int(len(closed)),
        "win_rate": round(float((closed["ret_pct"] > 0).mean() * 100), 1) if not closed.empty else None,
        "avg_ret_pct": round(float(closed["ret_pct"].mean()), 2) if not closed.empty else None,
        "by_kind": group("kind"), "by_grade": group("grade"), "by_strategy": group("strategy"),
        "by_verdict": group("verdict"),
        "feedback": [r for r in out if r.get("feedback")],
        "rows": out,
    }
