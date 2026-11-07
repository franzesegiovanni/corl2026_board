#!/usr/bin/env python3
"""Build the CoRL 2026 paper board (a single HTML page) from index.csv + the official schedule.

    python board/build_board.py            # uses board/schedule_source.html if present, else downloads it
    python board/build_board.py --refresh  # re-download the schedule from 2026.corl.org

Output: board/corl2026_board.html
"""
import argparse, csv, html, json, re, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEDULE_URL = "https://2026.corl.org/program/accepted-papers"


def fetch_schedule(cache, refresh):
    if cache.exists() and not refresh:
        page = cache.read_text(encoding="utf-8")
    else:
        req = urllib.request.Request(SCHEDULE_URL, headers={"User-Agent": "Mozilla/5.0 (corl2026-board)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = r.read().decode("utf-8", "replace")
        cache.write_text(page, encoding="utf-8")
    # The Google Sites page embeds the schedule as an escaped HTML document inside an attribute.
    i = page.find("&lt;h1&gt;CoRL 2026 Accepted Papers")
    if i < 0:
        sys.exit("Could not find the embedded schedule on the CoRL page; the page layout may have changed.")
    s, e = page.rfind('"', 0, i), page.find('"', i)
    return html.unescape(page[s + 1:e])


def to24(t, ampm):
    h, m = map(int, t.split(":"))
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"


def parse_time(s):
    # "9:00–9:30 AM", "11:30 AM–12:00 PM", "10:30 AM–12:00 PM"
    a, b = [x.strip() for x in s.split("–")]
    bt, bap = b.split()
    if " " in a:
        at, aap = a.split()
    else:
        at, aap = a, bap
    return to24(at, aap), to24(bt, bap)


def parse(src):
    sessions, sched, day = [], {}, None
    pat = re.compile(r'<section class="day" id="day-(\w+)"><h2>(.*?)</h2>'
                     r'|<section class="session( poster)?"[^>]*?(?:data-sess="(\w+)"|id="post-(\w+)")[^>]*>(.*?)</section>', re.S)
    for m in pat.finditer(src):
        if m.group(1):
            day = m.group(1)
            continue
        body, code = m.group(6), (m.group(4) or m.group(5)).upper()
        h3 = re.search(r'<h3[^>]*class="(\w+)"[^>]*><span class="tag">(.*?)</span>\s*(.*?)</h3>', body, re.S)
        kind, tag = h3.group(1), html.unescape(h3.group(2))
        theme = html.unescape(re.sub("<[^>]+>", "", h3.group(3))).strip()
        meta = re.search(r'<p class="meta">(.*?)</p>', body, re.S).group(1)
        rooms_txt = ""
        if "<br>" in meta:
            meta, rooms_txt = meta.split("<br>", 1)
        meta = html.unescape(re.sub("<[^>]+>", "", meta))
        when, venue = [p.strip() for p in meta.split("·")][:2]
        tm = re.match(r"\w+ (\d+)/(\d+), (.*)", when)
        start, end = parse_time(tm.group(3))
        rooms = []
        for r in re.finditer(r"([^·:]+?)\s*\(([^)]+)\):\s*posters\s*(\d+)\s*[–-]\s*(\d+)", html.unescape(re.sub("<[^>]+>", "", rooms_txt))):
            rooms.append([int(r.group(3)), int(r.group(4)), r.group(1).strip(), r.group(2).strip()])
        n = 0
        if kind == "poster":
            for r in re.finditer(r'<td class="num">(\d+)</td><td><a href="https://openreview.net/forum\?id=([^"&]+)"', body):
                sched.setdefault(r.group(2), {}).update(poster=code, num=int(r.group(1)))
                n += 1
        else:
            for r in re.finditer(r'<li class="paper"><a href="https://openreview.net/forum\?id=([^"&]+)"', body):
                sched.setdefault(r.group(1), {})["talk"] = code
                n += 1
        sessions.append(dict(code=code, kind=kind, label=theme if kind == "poster" else tag,
                             theme="" if kind == "poster" else theme, day=day,
                             date=f"2026-{int(tm.group(1)):02d}-{int(tm.group(2)):02d}",
                             time=tm.group(3), start=start, end=end, venue=venue, rooms=rooms, n=n))
    return sessions, sched


GREEK = {"pi": "π", "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "lambda": "λ",
         "mu": "μ", "sigma": "σ", "tau": "τ", "phi": "φ", "psi": "ψ", "omega": "ω", "Pi": "Π", "Delta": "Δ"}
SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


def clean_title(t):
    """Turn simple inline LaTeX in titles ($\\pi_{0.7}$, M$^3$P, $SE(3)$) into plain text."""
    def fix(m):
        x = m.group(1)
        x = re.sub(r"\\([A-Za-z]+)", lambda g: GREEK.get(g.group(1), g.group(1)), x)
        x = re.sub(r"\^\{?([0-9+-]+)\}?", lambda g: g.group(1).translate(SUP), x)
        x = re.sub(r"_\{([^}]*)\}", r"\1", x)
        return re.sub(r"[_^{}\\]", "", x)
    return re.sub(r"\$([^$]{1,80})\$", fix, t)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default=str(HERE.parent / "CoRL2026" / "index.csv"))
    ap.add_argument("--out", default=str(HERE / "corl2026_board.html"))
    ap.add_argument("--refresh", action="store_true", help="re-download the schedule page")
    args = ap.parse_args()

    sessions, sched = parse(fetch_schedule(HERE / "schedule_source.html", args.refresh))
    rows = list(csv.DictReader(open(args.index, encoding="utf-8")))
    cats = sorted({r["category"] for r in rows} | {m.strip() for r in rows for m in r["all_matches"].split(";") if m.strip()})
    authors, aidx = [], {}
    papers = []
    for r in rows:
        ai = []
        for a in (x.strip() for x in r["authors"].split(",")):
            if a:
                if a not in aidx:
                    aidx[a] = len(authors)
                    authors.append(a)
                ai.append(aidx[a])
        s = sched.get(r["id"], {})
        matches = [cats.index(m.strip()) for m in r["all_matches"].split(";") if m.strip() and m.strip() != r["category"]]
        papers.append([r["id"], clean_title(r["title"]), ai, cats.index(r["category"]), matches,
                       r["venue"].replace("CoRL 2026 ", "")[:1], s.get("talk", ""), s.get("poster", ""), s.get("num", 0)])
    missing = sum(1 for p in papers if not p[7])
    # workshops (Thursday): built separately by build_workshops.py
    W = []
    wpath = HERE / "workshops.json"
    if wpath.exists():
        for w in json.loads(wpath.read_text(encoding="utf-8")):
            W.append(dict(t=w["title"], u=w["url"], s=w["slot"], v=w["venue"], r=w["room"], it=w["items"], note=w["note"],
                          sp=[[n, a, aidx.get(n, -1)] for n, a in w["speakers"]],
                          pp=[[aidx[n], role] for n, role in w["people"].items() if n in aidx]))
    data = json.dumps(dict(S=sessions, C=cats, A=authors, P=papers, W=W), ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    page = (HERE / "board_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    Path(args.out).write_text(page, encoding="utf-8")
    # Standalone copy (repo-root index.html, served by GitHub Pages) for any browser; Claude adds this wrapper itself at publish time
    standalone = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                  '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
                  'body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>'
                  '</head><body>' + page + '</body></html>')
    (HERE.parent / "index.html").write_text(standalone, encoding="utf-8")
    print(f"{len(papers)} papers, {len(authors)} authors, {len(sessions)} sessions"
          f"{f', {missing} papers without a poster slot' if missing else ''} -> {args.out}")


if __name__ == "__main__":
    main()
