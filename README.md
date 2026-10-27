# ESnapper

Findet eBay-Auktionen, die kurz vor Ende deutlich unter ihrem Vergleichspreis stehen, zeigt sie auf einer Übersichtsseite und meldet neue Treffer per Push aufs Handy (ntfy) und/oder per WhatsApp (CallMeBot).

## So funktioniert es

Alle 15 Minuten startet GitHub Actions einen Lauf:

1. Über die offizielle eBay Browse API werden die Auktionen jeder Suche aus `config.yaml` abgefragt, die im eingestellten Zeitfenster enden.
2. Filter: Preisspanne, Versandkosten, Zustand, Ausschlusswörter, Verkäuferbewertung.
3. Für jeden neuen Artikel wird einmalig ein Referenzpreis bestimmt: der Sofortkaufpreis der Auktion, sonst der Median vergleichbarer Sofortkauf-Angebote (Suche mit den Kernbegriffen des Titels, gleiche Kategorie, gleicher Zustand).
4. Ersparnis = 1 − (Gebot + Versand) / Referenzpreis. Ab `min_saving` ist es ein Treffer.
5. Bei Treffern wird geprüft, ob ein Mindestpreis nicht erreicht ist. Solche Artikel fallen raus.
6. Neue Treffer gehen gesammelt an jeden eingerichteten Kanal (ntfy, WhatsApp), jeder nur einmal. Die Übersicht landet auf GitHub Pages.

Schlägt ein Lauf fehl, kommt höchstens alle 6 Stunden eine Warnung.

## Einrichtung

1. **eBay-Keys:** Auf developer.ebay.com einen Production-Keyset anlegen und bei „Marketplace Account Deletion“ die Ausnahme wählen. Benötigt werden App ID und Cert ID.
2. **Benachrichtigung** (mindestens eine, sonst stehen Treffer nur im Log):
   - **ntfy (empfohlen):** App „ntfy“ installieren (Android/iOS), „+“ tippen und ein schwer zu erratendes Thema abonnieren, z. B. `esnapper-7f3k9x2q`. Kein Konto nötig. Wer das Thema kennt, kann mitlesen, daher nicht zu einfach wählen.
   - **WhatsApp über CallMeBot:** Auf callmebot.com unter „WhatsApp API“ die Freigabe-Nachricht an die dort genannte Nummer schicken, dann kommt ein API-Key zurück. Der Dienst nimmt zeitweise keine neuen Nutzer an.
3. **Secrets** im Repo unter Settings → Secrets and variables → Actions anlegen:
   - `EBAY_CLIENT_ID` (App ID)
   - `EBAY_CLIENT_SECRET` (Cert ID)
   - `NTFY_TOPIC` (dein ntfy-Thema), und/oder
   - `CALLMEBOT_PHONE` (deine Nummer, z. B. `+4917612345678`) und `CALLMEBOT_APIKEY`
4. **Pages:** Settings → Pages → Source auf „GitHub Actions“ stellen.
5. Unter Actions → ESnapper → „Run workflow“ einmal von Hand starten. Danach läuft es von selbst.

## Anpassen

Alles Fachliche steht in `config.yaml`: Suchen, Kategorien, Zeitfenster, Schwellen, Filter. Mehrere Suchen sind möglich, z. B. eine pro Marke.

## Lokal testen

```
pip install -r requirements.txt pytest
pytest -q
EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=... python -m esnapper   # schreibt site/index.html
```

## Grenzen

- Der Vergleichspreis ist eine Näherung: Sofortkauf-Angebote sind meist teurer als echte Endpreise, und die Titelsuche trifft nicht immer genau dasselbe Produkt. Echte Verkaufspreise gibt eBay nur über die Marketplace Insights API frei, und die nur auf Antrag.
- Die eBay-API erlaubt 5.000 Aufrufe pro Tag. `max_new_items_per_run` begrenzt die Vergleichssuchen pro Lauf.
- GitHub startet geplante Läufe teils einige Minuten verspätet.
