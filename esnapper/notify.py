"""Benachrichtigung per ntfy-Push (https://ntfy.sh) und/oder WhatsApp über CallMeBot."""
import os

import requests

MAX_LEN = 3500  # CallMeBot schneidet sehr lange Nachrichten ab


def send_notification(text):
    """Schickt über jeden eingerichteten Kanal. Ohne Kanal landet die Nachricht nur im Log."""
    sent = False
    if os.environ.get("NTFY_TOPIC"):
        send_ntfy(os.environ["NTFY_TOPIC"], text)
        sent = True
    if os.environ.get("CALLMEBOT_PHONE") and os.environ.get("CALLMEBOT_APIKEY"):
        send_whatsapp(os.environ["CALLMEBOT_PHONE"], os.environ["CALLMEBOT_APIKEY"], text)
        sent = True
    if not sent:
        print("Kein Benachrichtigungskanal eingerichtet, Nachricht nur im Log:\n" + text)
    return sent


def send_ntfy(topic, text):
    r = requests.post(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"),
                      headers={"Title": "ESnapper", "Tags": "moneybag"}, timeout=30)
    r.raise_for_status()


def send_whatsapp(phone, apikey, text):
    r = requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": phone, "text": text[:MAX_LEN], "apikey": apikey},
        timeout=30,
    )
    r.raise_for_status()


def format_hits(hits):
    lines = [f"🔥 {len(hits)} neue{'s' if len(hits) == 1 else ''} Schnäppchen"]
    for h in hits:
        lines.append(
            f"\n*{h['title'][:80]}*\n"
            f"Gebot {h['bid']:.2f} € (+{h['shipping'] or 0:.2f} Versand), "
            f"Vergleich {h['reference']:.2f} €, {h['difference']:.0f} € bzw. {h['saving'] * 100:.0f} % drunter\n"
            f"Endet {h['ends_local']}\n{h['url']}"
        )
    return "\n".join(lines)
