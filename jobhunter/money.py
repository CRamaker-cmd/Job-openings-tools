"""Currency helpers. Amounts are stored as EUR-equivalents so jobs from different countries compare; they are shown
(and entered, for per-country minimums) in the country's own currency."""
from __future__ import annotations

from typing import Optional

SYMBOLS = {"EUR": "€", "GBP": "£", "CHF": "CHF ", "SEK": "SEK ", "DKK": "DKK ", "NOK": "NOK ", "PLN": "PLN "}
DEFAULT_FX = {"EUR": 1.0, "GBP": 1.15, "CHF": 1.05, "SEK": 0.09, "DKK": 0.134, "NOK": 0.087, "PLN": 0.23}


def fx_table(cfg: Optional[dict]) -> dict[str, float]:
    """Rates 'this currency -> EUR': built-in defaults overridden by Settings -> Advanced -> exchange rates."""
    return {**DEFAULT_FX, **(((cfg or {}).get("search") or {}).get("fx_to_eur") or {}), "EUR": 1.0}


def sym(cur: str) -> str:
    return SYMBOLS.get(cur, cur + " ")


def fmt(n: float, cur: str = "EUR") -> str:
    """€95k, £60k, CHF 120k; small amounts keep their digits: €5,500."""
    return f"{sym(cur)}{n / 1000:.0f}k" if n >= 10000 else f"{sym(cur)}{n:,.0f}"


def rng(lo: float, hi: float, cur: str = "EUR") -> str:
    """€71–91k, £60–75k, €5,500–7,000, or a single value when both ends are the same."""
    if round(lo) == round(hi):
        return fmt(lo, cur)
    if lo >= 10000 and hi >= 10000:
        return f"{sym(cur)}{lo / 1000:.0f}–{hi / 1000:.0f}k"
    return f"{sym(cur)}{lo:,.0f}–{hi:,.0f}"


def to_local(eur: float, cur: str, cfg: Optional[dict]) -> float:
    rate = fx_table(cfg).get(cur) or 1.0
    return eur / rate


def to_eur(local: float, cur: str, cfg: Optional[dict]) -> float:
    return local * (fx_table(cfg).get(cur) or 1.0)
