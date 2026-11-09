#!/usr/bin/env python3
"""Collect the CoRL 2026 main program (keynotes, early-career keynotes, special panel, session chairs,
sponsor talks, breaks, socials, livestreams) -> board/program.json

    python board/build_program.py            # uses cached pages in board/ws_cache/ when present
    python board/build_program.py --refresh  # re-download

Sources: the program grid on https://www.corl.org/program (its day-by-day agenda), plus the
Keynotes, Early Career Keynotes and Special Panel pages for titles, abstracts and bios.
"""
import argparse, html, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_workshops import fetch  # same cache folder and user agent

HERE = Path(__file__).resolve().parent
BASE = "https://www.corl.org"
DAYS = {"mon": "2026-11-09", "tue": "2026-11-10", "wed": "2026-11-11", "thu": "2026-11-12"}
KIND = {"general": "general", "spotlight": "spotlight", "oral": "oral", "early-career": "early", "keynote": "keynote",
        "break": "break", "lunch": "break", "sponsor": "sponsor", "poster": "poster", "social": "social",
        "reception": "social", "panel": "panel", "workshop": "workshop"}


def embedded(page):
    """Google Sites pages keep their custom HTML in escaped attributes: return the longest one."""
    embs = [html.unescape(m) for m in re.findall(r'"([^"]*&lt;(?:div|p|h\d|table|section)[^"]*)"', page)]
    return max(embs, key=len) if embs else ""


def text(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    return [" ".join(l.split()) for l in html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split("\n") if l.strip()]


def to24(t):
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", t.strip(), re.I)
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def agenda(grid):
    days, events = [], []
    for sec in re.findall(r'<section class="agday">(.*?)</section>', grid, re.S):
        d = re.search(r'<h2 id="(\w+)">(.*?)</h2>', sec)
        day = d.group(1)
        live = [{"label": " ".join(html.unescape(re.sub("<[^>]+>", "", a.group(2))).replace("▶", "").split()), "url": a.group(1)}
                for a in re.finditer(r'<a class="live"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', sec)]
        days.append({"day": day, "date": DAYS.get(day, ""), "title": html.unescape(d.group(2)), "live": live})
        for item in sec.split('<div class="item">')[1:]:
            w = re.search(r'<div class="when"><b>(.*?)</b>(?:&ndash;|–|-)\s*(.*?)</div>', item)
            k = re.search(r'<div class="what event-([\w-]+)">', item)
            if not (w and k):
                continue
            what = item[k.end():]
            chair = re.search(r'<span class="chair">Session Chair:\s*<strong>(.*?)</strong>', what)
            par = re.search(r'<div class="parallel">(.*?)</div>', what, re.S)
            main = re.sub(r'<span class="chair">.*?</span>|<div class="parallel">.*?</div>', "", what, flags=re.S)
            lines = [l for l in text(main) if l]
            venue = ""
            if lines and re.match(r"^\(.*\)$", lines[-1]):
                venue = lines.pop()[1:-1]
            strong = [html.unescape(re.sub("<[^>]+>", "", s)).strip() for s in re.findall(r"<strong>(.*?)</strong>", main)]
            kind = KIND.get(k.group(1), "general")
            code = ""
            m = re.match(r"^(Spotlight|Oral)\s+([SO]\d+)$", lines[0]) if lines else None
            if m:
                code = m.group(2)
            person = ""
            if kind in ("keynote", "early") and len(lines) > 1:
                person = lines[1]
            ev = {"day": day, "date": DAYS.get(day, ""), "start": to24(w.group(1)), "end": to24(w.group(2)),
                  "kind": kind, "title": lines[0] if lines else "", "lines": lines[1:], "venue": venue,
                  "chair": html.unescape(chair.group(1)).strip() if chair else "", "code": code, "person": person}
            if par:
                pl = text(par.group(1))
                pl = [l for l in pl if l.lower() != "parallel session"]
                ev["parallel"] = {"title": pl[0] if pl else "", "venue": pl[1][1:-1] if len(pl) > 1 and pl[1].startswith("(") else ""}
            events.append(ev)
    return days, events


def speakers(page, role):
    """Keynote pages: affiliation line, name, 'Title: ...', 'Abstract: ...', 'Bio: ...' per speaker."""
    lines = text(re.sub(r"</(p|div|h\d|li)>", "\n", re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)))
    try:
        start = next(i for i, l in enumerate(lines) if l in ("Keynotes", "Early Career Keynotes"))
    except StopIteration:
        start = 0
    lines = lines[start + 1:]
    out, cur = [], None
    for i, l in enumerate(lines):
        if l.startswith("Title:") and i >= 2:
            cur = {"name": lines[i - 1], "aff": lines[i - 2], "title": l[6:].strip(), "abstract": "", "bio": "", "role": role}
            out.append(cur)
        elif cur and l.startswith("Abstract:"):
            cur["abstract"] = l[9:].strip(); cur["_f"] = "abstract"
        elif cur and l.startswith("Bio:"):
            cur["bio"] = l[4:].strip(); cur["_f"] = "bio"
        elif cur and cur.get("_f") and l not in ("Report abuse", "Page details", "Page updated") and not lines[i + 1:i + 2] == ["Title:"]:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.startswith("Title:") or (i + 2 < len(lines) and lines[i + 2].startswith("Title:")):
                cur.pop("_f", None); cur = None; continue
            if l.startswith("Fireside Chat") or l in ("Report abuse",):
                cur.pop("_f", None); cur = None; continue
            cur[cur["_f"]] += ("\n" if cur["_f"] == "abstract" else " ") + l
    # the fireside chat guest has only a bio
    m = re.search(r"Fireside Chat with ([^\n]+)", "\n".join(lines))
    for o in out:
        o.pop("_f", None)
        o["abstract"] = o["abstract"].strip(); o["bio"] = o["bio"].strip()
    if m:
        try:
            i = lines.index(next(l for l in lines if l.startswith("Fireside Chat")))
            aff, name = lines[i + 1], lines[i + 2]
            bio = []
            for l in lines[i + 3:]:
                if l in ("Report abuse", "Page details"):
                    break
                bio.append(l[4:].strip() if l.startswith("Bio:") else l)
            out.append({"name": name, "aff": aff, "title": lines[i], "abstract": "", "bio": " ".join(bio).strip(), "role": "fireside"})
        except (StopIteration, IndexError):
            pass
    return out


def panel(page):
    lines = text(re.sub(r"</(p|div|h\d|li)>", "\n", re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)))
    try:
        i = next(k for k, l in enumerate(lines) if l.startswith("We are honored"))
    except StopIteration:
        return {"intro": "", "people": []}
    people, k = [], i + 1
    while k + 1 < len(lines) and lines[k] not in ("Report abuse", "Page details"):
        people.append({"name": lines[k], "aff": lines[k + 1]}); k += 2
    return {"intro": lines[i], "people": people}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    grid = embedded(fetch(f"{BASE}/program", "_corl_program", a.refresh))
    if 'class="agday"' not in grid:
        sys.exit("Could not find the day-by-day program on corl.org/program; the page layout may have changed.")
    days, events = agenda(grid)
    spk = speakers(fetch(f"{BASE}/program/keynotes", "_corl_keynotes", a.refresh), "keynote")
    spk += speakers(fetch(f"{BASE}/program/early-career-keynotes", "_corl_early", a.refresh), "early")
    pan = panel(fetch(f"{BASE}/program/special-panel", "_corl_panel", a.refresh))
    out = {"days": days, "events": events, "speakers": spk, "panel": pan}
    (HERE / "program.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(events)} program items over {len(days)} days, {len(spk)} keynote speakers, "
          f"{len(pan['people'])} panelists -> {HERE / 'program.json'}")


if __name__ == "__main__":
    main()
