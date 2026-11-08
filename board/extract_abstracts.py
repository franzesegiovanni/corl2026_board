#!/usr/bin/env python3
"""Extract each paper's abstract and keywords from the downloaded PDFs -> board/abstracts.json

    python board/extract_abstracts.py

Needs `pdftotext` (poppler-utils) and the PDFs downloaded by corl2026_download.py. CoRL papers follow
the conference template ("Abstract: ... Keywords: ..."), so the text is read from the first two pages.
"""
import csv, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / "CoRL2026"


def first_pages(pdf):
    try:
        r = subprocess.run(["pdftotext", "-f", "1", "-l", "2", "-enc", "UTF-8", str(pdf), "-"],
                           capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:
        print(f"  ! {pdf.name}: {e}", file=sys.stderr)
        return ""


def clean(s):
    s = s.replace("­", "")                        # soft hyphens
    s = re.sub(r"(\w)-\n(\w)", r"\1\2", s)            # words split across lines
    s = re.sub(r"\s*\n\s*", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def parse(text):
    m = re.search(r"\bAbstract\s*[:.—–-]?\s*", text, re.I)
    if not m:
        return "", ""
    rest = text[m.end():]
    end = re.search(r"\n\s*(Keywords?|Index Terms)\s*[:.—–-]|\n\s*1\.?\s+Introduction\b|\n\s*I\.\s+INTRODUCTION\b|\n\s*Introduction\s*\n"
                    r"|\n\s*(Figure|Fig\.)\s*1\b", rest, re.I)
    abstract = rest[:end.start()] if end else rest[:2500]
    keywords = ""
    k = re.search(r"\n\s*Keywords?\s*[:.—–-]\s*(.*?)(?:\n\s*\n|\n\s*1\.?\s+Introduction|\n\s*Introduction\b)", rest, re.I | re.S)
    if k:
        kw = clean(k.group(1))
        # cut footnotes and figure text that pdftotext puts right after the keyword line
        cut = re.search(r"\s(\d+(st|nd|rd|th) Conference|[∗*†‡]|Correspondence|correspondence|Multimedia|Equal contribution|\S+@\S+)|\?", kw)
        if cut:
            kw = kw[:cut.start()]
            if "?" in k.group(1)[:len(kw) + 2]:   # figure labels such as "Align cam pose?": drop the last fragment
                kw = kw.rsplit(",", 1)[0] if "," in kw else ""
        keywords = kw.strip(" ,;.")[:220]
    abstract = clean(abstract)
    # drop page furniture that sometimes lands inside (e.g. "10th Conference on Robot Learning (CoRL 2026), Austin, USA.")
    abstract = re.sub(r"\s*\d+(st|nd|rd|th) Conference on Robot Learning \(CoRL 2026\)[^.]*\.", "", abstract)
    if len(abstract) > 2200:  # no clear end marker: stop at the last full sentence before 2200 characters
        cut = abstract[:2200].rfind(". ")
        abstract = abstract[:cut + 1] if cut > 800 else abstract[:2200] + "…"
    return abstract, keywords


def main():
    rows = list(csv.DictReader(open(ROOT / "index.csv", encoding="utf-8")))
    out, missing, short = {}, [], []
    for i, r in enumerate(rows):
        pdf = ROOT / r["file"]
        if not pdf.exists():
            missing.append(r["id"]); continue
        a, k = parse(first_pages(pdf))
        if len(a) < 200:
            short.append(r["id"])
        if a:
            out[r["id"]] = {"a": a, "k": k}
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(rows)}", file=sys.stderr)
    (HERE / "abstracts.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(out)} abstracts -> {HERE / 'abstracts.json'}  ({len(missing)} PDFs missing, {len(short)} suspiciously short)")
    if short:
        print("  short:", " ".join(short[:20]))


if __name__ == "__main__":
    main()
