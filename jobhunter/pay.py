"""Reads a salary out of free text and turns it into a comparable yearly gross figure in EUR.

Handles what real postings (Dutch and English) actually look like:
  * ranges or single values, ``€5.500 - €7.000``, ``5500 en 7000 euro``, ``€5,500.00/mo - €7,000.00/mo``, ``80k - 100k``
  * the currency before or after the number (€, EUR, euro, £, CHF, SEK, DKK, NOK, PLN)
  * the period: per year / per month / per maand / p.m. / ``/mo`` ... (a bare "€4.500 - €6.000" is read as monthly,
    because no yearly salary is that small)
  * monthly -> yearly:  monthly x 12, plus holiday pay (vakantiegeld, default 8 %) unless the text says it is included
  * a stated bonus is added (``10% bonus``, ``bonus of €5.000``, ``13e maand``); one-off sign-on / relocation money is not
Every result carries a plain-language ``note`` explaining the arithmetic, shown in the dashboard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import money
from .money import DEFAULT_FX


_CUR_RE = r"(?:€|eur(?:os?)?\b|£|gbp\b|chf\b|sek\b|dkk\b|nok\b|pln\b|zł)"
_NUM_RE = r"(?:\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)"
_UNIT_RE = r"(?:\s*/\s*[a-zA-Z]+|\s+per\s+[a-zA-Z]+)"          # "/mo", "per month" sitting between two amounts
_SEP_RE = r"(?:-|–|—|\bto\b|\btot\b|\band\b|\ben\b)"

_RANGE = re.compile(
    rf"(?P<c1>{_CUR_RE})?\s*(?P<n1>{_NUM_RE})\s*(?P<k1>k\b)?\s*(?P<c1b>{_CUR_RE})?(?P<u1>{_UNIT_RE})*\s*"
    rf"{_SEP_RE}\s*(?P<c2>{_CUR_RE})?\s*(?P<n2>{_NUM_RE})\s*(?P<k2>k\b)?\s*(?P<c2b>{_CUR_RE})?",
    re.I)
_SINGLE = re.compile(
    rf"(?:(?P<c>{_CUR_RE})\s*(?P<n>{_NUM_RE})\s*(?P<k>k\b)?)|(?:(?P<n_>{_NUM_RE})\s*(?P<k_>k\b)?\s*(?P<c_>{_CUR_RE}))",
    re.I)

_PERIODS = {
    "year": re.compile(r"per\s+(?:year|annum|jaar)\b|/\s*(?:yr|year|jaar|y)\b|\bp\.?\s?a\.?\b|annual|yearly|jaarlijks|"
                       r"jaarsalaris|per\s+yr\b|(?:pro|per)\s+jahr|j[äa]hrlich|jahresgehalt|per\s+a[ñn]o|al\s+a[ñn]o|par\s+an\b|per\s+[åa]r\b|rocznie", re.I),
    "month": re.compile(r"per\s+(?:month|maand|mnd)\b|/\s*(?:mo|mth|month|maand|mnd|m)\b|\bp\.?\s?m\.?\b|monthly|"
                        r"maandelijks|maandsalaris|a\s+month|\bpm\b|(?:pro|per)\s+monat|monatlich|monatsgehalt|per\s+mes\b|al\s+mes\b|par\s+mois|"
                        r"mensuel|per\s+m[åa]nad|per\s+m[åa]ned|miesi[eę]cznie", re.I),
    "week": re.compile(r"per\s+(?:week|wk)\b|/\s*(?:wk|week)\b|weekly|per\s+week", re.I),
    "day": re.compile(r"per\s+(?:day|dag)\b|/\s*(?:day|dag|d)\b|daily|dagtarief", re.I),
    "hour": re.compile(r"per\s+(?:hour|uur|hr)\b|/\s*(?:h|hr|hour|uur)\b|hourly|uurtarief|per\s+uur", re.I),
}
_SALARY_WORDS = re.compile(r"salar|loon|bruto|gross|compensation|\bpay\b|verdien|bieden|offer|range|base|inkomen|beloning|uur?tarief|vergoeding", re.I)
_BONUS_NEAR = re.compile(r"bonus|sign-?on|signing|welcome|relocation|referral|verhuis|budget|stipend|allowance", re.I)
_INCLUDED = re.compile(r"incl(?:usief|usive|\.)?\s*(?:\d+\s*%\s*)?(?:vakantie(?:geld|toeslag)|holiday)|"
                       r"(?:vakantie(?:geld|toeslag)|holiday\s+(?:pay|allowance))\s+(?:is\s+)?(?:included|inbegrepen|inclusief)", re.I)
_THIRTEENTH = re.compile(r"13(?:e|th|de)?\s*(?:maand|month)|dertiende\s+maand|13\s*x\b", re.I)
_BONUS_PCT = [
    re.compile(r"(\d{1,2}(?:[.,]\d)?)\s*%\s*(?:annual\s+|jaarlijkse\s+|performance\s+|target\s+|variable\s+|variabele\s+)?(?:bonus|variabel)", re.I),
    re.compile(r"bonus\s*(?:of|van|up\s+to|tot|around|ca\.?|:|=)?\s*(?:up\s+to\s+|tot\s+)?(\d{1,2}(?:[.,]\d)?)\s*%", re.I),
]
_BONUS_AMT = [
    re.compile(rf"bonus\s*(?:of|van|up\s+to|tot|around|ca\.?|:|=)?\s*(?:up\s+to\s+|tot\s+)?(?P<c>{_CUR_RE})\s*(?P<n>{_NUM_RE})", re.I),
    re.compile(rf"(?P<c>{_CUR_RE})\s*(?P<n>{_NUM_RE})\s*(?:annual\s+|jaarlijkse\s+|yearly\s+)?bonus", re.I),
]
_ONE_OFF = re.compile(r"sign-?on|signing|welcome|relocation|referral|verhuis", re.I)


@dataclass
class Pay:
    lo: int                    # yearly gross, EUR-equivalent
    hi: int
    period: str                # period as stated in the text: year | month
    currency: str              # as stated
    note: str                  # how the figure was computed, in plain words
    assumed_period: bool = False


def to_number(s: str) -> float:
    s = s.replace(" ", "").replace(" ", "")
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)([.,]\d{1,2})?", s)
    if m:  # 5.500  5,500  5,500.00  5.500,00
        whole = re.sub(r"[.,]", "", m.group(1))
        dec = m.group(2)[1:] if m.group(2) else ""
        return float(whole + ("." + dec if dec else ""))
    return float(s.replace(",", "."))


def _norm_cur(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    t = token.lower()
    if t in ("€",) or t.startswith("eur"):
        return "EUR"
    return {"£": "GBP", "zł": "PLN"}.get(t, t.upper())


def _period(span_and_after: str, before: str) -> Optional[str]:
    """The period word closest after the amount wins, else the one just before it."""
    best: tuple[int, str] | None = None
    for name, rx in _PERIODS.items():
        m = rx.search(span_and_after)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    if best:
        return best[1]
    last: tuple[int, str] | None = None
    for name, rx in _PERIODS.items():
        for m in rx.finditer(before):
            if last is None or m.start() > last[0]:
                last = (m.start(), name)
    return last[1] if last else None


def _eur(x: float, cur: str, fx: dict) -> float:
    return x * float(fx.get(cur, 1.0 if cur == "EUR" else 0.0))


def _fmt(n: float, cur: str = "EUR") -> str:
    return money.fmt(n, cur)


def _rng(lo: float, hi: float, cur: str = "EUR") -> str:
    return money.rng(lo, hi, cur)


def _bonus(text: str, lo_base: float, hi_base: float, monthly: Optional[tuple[float, float]], fx: dict):
    """-> (lo_extra, hi_extra, description) for a bonus stated in the text, else (0, 0, '')."""
    for rx in _BONUS_PCT:
        m = rx.search(text)
        if m:
            pct = float(m.group(1).replace(",", "."))
            if 0 < pct <= 60:
                return lo_base * pct / 100, hi_base * pct / 100, f"+{pct:g}% bonus"
    for rx in _BONUS_AMT:
        for m in rx.finditer(text):
            before = text[max(0, m.start() - 25): m.end()]
            if _ONE_OFF.search(before):
                continue  # sign-on / relocation money is one-off, not yearly pay
            amt = _eur(to_number(m.group("n")), _norm_cur(m.group("c")) or "EUR", fx)
            if 500 <= amt <= 200_000:
                return amt, amt, f"+{_fmt(amt)} bonus"
    return 0.0, 0.0, ""


HOLIDAY_PAY_COUNTRIES = {"NL"}   # vakantiegeld is a Dutch convention; elsewhere holiday pay is part of the salary


def parse_pay(text: str, cfg: Optional[dict] = None, country: Optional[str] = None) -> Optional[Pay]:
    """Best salary figure found in ``text`` as yearly EUR-equivalent, or None.
    ``country`` (ISO code of the job) decides whether Dutch-style holiday pay is added to monthly salaries."""
    if not text:
        return None
    s_cfg = (cfg or {}).get("search", {})
    vac_pct = float(s_cfg.get("vacation_allowance_pct", 8))
    if country is not None and country not in HOLIDAY_PAY_COUNTRIES:
        vac_pct = 0.0
    add_bonus = bool(s_cfg.get("add_bonus", True))
    fx = money.fx_table(cfg)
    text = text.replace("\xa0", " ")

    cands: list[tuple[int, int, Pay]] = []   # (score, hi, pay)
    taken: list[tuple[int, int]] = []        # spans already used by a range, so singles don't double-count

    def consider(m, lo_s, hi_s, k_lo, k_hi, cur_tok, is_range):
        start, end = m.start(), m.end()
        try:
            lo, hi = to_number(lo_s), to_number(hi_s)
        except ValueError:
            return
        if k_hi and not k_lo and lo < 1000:
            lo *= 1000                      # "€90 - 110k": the k belongs to both ends
        if k_lo:
            lo *= 1000
        if k_hi:
            hi *= 1000
        if hi < lo:
            return
        cur = _norm_cur(cur_tok) or "EUR"
        if cur not in fx or fx[cur] <= 0:
            return
        before = text[max(0, start - 40): start]
        after = text[end: end + 60]
        explicit = _period(text[start:end] + " " + after, before)
        near = text[max(0, start - 35): end + 50]
        if _BONUS_NEAR.search(text[max(0, start - 22): start]) and not _SALARY_WORDS.search(text[max(0, start - 22): start]):
            return                           # "bonus of €5000", "relocation budget €3.000": not the salary
        context = bool(_SALARY_WORDS.search(near))
        assumed = False
        period = explicit
        if k_lo or k_hi:
            period = period or "year"
        if period is None:                   # no period word at all
            if hi < 12_000 and (is_range or context):
                period, assumed = "month", True      # nobody earns €5.000 a YEAR: read as monthly
            elif hi >= 25_000:
                period = "year"
            else:
                return
        if period in ("hour", "day", "week"):
            return
        notes = []
        if period == "month":
            vac = vac_pct
            included = bool(_INCLUDED.search(text[max(0, start - 60): end + 120]))
            if included:
                vac = 0.0
            base_lo, base_hi = lo * 12, hi * 12
            lo_y, hi_y = base_lo * (1 + vac / 100), base_hi * (1 + vac / 100)
            notes.append(f"{_rng(lo, hi, cur)}/month x12")
            if vac:
                notes.append(f"+{vac:g}% holiday pay")
            elif included:
                notes.append("holiday pay already included")
            thirteenth = bool(_THIRTEENTH.search(text))
            if thirteenth and add_bonus:
                lo_y += lo; hi_y += hi
                notes.append("+13th month")
        else:
            base_lo, base_hi = lo, hi
            lo_y, hi_y = lo, hi
            if re.search(r"excl(?:usief|usive|\.)?\s*(?:\d+\s*%\s*)?(?:vakantie(?:geld|toeslag)|holiday)|\+\s*8\s*%\s*(?:vakantie|holiday)", text[max(0, start - 60): end + 120], re.I) and vac_pct:
                lo_y *= 1 + vac_pct / 100; hi_y *= 1 + vac_pct / 100
                notes.append(f"stated yearly +{vac_pct:g}% holiday pay")
        if add_bonus:
            blo, bhi, bnote = _bonus(text, lo_y, hi_y, None, fx)
            if bnote:
                lo_y += blo; hi_y += bhi; notes.append(bnote)
        lo_e, hi_e = _eur(lo_y, cur, fx), _eur(hi_y, cur, fx)
        if cur != "EUR":
            notes.append(f"{cur}→EUR at ~{fx[cur]:g}")
        if not (25_000 <= lo_e <= 600_000 and lo_e <= hi_e <= 800_000):
            return
        stated = _rng(lo, hi, cur)
        label = {"month": "/month", "year": "/year"}[period]
        note = f"Stated {stated}{label}"
        if period == "month" or len(notes) > 0:
            note += f" → ≈ {_rng(lo_e, hi_e)}/year" + (f" ({', '.join(notes)})" if notes else "")
        if assumed:
            note += " [no period given: read as monthly]"
        score = (2 if context else 0) + (1 if explicit else 0) + (1 if is_range else 0)
        cands.append((score, int(hi_e), Pay(int(round(lo_e)), int(round(hi_e)), period, cur, note, assumed)))
        taken.append((start, end))

    for m in _RANGE.finditer(text):
        if not any(m.group(g) for g in ("c1", "c1b", "c2", "c2b")):
            continue
        cur_tok = m.group("c1") or m.group("c1b") or m.group("c2") or m.group("c2b")
        consider(m, m.group("n1"), m.group("n2"), bool(m.group("k1")), bool(m.group("k2")), cur_tok, True)
    for m in _SINGLE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        n = m.group("n") or m.group("n_")
        k = bool(m.group("k") or m.group("k_"))
        consider(m, n, n, k, k, m.group("c") or m.group("c_"), False)

    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return cands[0][2]


def monthly_to_yearly(monthly: float, cfg: Optional[dict] = None) -> float:
    """For structured feeds that give a monthly figure: x12 plus holiday pay."""
    vac = float(((cfg or {}).get("search") or {}).get("vacation_allowance_pct", 8))
    return monthly * 12 * (1 + vac / 100)
