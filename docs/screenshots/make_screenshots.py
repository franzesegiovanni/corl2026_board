"""Regenerate the README / LinkedIn screenshots with headless Chrome (example likes and workshops, not real data).

    python board/build_board.py && python docs/screenshots/make_screenshots.py

The LinkedIn covers come from cover.html: open it with ?f=wide (1200x627) or ?f=tall (1080x1350) and screenshot at 2x.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / "_site"
OUT = Path(__file__).resolve().parent
WORK.mkdir(exist_ok=True); (WORK / "board").mkdir(exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
shutil.copy(REPO / "board" / "abstracts.json", WORK / "board" / "abstracts.json")

LIKED = ["5XKFwWrW0v", "c4Z0Y8gvnI", "gQFYIM5dJy", "0cK9Wf9Eeq", "jnEHLRyWTZ"]
FLAGGED = ["RdvH11pAfJ", "2Z8xQxrlsY", "f5329HhijI", "cvPjGuUATQ", "0cK9Wf9Eeq"]
NOTES = {"RdvH11pAfJ": "Compare their evaluation protocol with ours"}
GOING = ["Continually Self-Improving Robots Workshop (CSIR-2026)",
         "Compositional Generalization for Real-World Robot Learning",
         "Do Robots Need World Models? A Debate on Dynamics Learning, Planning, and End-to-End Robot Learning",
         "The UMI Olympics: From Handheld Devices to Real-World Policies",
         "Pretrain to Adapt: What Makes a Pretrained Policy Adaptable?"]
PEOPLE = ["Shuran Song", "Chelsea Finn", "Danfei Xu"]

marks = {}
for i in LIKED: marks.setdefault(i, {})["l"] = 1
for i in FLAGGED: marks.setdefault(i, {})["f"] = 1
for i, n in NOTES.items(): marks.setdefault(i, {})["n"] = n
for v in marks.values(): v["t"] = 1
seed = {"corl26-board-marks-v1": marks,
        "corl26-board-people-v1": {n: {"l": 1, "t": 1} for n in PEOPLE},
        "corl26-board-going-v1": {t: {"g": 1, "t": 1} for t in GOING}}

PRE = """<script>
(function(){
  var shot = new URLSearchParams(location.search).get('shot') || '';
  var seed = %s;
  try{ for(var k in seed) localStorage.setItem(k, JSON.stringify(seed[k]));
       localStorage.setItem('corl26-board-ui-v1', JSON.stringify({day:'mon', showAbs: /schedule/.test(shot)})); }catch(e){}
})();
</script>""" % json.dumps(seed)

POST = """<script>
(async function(){
  const shot = new URLSearchParams(location.search).get('shot') || '';
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const $ = s => document.querySelector(s);
  await wait(900);
  // headless screenshots ignore scrolling, so hide what sits above the part we want instead
  const top = el => { if(!el) return; document.querySelector('.mast').style.display='none';
    let n = el; const view = document.getElementById('view');
    while(n && n !== view){ let s = n.previousElementSibling; while(s){ s.style.display='none'; s = s.previousElementSibling; } n = n.parentElement; }
    window.scrollTo(0,0); };
  if(shot.startsWith('schedule')){ location.hash='schedule'; await wait(300); if(shot.endsWith('phone')) top($('.dayhead')); }
  if(shot.startsWith('paper')){ location.hash='schedule'; await wait(300); $('.row[data-id="5XKFwWrW0v"] .ttl').click(); }
  if(shot.startsWith('workshops')){ location.hash='workshops'; await wait(300);
    const cards=[...document.querySelectorAll('.ws.card')]; const c=cards.find(x=>/Do Robots Need/.test(x.textContent));
    if(c){ c.querySelector('.wagenda').open=true; } top($('.wslot')); }
  if(shot.startsWith('thursday')){ location.hash='thursday'; await wait(300);
    const t=$('#tprev'); t.value='10:40'; t.dispatchEvent(new Event('change',{bubbles:true})); await wait(300);
    if(shot.endsWith('grid')) top($('#tlwrap')); else if(shot.endsWith('phone')) top($('.tlhead')); }
  if(shot.startsWith('topics')){ location.hash='topics'; await wait(300); top($('.grid2')); }
  if(shot.startsWith('people')){ location.hash='people'; await wait(300);
    const q=$('#aq'); q.value='Shuran Song'; q.dispatchEvent(new Event('input',{bubbles:true})); await wait(150);
    const r=$('#aq-res .arow'); if(r) r.click(); await wait(1600); top($('.people')); }
  if(shot.startsWith('mine')){ location.hash='mine'; await wait(300); top($('.minehead')); }
  document.title='ready';
})();
</script>"""

page = (REPO / "index.html").read_text(encoding="utf-8")
page = page.replace("<head>", "<head>" + PRE, 1).replace("</body>", POST + "</body>", 1)
(WORK / "index.html").write_text(page, encoding="utf-8")

SHOTS = [  # name, width, height, scale
    ("schedule", 1440, 900, 2), ("paper", 1440, 900, 2), ("workshops", 1440, 900, 2),
    ("thursday", 1440, 900, 2), ("thursday-grid", 1440, 900, 2), ("topics", 1440, 900, 2),
    ("people", 1440, 900, 2), ("mine", 1440, 900, 2),
    ("schedule-phone", 390, 844, 3), ("paper-phone", 390, 844, 3), ("thursday-phone", 390, 844, 3),
]
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8790", "--bind", "127.0.0.1"], cwd=WORK,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
try:
    only = sys.argv[1:]
    for name, w, h, sc in SHOTS:
        if only and name not in only:
            continue
        prof = WORK / ("prof_" + name)
        shutil.rmtree(prof, ignore_errors=True)
        out = OUT / f"{name}.png"
        subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                        f"--user-data-dir={prof}", f"--window-size={w},{h}", f"--force-device-scale-factor={sc}",
                        "--virtual-time-budget=9000", f"--screenshot={out}",
                        f"http://127.0.0.1:8790/index.html?shot={name}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        shutil.rmtree(prof, ignore_errors=True)
        print(name, out.stat().st_size // 1024, "KB")
finally:
    srv.terminate()
