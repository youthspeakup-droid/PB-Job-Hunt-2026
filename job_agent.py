"""
Daily Job Hunt Agent — Local Version
Searches Reed, Indeed, and Adzuna for Technical Accounting roles
near London / Stevenage, saves an HTML report, and opens it in your browser.

Setup:
  1. pip install requests feedparser
  2. Add your API keys below (Reed is most important; Adzuna optional)
  3. Run: python job_agent.py
  4. Schedule with Task Scheduler (Windows) or cron (Mac) — see README.md
"""

import os, json, re, requests, feedparser, webbrowser
from datetime import date, datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# ✏️  CONFIGURATION
# Keys are read from environment variables so they never get committed.
# Locally: `export REED_API_KEY=...` before running, OR paste between the
# quotes below for quick testing (do NOT commit a copy with real keys).
# In GitHub Actions: set them as repository Secrets — the workflow injects
# them into env: at runtime.
# ─────────────────────────────────────────────────────────────────────────────

REED_API_KEY   = os.environ.get("REED_API_KEY",   "")
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID",  "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

KEYWORDS = [
    "Technical Accounting Manager",
    "Group Technical Accounting Manager",
    "Senior Technical Accounting Manager",
    "Group Reporting Manager",
    "Head of Technical Accounting",
    "Technical Accountant IFRS",
]

LOCATIONS      = ["London", "City of London", "Stevenage", "Hertfordshire"]
MIN_SALARY     = 80000
DISTANCE_MILES = 35

# ─────────────────────────────────────────────────────────────────────────────
# Paths — all files stay in the same folder as this script
# ─────────────────────────────────────────────────────────────────────────────
BASE        = Path(__file__).parent
SEEN_FILE   = BASE / "seen_jobs.json"
REPORT_FILE = BASE / "index.html"   # GitHub Pages serves this as the home page

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_seen() -> dict:
    return json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}

def save_seen(seen: dict):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, default=str))

def clean(text: str, limit: int = 300) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:limit] + "…") if len(text) > limit else text

# ─────────────────────────────────────────────────────────────────────────────
# Sources
# ─────────────────────────────────────────────────────────────────────────────
def search_reed(keyword: str, location: str) -> list:
    if not REED_API_KEY:
        return []
    try:
        r = requests.get(
            "https://www.reed.co.uk/api/1.0/search",
            params=dict(
                keywords=keyword, locationName=location,
                distanceMile=DISTANCE_MILES, minimumSalary=MIN_SALARY,
                resultsToTake=10,
            ),
            auth=(REED_API_KEY, ""), timeout=12,
        )
        jobs = []
        for j in r.json().get("results", []):
            lo, hi = j.get("minimumSalary"), j.get("maximumSalary")
            salary = f"£{int(lo):,}–£{int(hi):,}" if lo else "Not disclosed"
            jobs.append({
                "id":          f"reed_{j['jobId']}",
                "title":       j.get("jobTitle", ""),
                "company":     j.get("employerName", "Unknown"),
                "location":    j.get("locationName", location),
                "salary":      salary,
                "url":         j.get("jobUrl", ""),
                "posted":      (j.get("date") or "")[:10],
                "source":      "Reed",
                "description": clean(j.get("jobDescription", "")),
            })
        return jobs
    except Exception as e:
        print(f"  Reed error ({keyword}/{location}): {e}")
        return []


def search_indeed(keyword: str, location: str) -> list:
    try:
        url = (
            f"https://www.indeed.co.uk/rss"
            f"?q={requests.utils.quote(keyword)}"
            f"&l={requests.utils.quote(location)}"
            f"&radius={DISTANCE_MILES}&fromage=7&sort=date"
        )
        feed = feedparser.parse(url)
        jobs = []
        for entry in feed.entries[:10]:
            jid = entry.get("id", entry.link)
            if "jk=" in jid:
                jid = jid.split("jk=")[-1].split("&")[0]
            jobs.append({
                "id":          f"indeed_{jid}",
                "title":       entry.get("title", ""),
                "company":     "See listing",
                "location":    location,
                "salary":      "See listing",
                "url":         entry.get("link", ""),
                "posted":      (entry.get("published") or "")[:10],
                "source":      "Indeed",
                "description": clean(entry.get("summary", "")),
            })
        return jobs
    except Exception as e:
        print(f"  Indeed error ({keyword}/{location}): {e}")
        return []


def search_adzuna(keyword: str, location: str) -> list:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []
    try:
        r = requests.get(
            "https://api.adzuna.com/v1/api/jobs/gb/search/1",
            params=dict(
                app_id=ADZUNA_APP_ID, app_key=ADZUNA_APP_KEY,
                what=keyword, where=location,
                distance=DISTANCE_MILES, salary_min=MIN_SALARY,
                results_per_page=10, sort_by="date",
            ),
            timeout=12,
        )
        jobs = []
        for j in r.json().get("results", []):
            lo, hi = j.get("salary_min"), j.get("salary_max")
            salary = f"£{int(lo):,}–£{int(hi):,}" if lo else "Not disclosed"
            jobs.append({
                "id":          f"adzuna_{j['id']}",
                "title":       j.get("title", ""),
                "company":     j.get("company", {}).get("display_name", "Unknown"),
                "location":    j.get("location", {}).get("display_name", location),
                "salary":      salary,
                "url":         j.get("redirect_url", ""),
                "posted":      (j.get("created") or "")[:10],
                "source":      "Adzuna",
                "description": clean(j.get("description", "")),
            })
        return jobs
    except Exception as e:
        print(f"  Adzuna error ({keyword}/{location}): {e}")
        return []


def collect_all_jobs() -> list:
    bucket: dict = {}
    for keyword in KEYWORDS:
        for location in LOCATIONS[:2]:   # London + Stevenage is enough
            for job in (
                search_reed(keyword, location)
                + search_indeed(keyword, location)
                + search_adzuna(keyword, location)
            ):
                if job["id"] not in bucket:
                    bucket[job["id"]] = job
    print(f"  Collected {len(bucket)} unique jobs")
    return list(bucket.values())

# ─────────────────────────────────────────────────────────────────────────────
# HTML report builder
# ─────────────────────────────────────────────────────────────────────────────
def build_html(all_jobs: list, new_ids: set) -> str:
    today_str  = date.today().strftime("%A, %d %B %Y")
    jobs_json  = json.dumps(all_jobs, default=str)
    newids_json = json.dumps(list(new_ids))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PB Job Hunt · {today_str}</title>
<style>
  :root {{
    --teal:   #1D9E75;
    --teal-l: #E1F5EE;
    --teal-d: #0F6E56;
    --red:    #E24B4A;
    --blue:   #185FA5;
    --purple: #5B3FA5;
    --bg:     #F4F5F7;
    --card:   #FFFFFF;
    --border: #E5E7EB;
    --text:   #111827;
    --muted:  #6B7280;
    --radius: 10px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg); color: var(--text); min-height: 100vh;
  }}

  /* ── Header ── */
  .header {{
    background: var(--teal); color: #fff;
    padding: 20px 28px; display: flex;
    align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
  }}
  .header h1 {{ font-size: 18px; font-weight: 700; }}
  .header p  {{ font-size: 13px; opacity: .8; margin-top: 2px; }}
  .stats-row {{
    display: flex; gap: 8px; flex-wrap: wrap;
  }}
  .stat {{
    background: rgba(255,255,255,.15); border-radius: 8px;
    padding: 6px 14px; text-align: center;
  }}
  .stat .n {{ font-size: 20px; font-weight: 700; }}
  .stat .l {{ font-size: 10px; opacity: .8; text-transform: uppercase; letter-spacing: .5px; }}

  /* ── Toolbar ── */
  .toolbar {{
    background: #fff; border-bottom: 1px solid var(--border);
    padding: 12px 28px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
  }}
  .toolbar input {{
    flex: 1; min-width: 200px; padding: 8px 12px;
    border: 1px solid var(--border); border-radius: 8px;
    font-size: 13px; outline: none;
  }}
  .toolbar input:focus {{ border-color: var(--teal); }}
  .tab-btn {{
    padding: 7px 14px; border-radius: 8px; border: 1px solid var(--border);
    background: #fff; font-size: 13px; cursor: pointer; color: var(--muted);
    transition: all .15s;
  }}
  .tab-btn.active {{ background: var(--teal-l); color: var(--teal-d); border-color: var(--teal); font-weight: 600; }}
  .restore-btn {{
    padding: 7px 14px; border-radius: 8px; border: 1px solid var(--border);
    background: #fff; font-size: 13px; cursor: pointer; color: var(--muted);
  }}
  .restore-btn:hover {{ background: #fef2f2; color: var(--red); border-color: var(--red); }}

  /* ── Content ── */
  .content {{ max-width: 820px; margin: 0 auto; padding: 24px 20px; }}
  .section-label {{
    font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .8px; color: var(--muted); margin-bottom: 12px;
    display: flex; align-items: center; gap: 8px;
  }}
  .section-label span {{
    flex: 1; height: 1px; background: var(--border);
  }}

  /* ── Job card ── */
  .card {{
    background: var(--card); border: 1.5px solid var(--border);
    border-radius: var(--radius); padding: 16px 18px;
    margin-bottom: 12px; transition: box-shadow .15s;
    animation: fadeIn .25s ease;
  }}
  @keyframes fadeIn {{ from {{ opacity:0; transform:translateY(6px) }} to {{ opacity:1; transform:none }} }}
  .card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.07); }}
  .card.new  {{ border-color: var(--teal); }}
  .card.hidden {{ display: none; }}

  .card-top {{
    display: flex; justify-content: space-between;
    align-items: flex-start; gap: 10px; margin-bottom: 10px;
  }}
  .card-title {{ font-size: 15px; font-weight: 600; line-height: 1.3; }}
  .card-meta  {{
    font-size: 12px; color: var(--muted); margin-top: 4px;
    display: flex; flex-wrap: wrap; gap: 10px;
  }}
  .card-meta span {{ display: flex; align-items: center; gap: 4px; }}
  .card-right {{ display: flex; gap: 6px; align-items: flex-start; flex-shrink: 0; }}

  .badge {{
    font-size: 11px; font-weight: 600; padding: 3px 9px;
    border-radius: 20px; white-space: nowrap;
  }}
  .badge-new    {{ background: var(--teal-l); color: var(--teal-d); }}
  .badge-reed   {{ background: #E6F1FB; color: var(--blue); }}
  .badge-indeed {{ background: #FEE8E8; color: var(--red); }}
  .badge-adzuna {{ background: #EEE8FC; color: var(--purple); }}

  .dismiss-btn {{
    background: none; border: 1px solid var(--border);
    border-radius: 6px; cursor: pointer;
    color: var(--muted); font-size: 14px; padding: 3px 7px;
    transition: all .15s; line-height: 1;
  }}
  .dismiss-btn:hover {{ background: #fef2f2; color: var(--red); border-color: var(--red); }}

  .card-desc {{
    font-size: 13px; color: #444; line-height: 1.6;
    margin-bottom: 13px;
  }}
  .apply-btn {{
    display: inline-block; background: var(--teal); color: #fff;
    padding: 7px 16px; border-radius: 7px; font-size: 13px;
    font-weight: 600; text-decoration: none;
    transition: background .15s;
  }}
  .apply-btn:hover {{ background: var(--teal-d); }}
  .posted {{ font-size: 11px; color: var(--muted); margin-left: 10px; }}

  /* ── Save button ── */
  .save-btn {{
    background: none; border: 1px solid var(--border);
    border-radius: 6px; cursor: pointer;
    color: var(--muted); font-size: 14px; padding: 3px 7px;
    transition: all .15s; line-height: 1;
  }}
  .save-btn:hover  {{ background: #fffbeb; color: #b45309; border-color: #f59e0b; }}
  .save-btn.saved  {{ background: #fffbeb; color: #b45309; border-color: #f59e0b; }}
  .badge-saved     {{ background: #fffbeb; color: #b45309; }}

  /* ── Saved section ── */
  #saved-section {{ margin-top: 32px; }}

  /* ── Dismissed section ── */
  #dismissed-section {{ margin-top: 32px; }}
  .dismissed-card {{
    opacity: .5; border-style: dashed;
  }}
  .dismissed-card .card-title {{ text-decoration: line-through; }}

  /* ── Empty ── */
  .empty {{
    text-align: center; padding: 48px 20px; color: var(--muted); font-size: 14px;
  }}

  /* ── Footer ── */
  .footer {{
    text-align: center; padding: 24px;
    font-size: 12px; color: var(--muted);
  }}

  /* ── Undo toast ── */
  #undo-toast {{
    position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
    background: #1f2937; color: #fff;
    padding: 12px 20px; border-radius: 10px;
    font-size: 13px; display: flex; align-items: center; gap: 14px;
    box-shadow: 0 4px 20px rgba(0,0,0,.25);
    opacity: 0; pointer-events: none;
    transition: opacity .2s ease;
    z-index: 999; white-space: nowrap;
  }}
  #undo-toast.show {{ opacity: 1; pointer-events: auto; }}
  #undo-toast-bar {{
    position: absolute; bottom: 0; left: 0;
    height: 3px; background: var(--teal); border-radius: 0 0 10px 10px;
    width: 100%; transition: width linear;
  }}
  .undo-btn {{
    background: var(--teal); color: #fff; border: none;
    padding: 5px 12px; border-radius: 6px;
    font-size: 12px; font-weight: 600; cursor: pointer;
  }}
  .undo-btn:hover {{ background: var(--teal-d); }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📋 PB Job Hunt</h1>
    <p>{today_str} · Technical Accounting · London / Stevenage corridor</p>
  </div>
  <div class="stats-row">
    <div class="stat"><div class="n" id="stat-new">–</div><div class="l">New today</div></div>
    <div class="stat"><div class="n" id="stat-total">–</div><div class="l">Total</div></div>
    <div class="stat"><div class="n" id="stat-saved">–</div><div class="l">Saved</div></div>
    <div class="stat"><div class="n" id="stat-dismissed">–</div><div class="l">Dismissed</div></div>
  </div>
</div>

<div class="toolbar">
  <input type="text" id="searchBox" placeholder="Filter jobs by keyword, company, location…" oninput="render()">
  <button class="tab-btn active" id="tab-all"   onclick="setTab('all')">All jobs</button>
  <button class="tab-btn"        id="tab-new"   onclick="setTab('new')">New today</button>
  <button class="tab-btn"        id="tab-saved" onclick="setTab('saved')">🔖 Saved</button>
  <button class="restore-btn"                   onclick="restoreAll()">↩ Restore all dismissed</button>
</div>

<div class="content">
  <div id="jobs-container"></div>
  <div id="saved-section" style="display:none;">
    <div class="section-label">🔖 Saved jobs <span></span></div>
    <div id="saved-container"></div>
  </div>
  <div id="dismissed-section" style="display:none;">
    <div class="section-label">Dismissed <span></span></div>
    <div id="dismissed-container"></div>
  </div>
</div>

<div class="footer">
  Sources: Reed · Indeed · Adzuna &nbsp;·&nbsp; Refreshed daily at 8 AM &nbsp;·&nbsp;
  Click ✕ on any card to dismiss it — it won't reappear tomorrow.
</div>

<div id="undo-toast">
  <span id="undo-msg">Job dismissed</span>
  <button class="undo-btn" onclick="undoDismiss()">Undo</button>
  <div id="undo-toast-bar"></div>
</div>

<script>
// ── Data injected by Python ──────────────────────────────────────────────────
const ALL_JOBS = {jobs_json};
const NEW_IDS  = new Set({newids_json});

// ── Persistent state (localStorage) ─────────────────────────────────────────
const DISMISSED_KEY = 'jh_dismissed_v1';
const SAVED_KEY     = 'jh_saved_v2';  // v2 — now stores {{id: timestamp}}

let dismissed = new Set(JSON.parse(localStorage.getItem(DISMISSED_KEY) || '[]'));
let saved     = JSON.parse(localStorage.getItem(SAVED_KEY) || '{{}}');  // {{id: "DD MMM YYYY, HH:MM"}}
let currentTab  = 'all';

// ── Persist helpers ──────────────────────────────────────────────────────────
function persistDismissed() {{ localStorage.setItem(DISMISSED_KEY, JSON.stringify([...dismissed])); }}
function persistSaved()     {{ localStorage.setItem(SAVED_KEY,     JSON.stringify(saved));          }}

function formatNow() {{
  const d = new Date();
  const day  = String(d.getDate()).padStart(2,'0');
  const mon  = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getMonth()];
  const yr   = d.getFullYear();
  const hr   = String(d.getHours()).padStart(2,'0');
  const min  = String(d.getMinutes()).padStart(2,'0');
  return `${{day}} ${{mon}} ${{yr}}, ${{hr}}:${{min}}`;
}}

// ── Actions ──────────────────────────────────────────────────────────────────
// ── Undo toast ──────────────────────────────────────────────────────────────
let lastDismissed = null;
let undoTimer     = null;
const UNDO_SECS   = 10;

function dismiss(id) {{
  lastDismissed = id;
  dismissed.add(id);
  persistDismissed();
  render();
  showUndoToast();
}}

function restore(id) {{
  dismissed.delete(id);
  persistDismissed();
  render();
}}

function undoDismiss() {{
  if (!lastDismissed) return;
  dismissed.delete(lastDismissed);
  persistDismissed();
  lastDismissed = null;
  hideUndoToast();
  render();
}}

function showUndoToast() {{
  clearTimeout(undoTimer);
  const toast = document.getElementById('undo-toast');
  const bar   = document.getElementById('undo-toast-bar');
  toast.classList.add('show');
  bar.style.transition = 'none';
  bar.style.width = '100%';
  bar.getBoundingClientRect();
  bar.style.transition = 'width ' + UNDO_SECS + 's linear';
  bar.style.width = '0%';
  undoTimer = setTimeout(function() {{ hideUndoToast(); lastDismissed = null; }}, UNDO_SECS * 1000);
}}

function hideUndoToast() {{
  clearTimeout(undoTimer);
  document.getElementById('undo-toast').classList.remove('show');
}}
function toggleSave(id) {{
  if (saved[id]) delete saved[id]; else saved[id] = formatNow();
  persistSaved();
  render();
}}
function restoreAll() {{
  if (!confirm('Restore all dismissed jobs?')) return;
  dismissed.clear(); persistDismissed(); render();
}}

function setTab(tab) {{
  currentTab = tab;
  ['all','new','saved'].forEach(t =>
    document.getElementById('tab-' + t).classList.toggle('active', t === tab)
  );
  render();
}}

// ── Badge helpers ─────────────────────────────────────────────────────────────
function srcBadge(source) {{
  const cls = {{'Reed':'reed','Indeed':'indeed','Adzuna':'adzuna'}}[source] || 'reed';
  return `<span class="badge badge-${{cls}}">${{source}}</span>`;
}}

// ── Card builder ──────────────────────────────────────────────────────────────
function cardHTML(job, mode) {{
  // mode: 'normal' | 'saved' | 'dismissed'
  const isDismissed = mode === 'dismissed';
  const isSaved     = !!saved[job.id];
  const isNew       = NEW_IDS.has(job.id);
  const savedAt     = saved[job.id] || '';

  const newBadge   = isNew  ? `<span class="badge badge-new">NEW</span> ` : '';
  const savedBadge = isSaved && mode !== 'dismissed' ? `<span class="badge badge-saved">🔖 Saved</span> ` : '';

  const saveCls   = isSaved ? 'save-btn saved' : 'save-btn';
  const saveTitle = isSaved ? 'Remove from saved' : 'Save this job';

  const dismissBtn = isDismissed
    ? `<button class="dismiss-btn" title="Restore" onclick="restore('${{job.id}}')">↩</button>`
    : `<button class="dismiss-btn" title="Dismiss"  onclick="dismiss('${{job.id}}')">✕</button>`;

  const saveBtn = isDismissed ? '' :
    `<button class="${{saveCls}}" title="${{saveTitle}}" onclick="toggleSave('${{job.id}}')">🔖</button>`;

  const savedTimestamp = isSaved && mode !== 'dismissed'
    ? `<span style="font-size:11px;color:#b45309;margin-left:10px;">🕐 Saved on ${{savedAt}}</span>`
    : '';

  return `
  <div class="card${{isNew && !isDismissed ? ' new' : ''}}${{isDismissed ? ' dismissed-card' : ''}}">
    <div class="card-top">
      <div>
        <div class="card-title">${{newBadge}}${{savedBadge}}${{job.title}}</div>
        <div class="card-meta">
          <span>🏢 ${{job.company}}</span>
          <span>📍 ${{job.location}}</span>
          <span>💷 ${{job.salary}}</span>
        </div>
      </div>
      <div class="card-right">
        ${{srcBadge(job.source)}}
        ${{saveBtn}}
        ${{dismissBtn}}
      </div>
    </div>
    <p class="card-desc">${{job.description}}</p>
    <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;">
      <a class="apply-btn" href="${{job.url}}" target="_blank" rel="noopener">View &amp; Apply →</a>
      ${{job.posted ? `<span class="posted">Posted ${{job.posted}}</span>` : ''}}
      ${{savedTimestamp}}
    </div>
  </div>`;}}

// ── Render ────────────────────────────────────────────────────────────────────
function render() {{
  const query       = document.getElementById('searchBox').value.toLowerCase();
  const active      = ALL_JOBS.filter(j => !dismissed.has(j.id));
  const savedJobs   = ALL_JOBS.filter(j =>  saved[j.id]);  // saved regardless of dismissed state
  const dismissedJs = ALL_JOBS.filter(j =>  dismissed.has(j.id) && !saved[j.id]); // dismissed but not saved

  // Stats
  document.getElementById('stat-new').textContent       = ALL_JOBS.filter(j => NEW_IDS.has(j.id) && !dismissed.has(j.id)).length;
  document.getElementById('stat-total').textContent     = active.length;
  document.getElementById('stat-saved').textContent     = savedJobs.length;
  document.getElementById('stat-dismissed').textContent = dismissedJs.length;

  // Which jobs to show in main area
  let visible = active;
  if (currentTab === 'new')   visible = active.filter(j => NEW_IDS.has(j.id));
  if (currentTab === 'saved') visible = savedJobs;
  if (query) visible = visible.filter(j =>
    [j.title, j.company, j.location, j.description, j.source].join(' ').toLowerCase().includes(query)
  );

  // Main container
  const container = document.getElementById('jobs-container');
  container.innerHTML = visible.length
    ? visible.map(j => cardHTML(j, 'normal')).join('')
    : `<div class="empty">${{
        currentTab === 'saved'
          ? '🔖 No saved jobs yet — click the bookmark icon on any listing to save it.'
          : 'No jobs match your current filter.'
      }}</div>`;

  // Saved section (only shown in All / New tabs, below main list)
  const ss = document.getElementById('saved-section');
  const sc = document.getElementById('saved-container');
  if (savedJobs.length > 0 && currentTab !== 'saved') {{
    ss.style.display = 'block';
    sc.innerHTML = savedJobs.map(j => cardHTML(j, 'saved')).join('');
  }} else {{
    ss.style.display = 'none';
  }}

  // Dismissed section
  const ds = document.getElementById('dismissed-section');
  const dc = document.getElementById('dismissed-container');
  if (dismissedJs.length > 0) {{
    ds.style.display = 'block';
    dc.innerHTML = dismissedJs.map(j => cardHTML(j, 'dismissed')).join('');
  }} else {{
    ds.style.display = 'none';
  }}
}}

render();
</script>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print(f"=== Daily Job Hunt — {date.today()} ===")

    seen = load_seen()
    print(f"  Previously seen: {len(seen)} jobs")

    print("Searching Reed, Indeed, Adzuna…")
    all_jobs = collect_all_jobs()

    # Which jobs are new (not in seen)?
    new_ids = {j["id"] for j in all_jobs if j["id"] not in seen}
    print(f"  New jobs: {len(new_ids)}")

    # Update seen tracker
    today = str(date.today())
    for job in all_jobs:
        if job["id"] not in seen:
            seen[job["id"]] = {**job, "first_seen": today}
    save_seen(seen)

    # Build HTML (include all ever-seen jobs so dismissed ones still appear in UI)
    all_tracked = list(seen.values())
    html = build_html(all_tracked, new_ids)
    REPORT_FILE.write_text(html, encoding="utf-8")
    print(f"  Report saved: {REPORT_FILE}")

    # Open in default browser — only when running locally. In CI (GitHub
    # Actions) there's no browser, so skip the open and just exit cleanly.
    if not os.environ.get("CI"):
        webbrowser.open(REPORT_FILE.as_uri())
    print("=== Done ===")

if __name__ == "__main__":
    main()
