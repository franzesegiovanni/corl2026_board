#!/usr/bin/env python3
"""Collect the CoRL 2026 workshop schedule plus each workshop's agenda and speakers -> board/workshops.json

    python board/build_workshops.py            # uses cached pages in board/ws_cache/ when present
    python board/build_workshops.py --refresh  # re-download everything

The CoRL page gives title, link, session (morning/afternoon), venue and room. Each workshop site is then
fetched (plus its schedule/program/speakers subpages) and parsed heuristically: agenda lines are lines that
start with a clock time; people are matched against the authors of CoRL 2026 main-track papers (index.csv).
Workshop sites differ a lot, so check anything important on the site itself.
"""
import argparse, csv, html, json, re, sys, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "ws_cache"
WORKSHOPS_URL = "https://www.corl.org/program/workshops"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36 corl2026-board"


def fetch(url, name, refresh):
    CACHE.mkdir(exist_ok=True)
    p = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", name)[:80] + ".html")
    if p.exists() and not refresh:
        return p.read_text(encoding="utf-8", errors="replace")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:  # keep going: one broken site should not stop the build
        print(f"  ! {url}: {e}", file=sys.stderr)
        body = ""
    p.write_text(body, encoding="utf-8")
    return body


def to_lines(t):
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>|<svg.*?</svg>", "", t, flags=re.S | re.I)
    t = re.sub(r"<(br|/p|/div|/li|/tr|/h\d|/section|/table|/ul|/dt|/dd|/header|/article)\b[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    out = []
    for l in t.split("\n"):
        l = re.sub(r"[ \t\xa0]+", " ", l).strip(" |")
        if l:
            out.append(l)
    return out


# ---------- CoRL workshop table ----------
def corl_table(page):
    links = {}
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        name = " ".join(html.unescape(re.sub("<[^>]+>", "", m.group(2))).split())
        href = html.unescape(m.group(1))
        if name and href.startswith("http") and "google.com/url" not in href:
            links[name] = href
    i = page.find("Workshop Schedule")
    emb = ""
    for m in re.finditer(r'"([^"]*&lt;table[^"]*)"', page):
        emb = html.unescape(m.group(1))
    rows = []
    slot = None
    for part in re.split(r"(Morning Session|Afternoon Session)", emb):
        if part == "Morning Session":
            slot = "am"; continue
        if part == "Afternoon Session":
            slot = "pm"; continue
        if not slot:
            continue
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", part, re.S):
            cells = [" ".join(html.unescape(re.sub("<[^>]+>", " ", c)).split()) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(cells) >= 3 and cells[0]:
                rows.append(dict(title=cells[0], venue=cells[1], room=cells[2], slot=slot))
    # match table titles to links (the table sometimes uses a slightly different title)
    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    for r in rows:
        url = links.get(r["title"])
        if not url:
            best, score = None, 0
            a = set(norm(r["title"]).split())
            for k, v in links.items():
                b = set(norm(k).split())
                s = len(a & b) / max(1, len(a | b))
                if s > score:
                    best, score = v, s
            url = best if score > .4 else ""
        r["url"] = url
    return rows


# ---------- agenda ----------
TIME = re.compile(r"^\s*\[?(\d{1,2}[:.]\d{2})\s*([AaPp]\.?\s?[Mm]\.?)?\s*(?:[-–—~|]|to)?\s*(?:(\d{1,2}[:.]\d{2})\s*([AaPp]\.?\s?[Mm]\.?)?)?\s*[\]|:\-–]?\s*(.*)$")
BAD = re.compile(r"AoE|deadline|submission|notification|camera|anywhere on earth|\bdue\b|UTC|GMT", re.I)
TAIL = re.compile(r"^(accepted papers|papers|call for papers.*|invited speakers|speakers|organizers|organi[sz]ing committee|submissions|open problems|structured breakout sessions|archived call for papers|call for papers and demos)$", re.I)


def fmt_time(t, ap):
    t = t.replace(".", ":")
    if ap:
        t += " " + ap.upper().replace(".", "").replace(" ", "")
    return t


def minutes(t, slot):
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", t)
    if not m:
        return 9999
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "PM" and h != 12:
        h += 12
    elif not ap and slot == "pm" and h < 8:
        h += 12
    return h * 60 + mi


def agenda(lines, slot):
    out, k = [], 0
    while k < len(lines):
        m = TIME.match(lines[k])
        if m and not BAD.search(lines[k]) and 0 < int(re.split("[:.]", m.group(1))[0]) <= 23:
            t1, t2 = fmt_time(m.group(1), m.group(2)), (fmt_time(m.group(3), m.group(4)) if m.group(3) else "")
            rest = m.group(5).strip(" |–-:·")
            m2 = re.match(r"^(\d{1,2}[:.]\s?\d\s?\d)\s*:?\s*(.*)$", rest)  # "8:30 | 8:45: Invited Speaker"
            if not t2 and m2:
                t2, rest = m2.group(1).replace(" ", "").replace(".", ":"), m2.group(2)
            j, extra = k + 1, []
            while j < len(lines) and len(extra) < 2 and not TIME.match(lines[j]):
                nxt = lines[j]
                if TAIL.match(nxt) or len(nxt) > 160:
                    break
                if rest and extra:
                    break
                extra.append(nxt); j += 1
                if rest:
                    break
            text = " · ".join(x for x in [rest] + extra if x)
            text = re.sub(r"\s+·\s+(Accepted Papers|Invited Speakers|Speakers|Papers|Call for Papers.*|Organizers)$", "", text)
            if text and not re.match(r"^(CST|CT|Central)\b", text):
                out.append([t1, t2, text[:240]])
            k = j
            continue
        k += 1
    seen, res = set(), []
    for it in out:
        key = (it[0], it[2][:40].lower())
        if key not in seen:
            seen.add(key); res.append(it)
    # drop a leading/trailing "whole session" line (e.g. 2:00 - 6:00 PM), sort by start time, keep site order on ties
    res = [it for it in res if not (it[1] and minutes(it[1], slot) - minutes(it[0], slot) >= 230)]
    res.sort(key=lambda it: minutes(it[0], slot))
    return res


def vue_agenda(page):
    """Sites that render the schedule from a JS array: { time: "2:00 – 2:05 PM", event: "..." }"""
    out = []
    for m in re.finditer(r'\{\s*time:\s*"([^"]+)"\s*,\s*event:\s*"([^"]+)"\s*\}', page):
        a, _, b = m.group(1).partition("–")
        out.append([a.strip(), b.strip(), m.group(2)])
    return out


# ---------- speakers ----------
HEAD = re.compile(r"^(invited |keynote |confirmed |featured )?(speakers?|keynotes?|panelists?)( & panelists| and panelists)?$", re.I)
OTHER_HEAD = re.compile(r"^(schedule|program(me)?|agenda|organi[sz](ers|ing committee)|organizers?|call for papers|accepted papers|important dates|about|sponsors?|contact|topics|challenge|competition|dates|faq|leaderboard|advisory( committee| board)?|program committee|reviewers)$", re.I)
NAME = re.compile(r"^(?:Prof\.?|Dr\.?)?\s*([A-ZÀ-Þ][\w'’\-.]+(?:\s+(?:de|van|der|von|da|di|del|la|le)?\s*[A-ZÀ-Þ][\w'’\-.]*){1,3})$")


NOT_NAME = set("""University Institute Lab Labs Research Google Meta NVIDIA Bio Website TBD Talk Talks Session Remarks Break
Schedule Program Programme Panel Discussion Submission Submissions Guidelines Accepted Workshop Format Speakers Speaker Previous
Title Tentative Person Additional Confirmed Event Thesis Agenda Evaluations Health Surgical Materials Robotics Robotic Team College
London Berkeley Zürich Zurich Technology Professor Assistant Associate CSAIL Generalist Intelligence Physical Tech Field Dyna Qwen
Imperial Neuro-symbolic TAMP LEAPs Hands-on Student Students Paper Papers Demo Demos Opening Closing Keynote Keynotes Invited Award
Awards Poster Posters Coffee Lunch Mellon Carnegie Stanford Harvard Princeton Toyota Amazon Microsoft Apple Tesla Boston Dynamics
Inc Corp Ltd AI Open Challenge Competition Leaderboard Organizers Committee Call Important Dates Contact Sponsors Venue Room Hall
Northwell Intuitive Health Systems DeepMind Laboratory Center Centre School Department Science Sciences Engineering
Voting Committees Engineer Founding Phase Breakouts""".split())
BAD_TOKEN = re.compile(r"^([A-Z]{1,3}\d*|\d.*|I{1,3}|IV|V)$")  # TU, UC, C1, II


def clean_aff(a):
    a = a.strip(" ()·")
    return "" if a.lower() in ("confirmed", "in-person", "in person", "remote", "organizers", "tbd", "cto", "ceo") else a


def speakers(lines):
    out, on = [], False
    for k, l in enumerate(lines):
        if HEAD.match(l):
            on = True; continue
        if not on:
            continue
        if OTHER_HEAD.match(l) or ROLE_HEADS[0][1].match(l) or ROLE_HEADS[1][1].match(l):
            on = False; continue
        # "Claire Tomlin UC Berkeley" -> cut at the first all-caps affiliation token
        toks = l.split()
        for q, tok in enumerate(toks):
            if q >= 2 and re.fullmatch(r"[A-Z]{2,6}", tok):
                l = " ".join(toks[:q]); break
        m = NAME.match(l)
        if m and len(l) < 40 and not any(tok.strip(".,") in NOT_NAME or BAD_TOKEN.match(tok) for tok in l.split()):
            aff = ""
            if k + 1 < len(lines):
                n = lines[k + 1]
                if not NAME.match(n) or re.search(r"University|Institute|Lab|Research|Inc|AI|Tech|College|School|Google|Meta|NVIDIA|Robotics|DeepMind|Intelligence", n):
                    aff = n if len(n) < 80 and not re.match(r"^(Bio|Website|Homepage)\b", n) else ""
            name = m.group(1).strip()
            if name not in [o[0] for o in out]:
                out.append([name, clean_aff(aff)])
    return out[:14]


# ---------- people: match CoRL main-track authors ----------
ROLE_HEADS = [
    ("org", re.compile(r"^(workshop |the )?(organi[sz](ers|ing committee|ation)|organizers?|organizing team|advisory( committee| board)?|program committee|steering committee)$", re.I)),
    ("paper", re.compile(r"^(accepted (papers|posters|contributions)|papers|spotlights?|oral papers|contributed (papers|talks)|posters)$", re.I)),
    ("spk", re.compile(r"^(invited |keynote |confirmed |featured )?(speakers?|keynotes?|panel(ists)?)( & panelists| and panelists)?$", re.I)),
    ("agenda", re.compile(r"^(confirmed |tentative )?(schedule|program(me)?|agenda)$", re.I)),
]


def people(lines, items, authors):
    role_of_line, cur = [], "other"
    for l in lines:
        for role, rx in ROLE_HEADS:
            if len(l) < 45 and rx.match(l):
                cur = role
        role_of_line.append(cur)
    # agenda lines that list a paper's author list (several commas) are spotlight/oral papers, not invited talks
    talk_txt = " \n ".join(it[2] for it in items if it[2].count(",") < 3)
    paper_txt = " \n ".join(it[2] for it in items if it[2].count(",") >= 3)
    found = {}
    rank = {"spk": 0, "org": 1, "paper": 2, "other": 3}
    for k, l in enumerate(lines):
        for name, rx in authors:
            if rx.search(l):
                role = role_of_line[k]
                if role == "agenda":
                    role = "paper" if l.count(",") >= 3 else "spk"
                if rx.search(talk_txt):
                    role = "spk"
                elif rx.search(paper_txt) and role != "org":
                    role = "paper"
                if name not in found or rank[role] < rank[found[name]]:
                    found[name] = role
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default=str(HERE.parent / "CoRL2026" / "index.csv"))
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    page = fetch(WORKSHOPS_URL, "_corl_workshops", args.refresh)
    rows = corl_table(page)
    if not rows:
        sys.exit("Could not read the workshop table from the CoRL page; the page layout may have changed.")

    names = set()
    for r in csv.DictReader(open(args.index, encoding="utf-8")):
        names.update(a.strip() for a in r["authors"].split(",") if a.strip())
    # only distinctive full names: at least two words, not all lower-case
    authors = [(n, re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])")) for n in sorted(names)
               if " " in n and len(n) >= 7 and not n.islower()]

    out = []
    for i, r in enumerate(rows):
        print(f"[{i + 1}/{len(rows)}] {r['title'][:70]}", file=sys.stderr)
        body = fetch(r["url"], f"ws{i}", args.refresh) if r["url"] else ""
        m = re.search(r'http-equiv="refresh"[^>]*url=([^"\']+)', body, re.I)
        base = r["url"]
        if m and len(body) < 3000:  # redirect stub
            base = m.group(1).strip()
            body = fetch(base, f"ws{i}_r", args.refresh)
        pages = [body]
        if "google.com/v3/signin" in body or "<title>Google Drive: Sign-in" in body:
            pages, note = [], "The workshop site needs a Google sign-in, so its agenda could not be read."
        else:
            note = ""
            subs = set()
            for h in re.findall(r'href="([^"#]*(?:schedule|program|agenda|speakers)[^"#]*)"', body, re.I):
                u = urllib.parse.urljoin(base, h)
                if urllib.parse.urlparse(u).netloc == urllib.parse.urlparse(base).netloc and u.rstrip("/") != base.rstrip("/"):
                    subs.add(u)
            for j, u in enumerate(sorted(subs)[:3]):
                pages.append(fetch(u, f"ws{i}_s{j}", args.refresh))
        lines = [l for p in pages for l in to_lines(p)]
        items = agenda(lines, r["slot"]) or [it for p in pages for it in vue_agenda(p)]
        spk = speakers(lines)
        ppl = people(lines, items, authors) if lines else {}
        if not note and not items:
            note = "No timed agenda on the workshop site yet."
        out.append(dict(title=r["title"], url=r["url"], slot=r["slot"], venue=r["venue"], room=r["room"],
                        items=items, speakers=spk, people=ppl, note=note))
    (HERE / "workshops.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_it = sum(len(w["items"]) for w in out)
    n_pp = sum(len(w["people"]) for w in out)
    print(f"{len(out)} workshops, {n_it} agenda items, {n_pp} CoRL authors matched -> {HERE / 'workshops.json'}")


if __name__ == "__main__":
    main()
