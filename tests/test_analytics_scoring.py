import pandas as pd

from app import analytics, groups, indicators, scoring


def test_metrics():
    observations = pd.DataFrame({"iso3": ["A"] * 5 + ["B"] * 5, "year": list(range(2019, 2024)) * 2,
                       "value": [1, 2, 3, 4, 5, 10, 10, 10, 10, 10]})
    averages = analytics.metric(observations, "avg", 5).set_index("iso3")
    assert averages.loc["A", "value"] == 3 and (averages.loc["A", "y0"], averages.loc["A", "y1"]) == (2019, 2023)
    assert analytics.metric(observations, "change", 5).set_index("iso3").loc["A", "value"] == 4
    assert analytics.metric(observations, "latest", 5).set_index("iso3").loc["B", "value"] == 10


def test_better_than_pct_direction():
    values = pd.Series([1.0, 2.0, 3.0], index=["a", "b", "c"])
    assert analytics.better_than_pct(values, True).tolist() == [0, 50, 100]
    assert analytics.better_than_pct(values, False).tolist() == [100, 50, 0]


def test_scores_rank_and_sentences():
    scores = scoring.all_scores()
    assert list(scores.index[:4]) == ["AAA", "BBB", "CCC", "DDD"]
    assert "ZZZ" not in scores.index  # only 2 of 4 signals
    alpha = scoring.explain("AAA", scores)
    assert alpha["score"] == 100 and alpha["rank"] == 1
    assert alpha["signals"][3]["sentence"].startswith("inflation averaged 2.0% (2019–2023), more stable than 100%")
    assert scoring.explain("ZZZ", scores)["note"] == "not enough data"
    assert "−1.0%" in scoring.explain("DDD", scores)["signals"][0]["sentence"]


def test_groups_and_search():
    assert len(groups.resolve("EU")) == 27
    assert set(groups.resolve("high income")) == {"AAA", "BBB", "CCC", "DDD", "ZZZ"}
    assert indicators.search("forest area % of land")[0]["id"] == "AG.LND.FRST.ZS"
    codes = [result["id"] for result in indicators.search("access to electricity rural")]
    assert "EG.ELC.ACCS.ZS" in codes and "EG.ELC.ACCS.RU.ZS" in codes


def test_country_names_and_iso2_resolve_to_iso3():
    assert groups.to_iso3(["AAA", "bb", "gamma", "Delta", "the Zeta", "Russia"]) == \
        ["AAA", "BBB", "CCC", "DDD", "ZZZ", "RUS"]
    assert groups.to_iso3(["../etc", "Nowhere"]) == ["../ETC", "NOWHERE"]  # still rejected by check_countries
