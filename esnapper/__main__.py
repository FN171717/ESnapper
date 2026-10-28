"""Ein Lauf: suchen, bewerten, filtern, benachrichtigen, Übersicht schreiben."""
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import geo, score
from .ebay import EbayClient, end_window_filter
from .notify import format_hits, send_notification
from .render import render

STATE_FILE = Path("data/state.json")
LOCAL_TZ = ZoneInfo("Europe/Berlin")
ERROR_ALERT_EVERY = timedelta(hours=6)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"items": {}, "last_error_alert": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def find_reference(client, item, search, delivery_country):
    """Sofortkaufpreis der Auktion, sonst Median vergleichbarer Sofortkauf-Angebote."""
    bin_price = score.buy_it_now_price(item)
    if bin_price:
        return bin_price, "Sofortkauf", 1
    keywords = score.comparison_keywords(item.get("title", ""))
    if not keywords:
        return None, "", 0
    filters = ["buyingOptions:{FIXED_PRICE}", f"deliveryCountry:{delivery_country}"]
    if item.get("conditionId"):
        filters.append(f"conditionIds:{{{item['conditionId']}}}")
    comps = client.search(keywords=keywords, category_ids=search.get("category_ids", []),
                          filters=filters, limit=30, max_items=30)
    prices = [score.money(c.get("price")) + (score.shipping_cost(c) or 0)
              for c in comps if score.money(c.get("price"))]
    ref = score.robust_median(prices)
    return ref, f"Median aus {len(prices)} Sofortkäufen", len(prices)


def make_locator(config):
    """Nur laden, wenn eine Suche einen Umkreis nutzt. Fehlt die PLZ-Datei, läuft es ohne Umkreis weiter."""
    if not config.get("home_postal_code") or not any(s.get("max_distance_km") for s in config["searches"]):
        return None
    try:
        return geo.Locator(geo.load_postal_codes())
    except Exception as exc:
        print(f"Warnung: PLZ-Daten nicht verfügbar, Umkreisfilter aus ({exc})")
        return None


def too_far(item, search, config, locator):
    """Umkreis gilt für Abhol-Suchen (pickup) immer, sonst nur für Artikel ohne Versand."""
    limit = search.get("max_distance_km")
    if not limit or locator is None:
        return False
    if not search.get("pickup") and score.shipping_cost(item) is not None:
        return False
    km = locator.distance_km(config["home_postal_code"], item.get("itemLocation", {}).get("postalCode"))
    return km is not None and km > limit


def run(config):
    missing = [v for v in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET") if not os.environ.get(v, "").strip()]
    if missing:
        raise RuntimeError(f"Secret fehlt oder ist leer: {', '.join(missing)}. "
                           "Anlegen unter Settings → Secrets and variables → Actions → Repository secrets.")
    client = EbayClient(os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"],
                        config.get("marketplace", "EBAY_DE"))
    country = config.get("delivery_country", "DE")
    state = load_state()
    known = state["items"]
    now = datetime.now(timezone.utc)
    budget = config.get("max_new_items_per_run", 25)
    rows, new_hits = [], []
    locator = make_locator(config)

    for search in config["searches"]:
        filters = ["buyingOptions:{AUCTION}", end_window_filter(search.get("ends_within_hours", 6), now),
                   # Fahrzeuge werden meist nur abgeholt, dort zählt der Standort statt der Lieferung.
                   f"itemLocationCountry:{country}" if search.get("pickup") else f"deliveryCountry:{country}"]
        if search.get("conditions"):
            filters.append("conditions:{" + "|".join(search["conditions"]) + "}")
        # Die Browse API nimmt nur eine Kategorie pro Suche, daher je Kategorie einzeln abfragen.
        # Das Zeitfenster prüfen wir zusätzlich selbst: eBay hat den itemEndDate-Filter nicht
        # zuverlässig angewendet (eine Auktion mit 3 Tagen Restzeit kam durch).
        ends_before = (now + timedelta(hours=search.get("ends_within_hours", 6))).strftime("%Y-%m-%dT%H:%M:%SZ")
        items, seen_ids = [], set()
        for cat_id in search.get("category_ids") or [None]:
            calls_before = client.calls
            found = client.search(keywords=search.get("keywords", ""), category_ids=[cat_id] if cat_id else [],
                                  filters=filters, sort="endingSoonest", max_items=search.get("max_auctions", 3000),
                                  ends_before=ends_before)
            print(f"  Kategorie {cat_id}: {len(found)} Auktionen bis {ends_before}, {client.calls - calls_before} Aufrufe")
            for i in found:
                if i["itemId"] not in seen_ids:
                    seen_ids.add(i["itemId"])
                    items.append(i)
        # "sofortkauf": nur Auktionen mit Sofortkauf-Option, Gebot direkt gegen Sofortkaufpreis.
        # "vergleich": zusätzlich Auktionen ohne Sofortkauf über Vergleichsangebote bewerten.
        compare = search.get("compare", "sofortkauf")
        if compare == "sofortkauf":
            items = [i for i in items if score.buy_it_now_price(i)]
        print(f"[{search['name']}] {len(items)} Auktionen im Zeitfenster (Vergleich: {compare})")

        for item in items:
            ok, _ = score.passes_filters(item, search)
            if not ok or too_far(item, search, config, locator):
                continue
            item_id = item["itemId"]
            entry = known.get(item_id)
            if entry is None and compare == "sofortkauf":
                entry = known[item_id] = {"reference": score.buy_it_now_price(item), "reference_source": "Sofortkauf",
                                          "end": item["itemEndDate"], "reserve_ok": None, "notified": False}
            if entry is None:
                if budget <= 0:
                    continue
                budget -= 1
                ref, src, n = find_reference(client, item, search, country)
                entry = known[item_id] = {"reference": ref, "reference_source": src, "end": item["itemEndDate"],
                                          "reserve_ok": None, "notified": False}
            if not entry["reference"]:
                continue

            bid, ship = score.current_bid(item), score.shipping_cost(item)
            # Beim Sofortkaufpreis desselben Artikels fällt der Versand auf beiden Seiten an.
            same_item = entry["reference_source"] == "Sofortkauf"
            result = score.evaluate(bid, 0 if same_item else ship, entry["reference"], search)
            is_hit = result["is_hit"]

            # Mindestpreis nur bei Kandidaten prüfen, das spart API-Aufrufe.
            if is_hit and entry["reserve_ok"] is not True:
                detail = client.get_item(item_id)
                entry["reserve_ok"] = detail.get("reservePriceMet", True) is not False
            if is_hit and entry["reserve_ok"] is False:
                is_hit = False

            row = {
                "id": item_id, "title": item.get("title", ""), "url": item.get("itemWebUrl", ""),
                "image": item.get("image", {}).get("imageUrl"), "bid": bid, "bid_count": item.get("bidCount", 0),
                "shipping": ship, "reference": entry["reference"], "reference_source": entry["reference_source"],
                "saving": result["saving"], "difference": result["difference"], "rating": result["rating"],
                "end": item["itemEndDate"], "is_hit": is_hit, "search": search["name"],
                "ends_local": parse_time(item["itemEndDate"]).astimezone(LOCAL_TZ).strftime("%d.%m. %H:%M"),
            }
            rows.append(row)
            # Zu knapp vor Ende lohnt keine Meldung mehr, man schafft das Bieten nicht.
            minutes_left = (parse_time(item["itemEndDate"]) - now).total_seconds() / 60
            if is_hit and not entry["notified"] and minutes_left >= search.get("min_minutes_left", 15):
                new_hits.append(row)
                entry["notified"] = True

    if new_hits:
        new_hits.sort(key=lambda h: h["rating"], reverse=True)
        send_notification(format_hits(new_hits))

    # Beendete Auktionen vergessen.
    state["items"] = {k: v for k, v in known.items() if parse_time(v["end"]) > now - timedelta(hours=1)}
    save_state(state)
    render(rows, now.isoformat())
    print(f"{len(rows)} bewertet, {sum(r['is_hit'] for r in rows)} Treffer, "
          f"{len(new_hits)} neu gemeldet, {client.calls} API-Aufrufe")


def alert_error(exc_text):
    state = load_state()
    last = state.get("last_error_alert")
    now = datetime.now(timezone.utc)
    if last and now - parse_time(last) < ERROR_ALERT_EVERY:
        return
    try:
        send_notification("⚠️ ESnapper-Lauf fehlgeschlagen:\n" + exc_text[-800:])
        state["last_error_alert"] = now.isoformat()
        save_state(state)
    except Exception:
        traceback.print_exc()


def main():
    config = yaml.safe_load(Path(os.environ.get("ESNAPPER_CONFIG", "config.yaml")).read_text(encoding="utf-8"))
    try:
        run(config)
    except Exception:
        text = traceback.format_exc()
        print(text, file=sys.stderr)
        alert_error(text)
        sys.exit(1)


if __name__ == "__main__":
    main()
