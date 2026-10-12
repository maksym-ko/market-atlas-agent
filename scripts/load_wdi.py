"""Download the full World Development Indicators dataset and load it into data/wdi.db (~9M values).

    uv run python -m scripts.load_wdi            # download (283 MB, skipped if present) + load
    uv run python -m scripts.load_wdi --refresh  # download again
"""
import sys

import httpx

from app import config, warehouse

URL = "https://databank.worldbank.org/data/download/WDI_CSV.zip"  # fixed: official bulk download


def download(dest) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    with httpx.stream("GET", URL, follow_redirects=True, timeout=httpx.Timeout(60, connect=10)) as response:
        response.raise_for_status()
        if "databank.worldbank.org" not in str(response.url):
            raise RuntimeError(f"Unexpected redirect to {response.url}")
        with open(part, "wb") as out_file:
            for chunk in response.iter_bytes(1 << 20):
                out_file.write(chunk)
    part.replace(dest)


def main():
    zip_path = config.data_dir() / "raw" / "WDI_CSV.zip"
    if "--refresh" in sys.argv or not zip_path.exists():
        print(f"Downloading {URL} …")
        download(zip_path)
    warehouse.load(zip_path)


if __name__ == "__main__":
    main()
