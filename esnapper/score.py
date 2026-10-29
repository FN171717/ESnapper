"""Bewertung und Filter. Reine Funktionen, damit sie ohne eBay testbar sind."""
import re
import statistics

STOPWORDS = {
    "und", "mit", "für", "fur", "der", "die", "das", "ein", "eine", "von", "the", "and",
    "for", "with", "neu", "new", "gebraucht", "used", "top", "ovp", "originalverpackt",
    "inkl", "set", "stück", "stk", "zustand", "sehr", "gut", "guter", "rarität", "selten",
}


def money(obj):
    """{'value': '12.50', 'currency': 'EUR'} -> 12.5 (oder None)."""
    try:
        return float(obj["value"])
    except (TypeError, KeyError, ValueError):
        return None


def shipping_cost(item):
    """Günstigste Versandoption, None wenn unbekannt (z. B. nur Abholung)."""
    costs = [money(o.get("shippingCost")) for o in item.get("shippingOptions", [])]
    costs = [c for c in costs if c is not None]
    return min(costs) if costs else None


def current_bid(item):
    return money(item.get("currentBidPrice"))


def buy_it_now_price(item):
    """Sofortkaufpreis einer Auktion, falls sie einen hat."""
    if "FIXED_PRICE" in item.get("buyingOptions", []) and "AUCTION" in item.get("buyingOptions", []):
        return money(item.get("price"))
    return None


def comparison_keywords(title, max_words=6):
    """Kernbegriffe aus dem Titel für die Vergleichssuche."""
    words = re.findall(r"[\wäöüß\-]+", title.lower())
    out = []
    for w in words:
        w = w.strip("-")
        if len(w) < 3 or w in STOPWORDS or w in out:
            continue
        out.append(w)
        if len(out) == max_words:
            break
    return " ".join(out)


def robust_median(prices, min_count=3):
    """Median ohne Ausreißer (unteres/oberes Viertel weg). None bei zu wenig Daten."""
    prices = sorted(p for p in prices if p and p > 0)
    if len(prices) < min_count:
        return None
    cut = len(prices) // 4
    core = prices[cut:len(prices) - cut] if cut else prices
    return statistics.median(core)


def saving(bid, shipping, reference):
    """Anteil unter dem Referenzpreis, z. B. 0.4 = 40 % günstiger."""
    if not reference or bid is None:
        return None
    return 1 - (bid + (shipping or 0)) / reference


def evaluate(bid, shipping, reference, search):
    """Bewertet eine Auktion gegen den Referenzpreis.

    Ein Treffer braucht beides: genug Abstand in Euro (lohnt sich der Aufwand?) und genug
    Abstand in Prozent (Puffer, falls der Referenzpreis daneben liegt oder das Gebot noch steigt).
    So fällt ein Auto mit 20.000 € Gebot bei 22.000 € Sofortkauf raus (2.000 €, aber nur 9 %),
    ebenso ein Artikel für 50 € statt 100 € (50 %, aber nur 50 €).

    Bewertung = Differenz × Ersparnis: bevorzugt Angebote, die in Euro viel bringen und dabei
    viel Luft lassen. Dient zum Sortieren der Treffer.
    """
    s = saving(bid, shipping, reference)
    if s is None:
        return {"saving": None, "difference": None, "rating": None, "is_hit": False}
    difference = reference - bid - (shipping or 0)
    rating = max(difference, 0) * max(s, 0)
    is_hit = difference >= search.get("min_difference", 0) and s >= search.get("min_saving", 0.3)
    return {"saving": s, "difference": difference, "rating": rating, "is_hit": is_hit}


def passes_filters(item, search):
    """Prüft alles, was ohne Zusatzabfrage geht. Gibt (ok, grund) zurück."""
    title = item.get("title", "").lower()
    for word in search.get("exclude_words", []):
        if word.lower() in title:
            return False, f"Ausschlusswort '{word}'"

    bid = current_bid(item)
    if bid is None:
        return False, "kein Gebotspreis"
    if search.get("min_price") is not None and bid < search["min_price"]:
        return False, "Gebot zu niedrig"
    if search.get("max_price") is not None and bid > search["max_price"]:
        return False, "Gebot zu hoch"

    ship = shipping_cost(item)
    if search.get("max_shipping") is not None and ship is not None and ship > search["max_shipping"]:
        return False, "Versand zu teuer"

    min_fb = search.get("min_seller_feedback")
    if min_fb is not None:
        fb = item.get("seller", {}).get("feedbackPercentage")
        if fb is not None and float(fb) < min_fb:
            return False, "Verkäuferbewertung zu niedrig"
    return True, ""


def wrong_country(item, country):
    """True, wenn der Artikel nachweislich nicht in country steht (eBay wendet Filter nicht immer an)."""
    found = item.get("itemLocation", {}).get("country")
    return bool(country and found and found != country)
