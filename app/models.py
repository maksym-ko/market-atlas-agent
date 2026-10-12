import re

from pydantic import BaseModel

ISO3 = re.compile(r"^[A-Z]{3}$")
INDICATOR = re.compile(r"^[A-Za-z0-9._]{2,40}$")
MAX_COUNTRIES = 60


def check_indicator(code: str) -> str:
    if not INDICATOR.fullmatch(code or ""):
        raise ValueError(f"Invalid indicator code {code!r}")
    return code.upper()


def check_countries(codes: list[str]) -> list[str]:
    codes = [code.strip().upper() for code in codes]
    invalid = [code for code in codes if not ISO3.fullmatch(code)]
    if invalid:
        raise ValueError(f"Invalid ISO3 country codes: {invalid}")
    if not codes or len(codes) > MAX_COUNTRIES:
        raise ValueError(f"Give between 1 and {MAX_COUNTRIES} countries")
    return list(dict.fromkeys(codes))


def check_years(year_from: int | None, year_to: int | None) -> tuple[int, int]:
    first_year, last_year = year_from or 1960, year_to or 2100
    if not (1960 <= first_year <= last_year <= 2100):
        raise ValueError("Years must be between 1960 and 2100, from <= to")
    return first_year, last_year


class Country(BaseModel):
    iso3: str
    iso2: str = ""
    name: str
    region: str
    income_level: str


class Observation(BaseModel):
    indicator: str
    iso3: str
    year: int
    value: float | None


class Provenance(BaseModel):
    indicators: list[str]
    countries: list[str]
    years: tuple[int, int]
    source: str  # "snapshot <date>" or "live API"
    urls: list[str]
