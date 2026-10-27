"""Schmaler Client für die eBay Browse API (nur lesend)."""
import base64
import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.ebay.com"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayClient:
    def __init__(self, client_id, client_secret, marketplace="EBAY_DE"):
        # Beim Kopieren in die Secrets rutschen gern Leerzeichen oder Zeilenumbrüche mit.
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.marketplace = marketplace
        self.calls = 0
        self._token = None
        self._token_expires = 0

    def _auth_header(self):
        if not self._token or time.time() > self._token_expires - 60:
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            r = requests.post(
                f"{API}/identity/v1/oauth2/token",
                headers={"Authorization": f"Basic {basic}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": SCOPE},
                timeout=30,
            )
            if r.status_code == 401:
                raise RuntimeError(
                    "eBay lehnt die Keys ab (401). Prüfen: Production-Keys statt Sandbox (App ID enthält 'PRD'), "
                    "App ID als EBAY_CLIENT_ID, Cert ID als EBAY_CLIENT_SECRET, Keyset aktiviert. "
                    f"Antwort von eBay: {r.text[:300]}")
            r.raise_for_status()
            body = r.json()
            self._token = body["access_token"]
            self._token_expires = time.time() + body["expires_in"]
        return {"Authorization": f"Bearer {self._token}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace}

    def _get(self, path, params=None):
        self.calls += 1
        r = requests.get(f"{API}{path}", headers=self._auth_header(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def search(self, *, keywords="", category_ids=(), filters=(), sort=None, limit=200, max_items=1000):
        """Liefert itemSummaries, blättert bis max_items."""
        params = {"limit": min(limit, 200), "filter": ",".join(filters)}
        if keywords:
            params["q"] = keywords
        if category_ids:
            params["category_ids"] = ",".join(category_ids)
        if sort:
            params["sort"] = sort
        items, offset = [], 0
        while offset < max_items:
            params["offset"] = offset
            page = self._get("/buy/browse/v1/item_summary/search", params)
            batch = page.get("itemSummaries", [])
            items.extend(batch)
            offset += len(batch)
            if not batch or offset >= page.get("total", 0):
                break
        return items[:max_items]

    def get_item(self, item_id):
        return self._get(f"/buy/browse/v1/item/{item_id}")


def end_window_filter(hours, now=None):
    now = now or datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return f"itemEndDate:[{now.strftime(fmt)}..{(now + timedelta(hours=hours)).strftime(fmt)}]"
