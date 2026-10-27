"""Sucht Kategorie-IDs im eBay-Kategoriebaum.

Aufruf: python -m esnapper.categories Werkzeug Heimwerker Fahrzeuge
"""
import os
import sys

from .ebay import EbayClient


def walk(node, path=(), depth=0):
    cat = node["category"]
    path = path + (cat["categoryName"],)
    yield depth, cat["categoryId"], path
    for child in node.get("childCategoryTreeNodes", []):
        yield from walk(child, path, depth + 1)


def main(queries, max_depth=3):
    client = EbayClient(os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"])
    tree_id = client._get("/commerce/taxonomy/v1/get_default_category_tree_id",
                          {"marketplace_id": client.marketplace})["categoryTreeId"]
    tree = client._get(f"/commerce/taxonomy/v1/category_tree/{tree_id}")
    nodes = list(walk(tree["rootCategoryNode"]))
    for q in queries:
        print(f"\n== {q} ==")
        for depth, cat_id, path in nodes:
            if 1 <= depth <= max_depth and q.lower() in path[-1].lower():
                print(f"{cat_id:>8}  {' > '.join(path[1:])}")


if __name__ == "__main__":
    main(sys.argv[1:])
