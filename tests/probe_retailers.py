"""Opt-in live browser search: python tests/probe_retailers.py [search terms]."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sourcing import search_all_retailers

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    query = " ".join(sys.argv[1:]) or "Adirondack chair"
    results = search_all_retailers([query])[query]
    print(f"{len(results)} matched products")
    for product in results:
        print(product["retailer"], product["price"], product["name"], product["url"])
