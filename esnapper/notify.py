"""WhatsApp-Benachrichtigung über CallMeBot (https://www.callmebot.com)."""
import os

import requests

MAX_LEN = 3500  # CallMeBot schneidet sehr lange Nachrichten ab


def send_whatsapp(text):
    phone = os.environ.get("CALLMEBOT_PHONE")
    apikey = os.environ.get("CALLMEBOT_APIKEY")
    if not phone or not apikey:
        print("Keine CallMeBot-Daten gesetzt, Nachricht nur im Log:\n" + text)
        return False
    r = requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": phone, "text": text[:MAX_LEN], "apikey": apikey},
        timeout=30,
    )
    r.raise_for_status()
    return True


def format_hits(hits):
    lines = [f"🔥 {len(hits)} neue{'s' if len(hits) == 1 else ''} Schnäppchen"]
    for h in hits:
        lines.append(
            f"\n*{h['title'][:80]}*\n"
            f"Gebot {h['bid']:.2f} € (+{h['shipping'] or 0:.2f} Versand), "
            f"Vergleich {h['reference']:.2f} €, {h['saving'] * 100:.0f} % drunter\n"
            f"Endet {h['ends_local']}\n{h['url']}"
        )
    return "\n".join(lines)
