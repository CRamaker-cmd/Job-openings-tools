"""Which countries can be searched, and how to recognise a job's country from its location text.

Keywords are place names (country, main cities, local spellings). Two-letter codes are NOT used as keywords because they
collide with ordinary words ("de", "it", "be"), except the unambiguous "nl" and "uk".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .money import to_eur


@dataclass(frozen=True)
class Country:
    code: str            # ISO 3166-1 alpha-2, used as the key everywhere
    name: str
    iso3: str            # Amazon / Uber career-site APIs
    currency: str
    flag: str
    keywords: tuple[str, ...]
    linkedin: str = ""   # location string for LinkedIn's search

    @property
    def linkedin_location(self) -> str:
        return self.linkedin or self.name


def _c(code, name, iso3, cur, flag, kws, linkedin=""):
    return Country(code, name, iso3, cur, flag, tuple(kws), linkedin)


COUNTRIES: dict[str, Country] = {c.code: c for c in [
    _c("NL", "Netherlands", "NLD", "EUR", "🇳🇱", ["netherlands", "nederland", "the netherlands", "amsterdam", "rotterdam", "utrecht",
       "eindhoven", "the hague", "den haag", "almere", "amstelveen", "delft", "leiden", "haarlem", "hilversum", "schiphol",
       "groningen", "tilburg", "breda", "nijmegen", "arnhem", "maastricht", "enschede", "amersfoort", "zwolle", "nl"]),
    _c("BE", "Belgium", "BEL", "EUR", "🇧🇪", ["belgium", "belgië", "belgie", "belgique", "brussels", "brussel", "bruxelles", "antwerp",
       "antwerpen", "ghent", "gent", "leuven", "liège", "liege", "bruges", "brugge", "mechelen", "hasselt"]),
    _c("DE", "Germany", "DEU", "EUR", "🇩🇪", ["germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne",
       "köln", "stuttgart", "düsseldorf", "dusseldorf", "leipzig", "dresden", "nuremberg", "nürnberg", "hannover", "bremen",
       "karlsruhe", "bonn"]),
    _c("LU", "Luxembourg", "LUX", "EUR", "🇱🇺", ["luxembourg", "luxemburg", "esch-sur-alzette"]),
    _c("IE", "Ireland", "IRL", "EUR", "🇮🇪", ["ireland", "dublin", "cork", "galway", "limerick"]),
    _c("FR", "France", "FRA", "EUR", "🇫🇷", ["france", "paris", "lyon", "toulouse", "marseille", "lille", "nantes", "bordeaux", "nice"]),
    _c("ES", "Spain", "ESP", "EUR", "🇪🇸", ["spain", "españa", "espana", "madrid", "barcelona", "valencia", "seville", "sevilla", "málaga", "malaga"]),
    _c("PT", "Portugal", "PRT", "EUR", "🇵🇹", ["portugal", "lisbon", "lisboa", "porto", "braga"]),
    _c("IT", "Italy", "ITA", "EUR", "🇮🇹", ["italy", "italia", "milan", "milano", "rome", "roma", "turin", "torino", "bologna"]),
    _c("AT", "Austria", "AUT", "EUR", "🇦🇹", ["austria", "österreich", "osterreich", "vienna", "wien", "graz", "linz", "salzburg"]),
    _c("FI", "Finland", "FIN", "EUR", "🇫🇮", ["finland", "suomi", "helsinki", "espoo", "tampere", "oulu"]),
    _c("GB", "United Kingdom", "GBR", "GBP", "🇬🇧", ["united kingdom", "uk", "england", "scotland", "wales", "northern ireland", "london",
       "manchester", "edinburgh", "glasgow", "leeds"]),
    _c("CH", "Switzerland", "CHE", "CHF", "🇨🇭", ["switzerland", "schweiz", "suisse", "zurich", "zürich", "geneva", "genève", "basel", "bern", "lausanne"]),
    _c("SE", "Sweden", "SWE", "SEK", "🇸🇪", ["sweden", "sverige", "stockholm", "gothenburg", "göteborg", "malmö", "malmo", "uppsala"]),
    _c("DK", "Denmark", "DNK", "DKK", "🇩🇰", ["denmark", "danmark", "copenhagen", "københavn", "aarhus", "odense"]),
    _c("NO", "Norway", "NOR", "NOK", "🇳🇴", ["norway", "norge", "oslo", "bergen", "trondheim", "stavanger"]),
    _c("PL", "Poland", "POL", "PLN", "🇵🇱", ["poland", "polska", "warsaw", "warszawa", "kraków", "krakow", "wrocław", "wroclaw", "gdańsk", "gdansk", "poznań"]),
]}
DEFAULT_COUNTRIES = ["NL"]


def _word(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])", re.I)


_PATTERNS: dict[str, list[re.Pattern]] = {c.code: [_word(k) for k in c.keywords] for c in COUNTRIES.values()}


def selected(cfg: Optional[dict]) -> list[Country]:
    codes = ((cfg or {}).get("search", {}).get("countries")) or DEFAULT_COUNTRIES
    return [COUNTRIES[c] for c in codes if c in COUNTRIES] or [COUNTRIES["NL"]]


def _matches(location: str, code: str) -> bool:
    return any(p.search(location) for p in _PATTERNS[code])


def in_selected_country(location: str, cfg: dict) -> bool:
    if any(_matches(location, c.code) for c in selected(cfg)):
        return True
    extra = cfg.get("search", {}).get("country_keywords") or []   # user-added extra location words
    return any(_word(k).search(location) for k in extra)


def detect_country(location: str, cfg: Optional[dict] = None) -> str:
    """Country code of a location text ('' when it can't be told, e.g. a plain 'Remote'). Selected countries win."""
    loc = location or ""
    for c in selected(cfg):
        if _matches(loc, c.code):
            return c.code
    for code in COUNTRIES:
        if _matches(loc, code):
            return code
    return ""


def currency_of(code: str) -> str:
    return COUNTRIES[code].currency if code in COUNTRIES else "EUR"


def min_salary_for(cfg: dict, code: str) -> int:
    """Minimum yearly pay for jobs in this country, as a EUR-equivalent so it can be compared with any posting.
    A per-country minimum is entered in that country's own currency; without one the general minimum (EUR) applies."""
    s = cfg["search"]
    by = s.get("min_salary_by_country") or {}
    if code in by:
        return round(to_eur(by[code], currency_of(code), cfg))
    return int(s["min_salary"])


def big_floor_for(cfg: dict, code: str) -> int:
    """The lower minimum for big companies in this country (EUR-equivalent). An explicit per-country value (local
    currency) wins; otherwise the general floor is scaled by how this country's minimum compares to the general one."""
    s = cfg["search"]
    own = min_salary_for(cfg, code)
    by = s.get("big_company_min_by_country") or {}
    if code in by:
        floor = to_eur(by[code], currency_of(code), cfg)
    else:
        base = s["min_salary"] or 1
        floor = s["big_company_min_salary"] * own / base
    return round(min(floor, own))


def keywords_for(cfg: dict) -> list[str]:
    """All place words that mean 'in one of the searched countries' (used by the browser scraper to spot locations)."""
    out: list[str] = []
    for c in selected(cfg):
        out += list(c.keywords)
    return out + list(cfg.get("search", {}).get("country_keywords") or [])
