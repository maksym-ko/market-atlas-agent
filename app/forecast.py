"""⭐ ARIMA forecasts and the Taylor rule. Deterministic statsmodels code; the LLM only explains results."""
import csv
import itertools
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.filters.hp_filter import hpfilter

from app import config, db, snapshot, wb
from app.models import check_countries, check_indicator

MIN_POINTS = 15


def _annual(indicator: str, iso3: str, year_from: int = 1990) -> pd.Series:
    observations = [
        observation for observation in wb.series(indicator, [iso3], year_from, 2100) if observation.value is not None
    ]
    series = pd.Series({observation.year: observation.value for observation in observations}).sort_index()
    return series


def arima(indicator: str, country: str, horizon: int = 10, p: int | None = None, d: int | None = None,
          q: int | None = None) -> dict:
    code, (iso3,) = check_indicator(indicator), check_countries([country])[:1]
    if not 1 <= horizon <= 20:
        raise ValueError("horizon must be between 1 and 20 years")
    series = _annual(code, iso3)
    if len(series) < MIN_POINTS:
        raise ValueError(f"Only {len(series)} yearly points for {code} in {iso3}; need at least {MIN_POINTS}")
    use_log = bool((series > 0).all())  # model growth for positive series (GDP per capita), like most macro forecasts
    values = np.log(series.values) if use_log else series.values

    if None in (p, d, q):  # pick the order by AIC over a small grid
        best = None
        for candidate_order in itertools.product(range(3), range(1, 3), range(3)):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    aic = ARIMA(values, order=candidate_order).fit().aic
                except Exception:  # some orders don't converge; skip them
                    continue
            if best is None or aic < best[1]:
                best = (candidate_order, aic)
        order = best[0]
    else:
        if not all(0 <= value <= 3 for value in (p, d, q)):
            raise ValueError("p, d and q must be between 0 and 3")
        order = (p, d, q)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = ARIMA(values, order=order).fit()
    prediction = fitted.get_forecast(horizon)
    mean, range_95, range_80 = (
        prediction.predicted_mean,
        prediction.conf_int(alpha=0.05),
        prediction.conf_int(alpha=0.20),
    )
    to_original_scale = np.exp if use_log else (lambda value: value)
    years = list(range(int(series.index[-1]) + 1, int(series.index[-1]) + 1 + horizon))
    rows = [
        {
            "year": year,
            "mean": float(to_original_scale(mean[step])),
            "lo95": float(to_original_scale(range_95[step][0])),
            "hi95": float(to_original_scale(range_95[step][1])),
            "lo80": float(to_original_scale(range_80[step][0])),
            "hi80": float(to_original_scale(range_80[step][1])),
        }
        for step, year in enumerate(years)
    ]
    name = snapshot.names().get(iso3, iso3)
    ref = db.put_ref(
        "forecast",
        {
            "indicator": code,
            "iso3": iso3,
            "name": name,
            "history": {str(year_key): float(value) for year_key, value in series.items()},
            "forecast": rows,
        },
    )
    highlights = [rows[0], rows[min(4, horizon - 1)], rows[-1]]
    return {
        "data_ref": ref, "indicator": code, "country": iso3,
        "model": f"ARIMA{order}" + (" on log values" if use_log else ""), "aic": round(float(fitted.aic), 2),
        "training_years": [int(series.index[0]), int(series.index[-1])], "points": len(series),
        "last_actual": [int(series.index[-1]), round(float(series.iloc[-1]), 2)],
        "forecast": [{"year": row["year"], "value": round(row["mean"], 2),
                      "range_95": [round(row["lo95"], 2), round(row["hi95"], 2)]} for row in highlights],
        "caveat": f"Only {len(series)} annual points; wide intervals are expected. A statistical extrapolation, "
                  "not an economic forecast: it can't foresee wars, crises or reforms.",
        "source": wb.source_url(code, [iso3]),
    }


def _policy_rates(iso3: str) -> dict[int, float]:
    """Optional user-supplied actual policy rates: data/policy_rates/<ISO3>.csv with columns year,rate."""
    path = config.data_dir() / "policy_rates" / f"{iso3}.csv"
    if not path.exists():
        return {}
    with path.open() as csv_file:
        return {int(row["year"]): float(row["rate"]) for row in csv.DictReader(csv_file)}


def taylor(country: str = "UKR", years: int = 10, r_star: float = 2.0, pi_target: float = 5.0,
           a_pi: float = 0.5, a_y: float = 0.5, hp_lambda: float = 100.0) -> dict:
    (iso3,) = check_countries([country])[:1]
    if not 3 <= years <= 30:
        raise ValueError("years must be between 3 and 30")
    if not (-5 <= r_star <= 10 and 0 <= pi_target <= 20 and 0 <= a_pi <= 3 and 0 <= a_y <= 3
            and 1 <= hp_lambda <= 100_000):
        raise ValueError("Assumptions out of range")
    inflation = _annual("FP.CPI.TOTL.ZG", iso3)
    gdp = _annual("NY.GDP.MKTP.KD", iso3)  # real GDP, constant US$
    if len(gdp) < MIN_POINTS:
        raise ValueError(f"Not enough real GDP data for {iso3}")
    gdp_cycle, _ = hpfilter(np.log(gdp), lamb=hp_lambda)  # output gap over the full history, not just the window
    output_gap = gdp_cycle * 100
    common_years = sorted(set(inflation.index) & set(output_gap.index))[-years:]
    actual_rates = _policy_rates(iso3)
    rows = []
    for year in common_years:
        inflation_pct, gap_pct = float(inflation[year]), float(output_gap[year])
        implied = r_star + inflation_pct + a_pi * (inflation_pct - pi_target) + a_y * gap_pct
        rows.append({"year": int(year), "inflation": round(inflation_pct, 2), "output_gap": round(gap_pct, 2),
                     "implied_rate": round(implied, 2), "actual_rate": actual_rates.get(int(year))})
    name = snapshot.names().get(iso3, iso3)
    assumptions = {"r_star": r_star, "pi_target": pi_target, "a_pi": a_pi, "a_y": a_y, "hp_lambda": hp_lambda}
    ref = db.put_ref("taylor", {"iso3": iso3, "name": name, "rows": rows, "assumptions": assumptions})
    return {
        "data_ref": ref, "country": iso3, "formula": "i = r* + π + a_π·(π − π*) + a_y·(output gap)",
        "assumptions": assumptions, "rows": rows,
        "actual_rates": "loaded from data/policy_rates" if actual_rates else
                        f"not loaded: add data/policy_rates/{iso3}.csv (year,rate) with official central-bank "
                        "rates to compare; the World Bank doesn't publish policy rates",
        "caveat": "Annual data (central banks decide monthly); output gap from an HP filter is revised as new "
                  "data arrives; structural breaks (e.g. 2014-2015, 2022 for Ukraine) distort the rule.",
        "sources": [wb.source_url("FP.CPI.TOTL.ZG", [iso3]), wb.source_url("NY.GDP.MKTP.KD", [iso3])],
    }
