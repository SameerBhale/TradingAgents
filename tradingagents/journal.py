"""A trade journal: your entries, exits, charges, P&L and capital, in one JSON file.

The file lives at ``~/.tradingagents/journal.json`` (override with
``TRADINGAGENTS_JOURNAL_PATH``). Charges default to an estimate for NSE
delivery trades: about 0.12% on the buy (STT 0.1%, stamp duty 0.015%, exchange
and SEBI fees, GST) and 0.11% on the sell plus a Rs 15.93 DP charge. Pass the
real figure from your contract note with ``charges`` to be exact.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date

BUY_COST_PCT = 0.12
SELL_COST_PCT = 0.11
DP_CHARGE = 15.93


def journal_path() -> str:
    return os.environ.get("TRADINGAGENTS_JOURNAL_PATH") or os.path.join(
        os.path.expanduser("~"), ".tradingagents", "journal.json"
    )


@dataclass
class Trade:
    id: int
    symbol: str
    entry_date: str
    entry_price: float
    qty: int
    stop: float | None = None
    target: float | None = None
    strategy: str = ""
    notes: str = ""
    exit_date: str | None = None
    exit_price: float | None = None
    charges: float | None = None  # total, both legs; None = estimated

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    @property
    def capital_used(self) -> float:
        return self.entry_price * self.qty

    def est_charges(self, exit_price: float | None = None) -> float:
        buy = self.capital_used * BUY_COST_PCT / 100
        px = exit_price if exit_price is not None else self.exit_price
        sell = (px * self.qty * SELL_COST_PCT / 100 + DP_CHARGE) if px is not None else 0.0
        return round(buy + sell, 2)

    def total_charges(self) -> float:
        return self.charges if self.charges is not None else self.est_charges()

    def gross_pnl(self, price: float | None = None) -> float | None:
        px = self.exit_price if price is None else price
        return None if px is None else round((px - self.entry_price) * self.qty, 2)

    def net_pnl(self, price: float | None = None) -> float | None:
        gross = self.gross_pnl(price)
        if gross is None:
            return None
        charges = self.total_charges() if price is None else self.est_charges(price)
        return round(gross - charges, 2)

    def r_multiple(self, price: float | None = None) -> float | None:
        net = self.net_pnl(price)
        if net is None or self.stop is None or self.stop >= self.entry_price:
            return None
        return round(net / ((self.entry_price - self.stop) * self.qty), 2)

    def holding_days(self, today: date | None = None) -> int:
        end = date.fromisoformat(self.exit_date) if self.exit_date else (today or date.today())
        return (end - date.fromisoformat(self.entry_date)).days


@dataclass
class Journal:
    capital: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    path: str = ""

    @classmethod
    def load(cls, path: str | None = None) -> Journal:
        path = path or journal_path()
        if not os.path.exists(path):
            return cls(path=path)
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls(capital=float(raw.get("capital", 0)), trades=[Trade(**t) for t in raw.get("trades", [])],
                   path=path)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"capital": self.capital, "trades": [asdict(t) for t in self.trades]}, fh, indent=1)
        os.replace(tmp, self.path)

    def add(self, **kw) -> Trade:
        if kw.get("qty", 0) <= 0 or kw.get("entry_price", 0) <= 0:
            raise ValueError("price and quantity must be positive")
        trade = Trade(id=max((t.id for t in self.trades), default=0) + 1, **kw)
        self.trades.append(trade)
        return trade

    def get(self, trade_id: int) -> Trade:
        for t in self.trades:
            if t.id == trade_id:
                return t
        raise ValueError(f"no trade #{trade_id} in the journal")

    def close(self, trade_id: int, exit_price: float, exit_date: str, charges: float | None = None,
              qty: int | None = None) -> Trade:
        """Close a trade (or part of it: ``qty`` splits the rest into a new open trade)."""
        t = self.get(trade_id)
        if not t.is_open:
            raise ValueError(f"trade #{trade_id} is already closed")
        if exit_price <= 0:
            raise ValueError("exit price must be positive")
        if qty is not None and 0 < qty < t.qty:
            rest = Trade(**{**asdict(t), "id": max(x.id for x in self.trades) + 1, "qty": t.qty - qty})
            t.qty = qty
            self.trades.append(rest)
        t.exit_price, t.exit_date, t.charges = exit_price, exit_date, charges
        return t

    def open_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.is_open]

    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    def stats(self, prices: dict[str, float] | None = None) -> dict:
        closed = self.closed_trades()
        nets = [t.net_pnl() for t in closed]
        wins = [n for n in nets if n > 0]
        losses = [n for n in nets if n <= 0]
        rs = [r for r in (t.r_multiple() for t in closed) if r is not None]
        realized = round(sum(nets), 2)
        deployed = round(sum(t.capital_used for t in self.open_trades()), 2)
        unrealized = None
        if prices:
            vals = [t.net_pnl(prices[t.symbol]) for t in self.open_trades() if t.symbol in prices]
            unrealized = round(sum(vals), 2) if vals else 0.0
        return {
            "capital": self.capital,
            "closed_trades": len(closed),
            "open_trades": len(self.open_trades()),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
            "realized_pnl": realized,
            "charges_paid": round(sum(t.total_charges() for t in closed), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
            "best": max(nets) if nets else None,
            "worst": min(nets) if nets else None,
            "capital_deployed": deployed,
            "capital_free": round(self.capital + realized - deployed, 2) if self.capital else None,
            "return_on_capital_pct": round(realized / self.capital * 100, 2) if self.capital else None,
            "unrealized_pnl": unrealized,
            "total_capital_used": round(sum(t.capital_used for t in self.trades), 2),
        }
