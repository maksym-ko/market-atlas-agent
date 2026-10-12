"""Country groups resolved to ISO3 codes (never to aggregate codes)."""
from app import snapshot

EU27 = ["AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN", "IRL",
        "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE"]
G7 = ["CAN", "FRA", "DEU", "ITA", "JPN", "GBR", "USA"]
ALIASES = {"eu": EU27, "european union": EU27, "eu27": EU27, "eu-27": EU27, "g7": G7}
# common names that differ from the World Bank's ("Russian Federation", "Turkiye", "Viet Nam"...)
COUNTRY_ALIASES = {"russia": "RUS", "turkey": "TUR", "vietnam": "VNM", "south korea": "KOR", "korea": "KOR",
                   "north korea": "PRK", "usa": "USA", "us": "USA", "america": "USA", "uk": "GBR",
                   "britain": "GBR", "great britain": "GBR", "czech republic": "CZE", "slovakia": "SVK",
                   "iran": "IRN", "egypt": "EGY", "syria": "SYR", "laos": "LAO", "kyrgyzstan": "KGZ",
                   "venezuela": "VEN", "yemen": "YEM", "gambia": "GMB", "bahamas": "BHS"}


def resolve(group: str) -> list[str]:
    key = group.strip().lower()
    if key in ALIASES:
        return ALIASES[key]
    countries = snapshot.countries()
    if key in ("all", "world"):
        return [country.iso3 for country in countries]
    hits = [country.iso3 for country in countries if key in (country.region.lower(), country.income_level.lower())]
    if not hits:
        regions = sorted({country.region for country in countries}) + sorted(
            {country.income_level for country in countries}
        )
        raise ValueError(f"Unknown group {group!r}. Try EU, G7, all, or one of: {regions}")
    return hits


def to_iso3(items: list[str]) -> list[str]:
    """Map ISO3 codes, ISO2 codes or country names to ISO3. Unknown items are returned upper-cased,
    so check_countries still rejects them; nothing here loosens validation."""
    countries = snapshot.countries()
    lookup = {country.iso3: country.iso3 for country in countries}
    lookup.update({country.iso2: country.iso3 for country in countries if country.iso2})
    for country in countries:
        name = country.name.lower()
        lookup.setdefault(name, country.iso3)
        lookup.setdefault(name.split(",")[0].strip(), country.iso3)  # "Egypt, Arab Rep." -> "egypt"
    lookup.update(COUNTRY_ALIASES)
    out = []
    for item in items:
        key = str(item).strip()
        out.append(lookup.get(key.upper()) or lookup.get(key.lower().removeprefix("the ")) or key.upper())
    return out
