"""Erzeugt die statische Übersichtsseite site/index.html."""
import html
import json
from pathlib import Path

PAGE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESnapper</title>
<style>
  :root { --bg:#f7f7f5; --card:#fff; --text:#1d1d1b; --muted:#6b6b66; --line:#e3e3df; --hit:#0a7d3b; --hitbg:#e8f6ee; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#151514; --card:#1f1f1d; --text:#ececea; --muted:#9a9a94; --line:#33332f; --hit:#5fd38f; --hitbg:#1b3426; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.4 system-ui, sans-serif; }
  header { padding:16px; max-width:1000px; margin:0 auto; }
  h1 { margin:0 0 4px; font-size:22px; }
  .meta { color:var(--muted); font-size:13px; }
  .controls { margin-top:10px; display:flex; gap:12px; font-size:14px; }
  main { max-width:1000px; margin:0 auto; padding:0 16px 32px; display:grid; gap:10px; }
  .item { display:grid; grid-template-columns:72px 1fr auto; gap:12px; align-items:center;
          background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px; color:inherit; text-decoration:none; }
  .item.hit { border-color:var(--hit); background:var(--hitbg); }
  .item img { width:72px; height:72px; object-fit:contain; border-radius:6px; background:#fff; }
  .title { font-weight:600; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
  .sub { color:var(--muted); font-size:13px; margin-top:2px; }
  .right { text-align:right; white-space:nowrap; }
  .saving { font-size:20px; font-weight:700; }
  .hit .saving { color:var(--hit); }
  .left { font-variant-numeric:tabular-nums; font-size:13px; }
  .empty { color:var(--muted); padding:24px 0; }
  @media (max-width:560px) { .item { grid-template-columns:56px 1fr; } .item img { width:56px; height:56px; }
    .right { grid-column:2; text-align:left; display:flex; gap:12px; align-items:baseline; } }
</style>
</head>
<body>
<header>
  <h1>ESnapper</h1>
  <div class="meta">Stand: <span id="gen"></span> · __COUNT__ Auktionen mit Vergleichspreis, davon __HITS__ Treffer</div>
  <div class="controls"><label><input type="checkbox" id="onlyhits"> Nur Treffer</label></div>
</header>
<main id="list">__ITEMS__</main>
<script>
  const gen = new Date("__GENERATED__");
  document.getElementById("gen").textContent = gen.toLocaleString("de-DE");
  function fmt(ms) {
    if (ms <= 0) return "beendet";
    const m = Math.floor(ms / 60000), h = Math.floor(m / 60);
    return h ? h + " Std " + (m % 60) + " Min" : m + " Min";
  }
  function tick() {
    document.querySelectorAll("[data-end]").forEach(el => {
      el.textContent = "noch " + fmt(new Date(el.dataset.end) - Date.now());
    });
  }
  tick(); setInterval(tick, 30000);
  const cb = document.getElementById("onlyhits");
  try { cb.checked = localStorage.getItem("onlyhits") === "1"; } catch (e) {}
  function apply() {
    document.querySelectorAll(".item:not(.hit)").forEach(el => el.hidden = cb.checked);
    try { localStorage.setItem("onlyhits", cb.checked ? "1" : "0"); } catch (e) {}
  }
  cb.addEventListener("change", apply); apply();
</script>
</body>
</html>
"""

ITEM = """<a class="item{hit}" href="{url}" target="_blank" rel="noopener">
  <img src="{img}" alt="" loading="lazy">
  <div><div class="title">{title}</div>
    <div class="sub">{bid:.2f} € · {bids} Gebot(e) · Versand {ship} · Vergleich {ref:.2f} € ({src})</div></div>
  <div class="right"><div class="saving">{saving:+.0f} %</div><div class="left">{diff:+.0f} €</div><div class="left" data-end="{end}"></div></div>
</a>"""


def render(rows, generated_iso, out_dir="site"):
    rows = sorted(rows, key=lambda r: r["end"])
    parts = [
        ITEM.format(
            hit=" hit" if r["is_hit"] else "",
            url=html.escape(r["url"]),
            img=html.escape(r.get("image") or ""),
            title=html.escape(r["title"]),
            bid=r["bid"],
            bids=r["bid_count"],
            ship="unbekannt" if r["shipping"] is None else f"{r['shipping']:.2f} €",
            ref=r["reference"],
            src=html.escape(r["reference_source"]),
            saving=-r["saving"] * 100,
            diff=-r["difference"],
            end=html.escape(r["end"]),
        )
        for r in rows
    ]
    page = (PAGE.replace("__ITEMS__", "\n".join(parts) or '<p class="empty">Gerade nichts Passendes.</p>')
                .replace("__COUNT__", str(len(rows)))
                .replace("__HITS__", str(sum(r["is_hit"] for r in rows)))
                .replace("__GENERATED__", generated_iso))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "items.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
