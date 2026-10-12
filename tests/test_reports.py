"""Saved reports: Markdown export rebuilt from stored data."""
from app import db, reports


def test_report_markdown_is_built_from_stored_data():
    ref = db.put_ref("series", {"indicator": "FP.CPI.TOTL.ZG", "indicator_name": "Inflation",
                                "values": {"AAA": {"2020": 1.5, "2023": 2.5}}})
    report_id = db.save_report("PL vs UA", "Short summary", [ref])["report_id"]
    markdown = reports.to_markdown(report_id)
    assert markdown.startswith("# PL vs UA") and "| Alpha | 1.5 (2020) | 2.5 (2023) |" in markdown
    assert "data.worldbank.org/indicator/FP.CPI.TOTL.ZG" in markdown
