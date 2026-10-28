from datetime import datetime, timedelta, timezone

import pytest

from esnapper import __main__ as app
from esnapper import score


def auction(item_id="1", title="Festool Kappsäge KS 120 REB", bid="100.00", ship="10.00",
            options=("AUCTION",), price=None, hours=2, feedback="99.5", condition_id="3000"):
    end = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    item = {
        "itemId": item_id, "title": title, "itemWebUrl": f"https://www.ebay.de/itm/{item_id}",
        "currentBidPrice": {"value": bid, "currency": "EUR"}, "bidCount": 3,
        "buyingOptions": list(options), "itemEndDate": end, "conditionId": condition_id,
        "shippingOptions": [{"shippingCost": {"value": ship, "currency": "EUR"}}] if ship else [],
        "seller": {"feedbackPercentage": feedback},
    }
    if price:
        item["price"] = {"value": price, "currency": "EUR"}
    return item


SEARCH = {"name": "Test", "category_ids": ["12576"], "min_saving": 0.3, "min_difference": 50, "min_price": 20, "max_price": 2000,
          "max_shipping": 50, "exclude_words": ["defekt"], "min_seller_feedback": 97}


def test_saving_includes_shipping():
    assert score.saving(60, 10, 100) == pytest.approx(0.3)
    assert score.saving(60, None, 100) == pytest.approx(0.4)
    assert score.saving(60, 10, None) is None


def test_buy_it_now_only_for_auctions_with_bin():
    assert score.buy_it_now_price(auction(options=("AUCTION", "FIXED_PRICE"), price="400.00")) == 400
    assert score.buy_it_now_price(auction(price="400.00")) is None


def test_robust_median_drops_outliers_and_needs_three():
    assert score.robust_median([100, 110]) is None
    assert score.robust_median([1, 100, 110, 120, 9999]) == 110


def test_comparison_keywords():
    assert score.comparison_keywords("NEU! Festool Kappsäge KS 120 REB mit OVP Top") == "festool kappsäge 120 reb"


@pytest.mark.parametrize("item,reason", [
    (auction(title="Kappsäge defekt"), "Ausschlusswort"),
    (auction(bid="5.00"), "Gebot zu niedrig"),
    (auction(ship="80.00"), "Versand zu teuer"),
    (auction(feedback="90.0"), "Verkäuferbewertung"),
])
def test_filters_reject(item, reason):
    ok, why = score.passes_filters(item, SEARCH)
    assert not ok and reason in why


def test_filters_accept_pickup_only():
    assert score.passes_filters(auction(ship=None), SEARCH) == (True, "")


class FakeClient:
    def __init__(self, auctions, comps, reserve_met):
        self.auctions, self.comps, self.reserve_met, self.calls = auctions, comps, reserve_met, 0

    def search(self, *, filters=(), **kw):
        self.calls += 1
        return self.comps if "buyingOptions:{FIXED_PRICE}" in filters else self.auctions

    def get_item(self, item_id):
        self.calls += 1
        met = self.reserve_met.get(item_id)
        return {} if met is None else {"reservePriceMet": met}


def test_full_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EBAY_CLIENT_ID", "x")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "y")
    sent = []
    monkeypatch.setattr(app, "send_notification", sent.append)
    comps = [{"price": {"value": v}, "shippingOptions": []} for v in ("300", "320", "340", "360")]
    auctions = [
        auction("cheap", bid="100.00"),                      # 110 vs 330 -> Treffer
        auction("reserve", bid="100.00"),                    # Treffer, aber Mindestpreis nicht erreicht
        auction("pricey", bid="300.00"),                     # kein Schnäppchen
        auction("bin", bid="50.00", options=("AUCTION", "FIXED_PRICE"), price="200.00"),  # 60 vs 200
    ]
    fake = FakeClient(auctions, comps, {"reserve": False})
    monkeypatch.setattr(app, "EbayClient", lambda *a, **k: fake)
    config = {"searches": [dict(SEARCH, compare="vergleich")]}

    app.run(config)
    page = (tmp_path / "site" / "index.html").read_text()
    assert "Festool" in page
    assert len(sent) == 1
    assert sent[0].count("ebay.de/itm/") == 2
    assert "itm/cheap" in sent[0] and "itm/bin" in sent[0]

    # Zweiter Lauf: nichts doppelt melden, keine neuen Vergleichssuchen.
    sent.clear()
    calls_before = fake.calls
    app.run(config)
    assert sent == []
    assert fake.calls - calls_before == 2  # Auktionssuche + erneute Mindestpreis-Prüfung


def test_notification_channels(monkeypatch):
    from esnapper import notify
    calls = []
    monkeypatch.setattr(notify, "send_ntfy", lambda topic, text: calls.append(("ntfy", topic)))
    monkeypatch.setattr(notify, "send_whatsapp", lambda phone, key, text: calls.append(("wa", phone)))
    for var in ("NTFY_TOPIC", "CALLMEBOT_PHONE", "CALLMEBOT_APIKEY"):
        monkeypatch.delenv(var, raising=False)
    assert notify.send_notification("x") is False

    monkeypatch.setenv("NTFY_TOPIC", "esnapper-test")
    assert notify.send_notification("x") is True
    assert calls == [("ntfy", "esnapper-test")]


@pytest.mark.parametrize("bid,ship,ref,hit", [
    (20000, 0, 22000, False),   # Auto: 2.000 € Differenz, aber nur 9 %
    (50, 0, 100, False),        # 50 %, aber nur 50 €
    (500, 20, 1000, True),      # 480 € und 48 %
    (700, 0, 1000, True),       # genau 300 € / 30 %
])
def test_hit_needs_euro_and_percent(bid, ship, ref, hit):
    search = {"min_difference": 200, "min_saving": 0.25}
    assert score.evaluate(bid, ship, ref, search)["is_hit"] is hit


def test_rating_prefers_big_and_safe_deals():
    search = {"min_difference": 0, "min_saving": 0}
    big = score.evaluate(600, 0, 1000, search)["rating"]     # 400 € × 40 %
    thin = score.evaluate(9000, 0, 10000, search)["rating"]  # 1.000 € × 10 %
    assert big > thin


def test_sofortkauf_mode_skips_auctions_without_bin(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EBAY_CLIENT_ID", "x")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "y")
    sent = []
    monkeypatch.setattr(app, "send_notification", sent.append)
    auctions = [
        auction("nobin", bid="30.00"),
        auction("bin", bid="30.00", ship="15.00", options=("AUCTION", "FIXED_PRICE"), price="400.00"),
    ]
    fake = FakeClient(auctions, comps=[], reserve_met={})
    monkeypatch.setattr(app, "EbayClient", lambda *a, **k: fake)
    app.run({"searches": [dict(SEARCH, compare="sofortkauf", min_difference=200, min_saving=0.9)]})
    assert len(sent) == 1 and "itm/bin" in sent[0] and "itm/nobin" not in sent[0]
    assert "370 €" in sent[0]  # 400 − 30, Versand fällt beim selben Artikel raus
    assert fake.calls == 2  # Auktionssuche + Mindestpreis-Prüfung, keine Vergleichssuche


def test_no_notification_shortly_before_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EBAY_CLIENT_ID", "x")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "y")
    sent = []
    monkeypatch.setattr(app, "send_notification", sent.append)
    late = auction("late", bid="10.00", options=("AUCTION", "FIXED_PRICE"), price="400.00", hours=0.1)
    monkeypatch.setattr(app, "EbayClient", lambda *a, **k: FakeClient([late], [], {}))
    app.run({"searches": [dict(SEARCH, compare="sofortkauf", min_difference=200, min_saving=0.9)]})
    assert sent == []


def test_geo_distance_with_masked_postal_code(tmp_path):
    from esnapper import geo
    f = tmp_path / "DE.txt"
    rows = [("25712", 54.08, 9.27), ("20095", 53.55, 10.00), ("20097", 53.55, 10.02), ("80331", 48.14, 11.57)]
    f.write_text("\n".join(f"DE\t{c}\tOrt\t\t\t\t\t\t\t{lat}\t{lon}\t4" for c, lat, lon in rows))
    loc = geo.Locator(geo.load_postal_codes(f))
    assert 60 < loc.distance_km("25712", "200**") < 90       # Hamburg
    assert 650 < loc.distance_km("25712", "80331") < 750     # München
    assert loc.distance_km("25712", "") is None


def test_too_far_only_for_pickup(monkeypatch):
    class FakeLocator:
        def distance_km(self, a, b):
            return 700
    cfg = {"home_postal_code": "25712"}
    search = {"max_distance_km": 400}
    shipped = auction(ship="10.00")
    pickup_only = auction(ship=None)
    assert app.too_far(shipped, search, cfg, FakeLocator()) is False
    assert app.too_far(pickup_only, search, cfg, FakeLocator()) is True
    assert app.too_far(shipped, dict(search, pickup=True), cfg, FakeLocator()) is True


def test_search_drops_items_outside_window_and_stops_paging():
    from esnapper.ebay import EbayClient
    pages = [
        {"total": 600, "itemSummaries": [{"itemId": "a", "itemEndDate": "2026-10-28T08:10:00.000Z"},
                                         {"itemId": "b", "itemEndDate": "2026-10-28T08:50:00.000Z"}]},
        {"total": 600, "itemSummaries": [{"itemId": "c", "itemEndDate": "2026-10-31T08:00:00.000Z"}]},
    ]
    client = EbayClient("x", "y")
    client._get = lambda path, params: pages[params["offset"] // 2] if params["offset"] < 3 else {}
    got = client.search(category_ids=["1"], sort="endingSoonest", limit=2, ends_before="2026-10-28T09:00:00Z")
    assert [i["itemId"] for i in got] == ["a", "b"]


def test_every_nth_run_skips_search(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EBAY_CLIENT_ID", "x")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "y")
    monkeypatch.setattr(app, "send_notification", lambda text: None)
    fake = FakeClient([], [], {})
    monkeypatch.setattr(app, "EbayClient", lambda *a, **k: fake)
    config = {"searches": [dict(SEARCH, every_nth_run=2)]}
    app.run(config)
    assert fake.calls == 0      # 1. Lauf: ausgelassen
    app.run(config)
    assert fake.calls == 1      # 2. Lauf: gesucht
