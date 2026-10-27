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


SEARCH = {"name": "Test", "category_ids": ["12576"], "min_saving": 0.3, "min_price": 20, "max_price": 2000,
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
    monkeypatch.setattr(app, "send_whatsapp", sent.append)
    comps = [{"price": {"value": v}, "shippingOptions": []} for v in ("300", "320", "340", "360")]
    auctions = [
        auction("cheap", bid="100.00"),                      # 110 vs 330 -> Treffer
        auction("reserve", bid="100.00"),                    # Treffer, aber Mindestpreis nicht erreicht
        auction("pricey", bid="300.00"),                     # kein Schnäppchen
        auction("bin", bid="50.00", options=("AUCTION", "FIXED_PRICE"), price="200.00"),  # 60 vs 200
    ]
    fake = FakeClient(auctions, comps, {"reserve": False})
    monkeypatch.setattr(app, "EbayClient", lambda *a, **k: fake)
    config = {"searches": [SEARCH]}

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
