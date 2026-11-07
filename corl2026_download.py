#!/usr/bin/env python3
"""Download CoRL 2026 accepted papers from OpenReview into topic subfolders.

Standard library only (no installs).

    python corl2026_download.py --dry-run     # fetch metadata, write index.csv, print folder counts
    python corl2026_download.py               # also download the PDFs (resumable, skips existing)

If OpenReview refuses anonymous API access, log in via env vars:
    export OPENREVIEW_USERNAME=you@example.com OPENREVIEW_PASSWORD=...

Categorisation: if the venue exposes a `primary_area` field it is used as-is;
otherwise each paper goes to the TAXONOMY folder with the highest score
(phrase found in title = 3, in keywords = 2, in abstract = 1; ties -> earlier folder).
All matching folders are listed in index.csv, so you can re-sort later without re-downloading.
"""
import argparse, csv, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

API = "https://api2.openreview.net"
VENUE_ID = "robot-learning.org/CoRL/2026/Conference"
FALLBACK = "Other"

# Edit freely. Lower-case phrases, matched on word boundaries (plural 's' tolerated).
# "manipulation" is deliberately absent: most CoRL papers would match it.
TAXONOMY = {
    "VLA_Foundation_Models": ["vision-language-action", "vla", "foundation model", "generalist policy",
                              "language model", "llm", "vision-language model", "vlm", "pretraining", "scaling law"],
    "World_Models_Video": ["world model", "video prediction", "video generation", "video model",
                           "video diffusion", "latent dynamics", "dynamics model"],
    "Humanoids_Locomotion": ["humanoid", "locomotion", "legged", "quadruped", "biped", "whole-body",
                             "parkour", "loco-manipulation"],
    "Dexterous_Tactile_Bimanual": ["dexterous", "in-hand", "multi-fingered", "tactile", "contact-rich",
                                   "grasp", "grasping", "bimanual", "deformable", "cloth", "articulated object"],
    "Navigation_Driving_Aerial": ["navigation", "autonomous driving", "driving", "drone", "aerial",
                                  "quadrotor", "uav", "mobile robot"],
    "Reinforcement_Learning": ["reinforcement learning", "rl", "reward", "policy gradient", "ppo",
                               "q-learning", "sim-to-real", "sim2real"],
    "Imitation_Learning": ["imitation learning", "behavior cloning", "behavioral cloning", "demonstration",
                           "diffusion policy", "flow matching", "action chunking"],
    "Perception_3D_Representations": ["point cloud", "3d", "gaussian splatting", "nerf", "pose estimation",
                                      "scene graph", "segmentation", "keypoint", "correspondence",
                                      "representation learning"],
    "HRI_Feedback_Interaction": ["human-robot interaction", "hri", "human feedback", "preference",
                                 "shared autonomy", "assistive", "intervention", "correction", "collaboration"],
    "Data_Simulation_Benchmarks": ["dataset", "benchmark", "simulation", "simulator", "data collection",
                                   "teleoperation", "data generation", "synthetic data", "real-to-sim",
                                   "digital twin"],
    "Safety_Uncertainty_Failure": ["safety", "safe", "uncertainty", "failure", "risk", "conformal",
                                   "out-of-distribution", "ood", "anomaly", "verification"],
    "Planning_Reasoning_Hierarchy": ["task and motion planning", "tamp", "motion planning", "planning",
                                     "long-horizon", "reasoning", "hierarchical", "skill"],
    "Hardware_Design": ["hardware", "co-design", "morphology", "gripper design", "soft robot",
                        "end-effector", "low-cost"],
}
PATTERNS = {cat: [re.compile(r"\b" + re.escape(p) + r"(?:s|es)?\b") for p in phrases]
            for cat, phrases in TAXONOMY.items()}


def classify(title, abstract, keywords):
    fields = [(title.lower(), 3), (" ; ".join(keywords).lower(), 2), (abstract.lower(), 1)]
    scores = Counter()
    for cat, pats in PATTERNS.items():  # each field counts once per category, so long synonym lists don't win
        scores[cat] = sum(w for text, w in fields if any(p.search(text) for p in pats))
    ranked = [c for c, s in scores.most_common() if s > 0]
    return (ranked[0] if ranked else FALLBACK), ranked


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


class RateLimited(RuntimeError):
    def __init__(self, wait, url):
        super().__init__(f"rate-limited for {wait}s: {url}")
        self.wait = wait


def http_get(url, token=None, raw=False, retries=5, max_wait=600):
    headers = {"User-Agent": "corl2026-downloader"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    last = "unknown error"
    for attempt in range(retries):
        wait = min(2 ** (attempt + 1), 120)  # 2, 4, 8, 16, 32 s unless the server says otherwise
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            last = f"HTTP {e.code}"
            retry_after = e.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = int(retry_after) + 1
                if wait > max_wait:  # long cooldown: let the caller try another source
                    raise RateLimited(wait, url)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = f"network: {getattr(e, 'reason', e)}"
        if attempt < retries - 1:
            print(f"    {last} from {urllib.parse.urlparse(url).netloc}; retrying in {wait}s "
                  f"({attempt + 1}/{retries - 1})", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"gave up after {retries} attempts ({last}): {url}")


def download_pdf(note_id, token):
    """Public web URL first, API as fallback. If every source asks for a long cooldown,
    wait for the soonest one to reset and try again."""
    sources = [(f"https://openreview.net/pdf?id={note_id}", None),
               (f"{API}/attachment?" + urllib.parse.urlencode({"id": note_id, "name": "pdf"}), token)]
    while True:
        errors, waits = [], []
        for url, tok in sources:
            try:
                pdf = http_get(url, tok, raw=True, max_wait=60)
                if pdf.startswith(b"%PDF"):
                    return pdf
                errors.append(f"not a PDF from {urllib.parse.urlparse(url).netloc}")
            except RateLimited as e:
                waits.append(e.wait)
            except Exception as e:
                errors.append(str(e))
        if not waits:
            raise RuntimeError(" | ".join(errors))
        print(f"    all sources rate-limited; waiting {min(waits)}s", flush=True)
        time.sleep(min(waits))


def login():
    user, pw = os.environ.get("OPENREVIEW_USERNAME"), os.environ.get("OPENREVIEW_PASSWORD")
    if not (user and pw):
        return None
    req = urllib.request.Request(f"{API}/login", data=json.dumps({"id": user, "password": pw}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["token"]


def fetch_accepted(token):
    notes, offset, limit = [], 0, 1000
    while True:
        q = urllib.parse.urlencode({"content.venueid": VENUE_ID, "offset": offset, "limit": limit})
        batch = http_get(f"{API}/notes?{q}", token)["notes"]
        notes += batch
        if len(batch) < limit:
            return notes
        offset += limit


def val(note, key, default=""):
    v = note.get("content", {}).get(key)
    if isinstance(v, dict):
        v = v.get("value")
    return v if v else default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="CoRL2026", help="output folder (default: CoRL2026)")
    ap.add_argument("--dry-run", action="store_true", help="write index.csv and print counts, no PDFs")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between PDF downloads (default 3)")
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch metadata and re-sort (needed after editing TAXONOMY; "
                         "papers whose folder changes are downloaded again)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = out / "index.csv"
    token = login()
    if index.exists() and not args.refresh:
        with open(index, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        print(f"Resuming from {index} ({len(rows)} papers); no metadata request needed.", flush=True)
    else:
        rows = build_index(token, index)

    print(f"{len(rows)} accepted papers -> {index}")
    for cat, k in Counter(r["category"] for r in rows).most_common():
        print(f"  {k:4d}  {cat}")
    if args.dry_run:
        return
    download_all(rows, out, token, args.delay)


def build_index(token, index):
    print("Fetching paper metadata from OpenReview...", flush=True)
    try:
        notes = fetch_accepted(token)
    except urllib.error.HTTPError as e:
        sys.exit(f"OpenReview refused the request (HTTP {e.code}). "
                 "Set OPENREVIEW_USERNAME / OPENREVIEW_PASSWORD and retry.")
    except RuntimeError as e:
        sys.exit(f"Could not reach OpenReview: {e}")
    if not notes:
        sys.exit(f"No accepted papers found for {VENUE_ID}.")
    rows = []
    for n in notes:
        title = " ".join(val(n, "title").split())
        kws = val(n, "keywords", [])
        kws = [k.strip() for k in kws.split(",")] if isinstance(kws, str) else list(kws)
        area = val(n, "primary_area")
        if area:
            cat, matches = slug(area), [area]
        else:
            cat, matches = classify(title, val(n, "abstract"), kws)
        rows.append({
            "category": cat, "title": title, "venue": val(n, "venue"),
            "authors": ", ".join(val(n, "authors", [])), "keywords": "; ".join(kws),
            "all_matches": "; ".join(matches), "url": f"https://openreview.net/forum?id={n.get('forum', n['id'])}",
            "id": n["id"], "file": f"{cat}/{slug(title)[:90]}_{n['id']}.pdf",
        })
    rows.sort(key=lambda r: (r["category"], r["title"].lower()))
    with open(index, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def download_all(rows, out, token, delay):
    todo = [r for r in rows if not ((out / r["file"]).exists() and (out / r["file"]).stat().st_size > 0)]
    print(f"{len(rows) - len(todo)} already downloaded, {len(todo)} to go.", flush=True)
    failed = streak = 0
    for i, r in enumerate(rows, 1):
        dest = out / r["file"]
        if dest.exists() and dest.stat().st_size > 0:
            continue
        dest.parent.mkdir(exist_ok=True)
        print(f"[{i}/{len(rows)}] downloading {r['title'][:70]}", flush=True)
        try:
            pdf = download_pdf(r["id"], token)
        except Exception as e:
            failed += 1
            streak += 1
            print(f"[{i}/{len(rows)}] FAILED  {r['title'][:70]}  ({e})", flush=True)
            if streak >= 3:
                sys.exit("Stopping: OpenReview keeps refusing. Wait ~15 min and re-run; "
                         "finished PDFs are skipped. Consider a larger --delay.")
            continue
        streak = 0
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(pdf)
        tmp.rename(dest)
        print(f"[{i}/{len(rows)}] saved to {r['category']}/", flush=True)
        time.sleep(delay)
    print(f"Done. {len(rows) - failed} PDFs in {out}" + (f", {failed} failed (re-run to retry)" if failed else ""))


if __name__ == "__main__":
    main()