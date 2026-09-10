"""Opt-in live check: python tests/probe_home_depot.py (no purchases)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from sourcing import search_product

if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(locale="en-US")
            print(search_product(page, "boxwood shrub"))
            print("Page title:", page.title())
        finally:
            browser.close()
