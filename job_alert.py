"""
job_alert.py
Monitors job postings for roles matched to Amber's background.
Uses Google Custom Search API to search across multiple job boards.
Emails only NEW listings with fit-tier badges (Best / Strong / Good).
Runs every 2 hours, 6am-6pm CT via GitHub Actions.
"""

import os
import json
import smtplib
import datetime
import hashlib
import signal
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Config (GitHub Actions secrets) ───────────────────────────────────────────
EMAIL_SENDER   = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO       = os.environ["EMAIL_TO"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CSE_ID  = os.environ["GOOGLE_CSE_ID"]

SEEN_FILE = "seen_jobs.json"

NOW   = datetime.datetime.now()
TODAY = NOW.strftime("%B %d, %Y")
TIME  = NOW.strftime("%I:%M %p")

# ── Timeout config ─────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 10
MAX_TOTAL_SECONDS = 300

def _timeout_handler(signum, frame):
    raise TimeoutError("Total run time exceeded 5 minutes — exiting cleanly.")

signal.signal(signal.SIGALRM, _timeout_handler)
signal.alarm(MAX_TOTAL_SECONDS)

# ── Search Targets ─────────────────────────────────────────────────────────────
SEARCHES = [

    # BEST FIT — Compliance Testing Analyst
    {
        "category": "Compliance Testing",
        "fit": "best",
        "label": "Compliance Testing Analyst — Des Moines",
        "query": '"compliance testing analyst" "Des Moines"',
    },
    {
        "category": "Compliance Testing",
        "fit": "best",
        "label": "Compliance Testing Analyst — Remote",
        "query": '"compliance testing analyst" remote',
    },
    {
        "category": "Compliance Testing",
        "fit": "best",
        "label": "Compliance Testing — Financial Services",
        "query": '"compliance testing" "financial services" (remote OR "Des Moines")',
    },

    # STRONG FIT — Internal Auditor
    {
        "category": "Internal Audit",
        "fit": "strong",
        "label": "Internal Auditor — Des Moines",
        "query": '"internal auditor" "Des Moines"',
    },
    {
        "category": "Internal Audit",
        "fit": "strong",
        "label": "Internal Auditor — Remote",
        "query": '"internal auditor" remote "financial services"',
    },
    {
        "category": "Internal Audit",
        "fit": "strong",
        "label": "Audit Analyst — Des Moines or Remote",
        "query": '"audit analyst" (remote OR "Des Moines") "financial"',
    },

    # STRONG FIT — Controls Testing
    {
        "category": "Controls Testing",
        "fit": "strong",
        "label": "Controls Testing Analyst — Des Moines or Remote",
        "query": '"controls testing" analyst (remote OR "Des Moines")',
    },
    {
        "category": "Controls Testing",
        "fit": "strong",
        "label": "SOX Controls Testing — Remote",
        "query": 'SOX "controls testing" remote',
    },

    # STRONG FIT — Compliance Monitoring
    {
        "category": "Compliance Monitoring",
        "fit": "strong",
        "label": "Compliance Monitoring Analyst — Des Moines or Remote",
        "query": '"compliance monitoring" analyst (remote OR "Des Moines")',
    },
    {
        "category": "Compliance Monitoring",
        "fit": "strong",
        "label": "Compliance Coordinator — Des Moines or Remote",
        "query": '"compliance coordinator" (remote OR "Des Moines") "financial"',
    },

    # GOOD FIT — QA Specialist
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "QA Specialist — Des Moines",
        "query": '"QA specialist" OR "quality assurance specialist" "Des Moines"',
    },
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "QA Analyst — Remote Financial Services",
        "query": '"QA analyst" OR "quality assurance analyst" remote "financial"',
    },
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "Process Improvement Analyst — Des Moines or Remote",
        "query": '"process improvement analyst" (remote OR "Des Moines")',
    },

    # GOOD FIT — Reporting Analyst
    {
        "category": "Reporting Analyst",
        "fit": "good",
        "label": "Reporting Analyst — Des Moines",
        "query": '"reporting analyst" "Des Moines"',
    },
    {
        "category": "Reporting Analyst",
        "fit": "good",
        "label": "Reporting Analyst — Remote Financial",
        "query": '"reporting analyst" remote "financial services" OR banking OR insurance',
    },
    {
        "category": "Reporting Analyst",
        "fit": "good",
        "label": "Operations Support Analyst — Des Moines or Remote",
        "query": '"operations support analyst" OR "business analyst" (remote OR "Des Moines") "financial"',
    },
]

# ── Fit tier display config ────────────────────────────────────────────────────
FIT_CONFIG = {
    "best":   {"label": "★ Best fit",   "bg": "#dcfce7", "color": "#166534", "border": "#86efac", "hdr": "#15803d"},
    "strong": {"label": "◆ Strong fit", "bg": "#dbeafe", "color": "#1e40af", "border": "#93c5fd", "hdr": "#1d4ed8"},
    "good":   {"label": "● Good fit",   "bg": "#fef9c3", "color": "#854d0e", "border": "#fde047", "hdr": "#a16207"},
}

CATEGORY_ORDER = [
    "Compliance Testing",
    "Internal Audit",
    "Controls Testing",
    "Compliance Monitoring",
    "QA Specialist",
    "Reporting Analyst",
]

# ── Seen Job Tracking ─────────────────────────────────────────────────────────

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def job_id(link):
    return hashlib.md5(link.encode()).hexdigest()

# ── Google Custom Search ───────────────────────────────────────────────────────

def fetch_jobs(search, seen):
    params = {
        "key": GOOGLE_API_KEY,
        "cx":  GOOGLE_CSE_ID,
        "q":   search["query"],
        "num": 10,
        "dateRestrict": "d1",
    }
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  WARNING: Could not fetch {search['label']}: {e}")
        return [], set()

    new_jobs = []
    new_ids  = set()

    for item in data.get("items", []):
        link = item.get("link", "")
        jid  = job_id(link)
        if not link or jid in seen:
            continue

        title   = item.get("title", "No title")
        snippet = item.get("snippet", "")

        pagemap  = item.get("pagemap", {})
        metatags = pagemap.get("metatags", [{}])[0]
        company  = (
            metatags.get("og:site_name") or
            metatags.get("twitter:site") or ""
        )

        for suffix in [" - Indeed", " | Indeed", " - LinkedIn", " | LinkedIn",
                       " - ZipRecruiter", " | ZipRecruiter", " - Glassdoor",
                       " | Glassdoor", " - Workday", " | Workday"]:
            if title.endswith(suffix):
                title = title[:-len(suffix)].strip()
                break

        new_jobs.append({
            "title":   title,
            "link":    link,
            "company": company,
            "snippet": snippet[:120] + "..." if len(snippet) > 120 else snippet,
        })
        new_ids.add(jid)

    return new_jobs, new_ids

# ── Email Builder ──────────────────────────────────────────────────────────────

def build_html(all_results, total_new):
    categories = {cat: [] for cat in CATEGORY_ORDER}
    fit_lookup = {}
    for search, jobs in all_results:
        cat = search["category"]
        if cat in categories:
            categories[cat].append((search["label"], jobs))
        fit_lookup[cat] = search["fit"]

    sections = ""
    for cat in CATEGORY_ORDER:
        searches = categories[cat]
        fit      = fit_lookup.get(cat, "good")
        cfg      = FIT_CONFIG[fit]

        cards = ""
        found = False
        for label, jobs in searches:
            for job in jobs:
                found = True
                company_html = (
                    f"<div style='color:#475569;font-size:13px;margin-top:2px;"
                    f"font-weight:500;'>{job['company']}</div>"
                    if job["company"] else ""
                )
                cards += f"""
                <div style="border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;
                            margin-bottom:10px;background:#ffffff;">
                  <a href="{job['link']}" style="color:#1a3a5c;font-weight:600;font-size:15px;
                     text-decoration:none;line-height:1.4;">{job['title']}</a>
                  {company_html}
                  <div style="color:#64748b;font-size:12px;margin-top:4px;line-height:1.5;">
                    {job['snippet']}
                  </div>
                  <div style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    <span style="background:{cfg['bg']};color:{cfg['color']};
                                 border:1px solid {cfg['border']};font-size:11px;font-weight:600;
                                 padding:2px 9px;border-radius:12px;">{cfg['label']}</span>
                    <span style="color:#94a3b8;font-size:11px;">{label}</span>
                  </div>
                </div>"""

        if not found:
            continue

        sections += f"""
        <div style="margin-bottom:24px;">
          <div style="background:{cfg['hdr']};color:#fff;padding:9px 16px;
                      border-radius:8px 8px 0 0;font-size:13px;font-weight:700;
                      display:flex;align-items:center;justify-content:space-between;">
            <span>{cat}</span>
            <span style="opacity:.8;font-weight:400;font-size:11px;">{cfg['label']}</span>
          </div>
          <div style="border:1px solid #e2e8f0;border-top:none;
                      border-radius:0 0 8px 8px;padding:14px;">{cards}</div>
        </div>"""

    if not sections:
        sections = '<p style="color:#94a3b8;text-align:center;font-size:13px;">No new listings found this run.</p>'

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<div style="max-width:640px;margin:30px auto;">
  <div style="background:#1a3a5c;color:#fff;padding:22px 28px;
              border-radius:10px 10px 0 0;text-align:center;">
    <div style="font-size:22px;font-weight:700;">Job Alert</div>
    <div style="font-size:13px;opacity:.75;margin-top:4px;">
      {TODAY} &nbsp;&middot;&nbsp; {TIME} &nbsp;&middot;&nbsp;
      {total_new} new listing{"s" if total_new != 1 else ""}
    </div>
    <div style="margin-top:12px;display:flex;justify-content:center;gap:10px;flex-wrap:wrap;">
      <span style="background:#dcfce7;color:#166534;border:1px solid #86efac;
                   font-size:11px;font-weight:600;padding:2px 10px;border-radius:12px;">★ Best fit</span>
      <span style="background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;
                   font-size:11px;font-weight:600;padding:2px 10px;border-radius:12px;">◆ Strong fit</span>
      <span style="background:#fef9c3;color:#854d0e;border:1px solid #fde047;
                   font-size:11px;font-weight:600;padding:2px 10px;border-radius:12px;">● Good fit</span>
    </div>
  </div>
  <div style="background:#f8fafc;padding:24px 28px;border:1px solid #e2e8f0;
              border-top:none;border-radius:0 0 10px 10px;">
    {sections}
    <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">
    <p style="font-size:11px;color:#94a3b8;text-align:center;margin:0;">
      Sent by your GitHub Actions job alert &nbsp;&middot;&nbsp;
      Powered by Google Custom Search &nbsp;&middot;&nbsp;
      Runs every 2 hours, 6am&ndash;6pm CT
    </p>
  </div>
</div>
</body></html>"""

# ── Email Sender ───────────────────────────────────────────────────────────────

def send_email(html, total_new):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Alert: {total_new} New Listing{'s' if total_new != 1 else ''} — {TODAY} {TIME}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_TO, msg.as_string())
    print(f"Email sent: {total_new} new listing(s)")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    seen        = load_seen()
    all_results = []
    all_new_ids = set()
    total_new   = 0

    for search in SEARCHES:
        print(f"Checking: {search['label']}")
        jobs, new_ids = fetch_jobs(search, seen)
        all_results.append((search, jobs))
        all_new_ids.update(new_ids)
        total_new += len(jobs)
        if jobs:
            print(f"  -> {len(jobs)} new listing(s)")

    if total_new == 0:
        print("No new listings this run — no email sent.")
        save_seen(seen | all_new_ids)
        return

    html = build_html(all_results, total_new)
    send_email(html, total_new)
    save_seen(seen | all_new_ids)

if __name__ == "__main__":
    try:
        main()
    except TimeoutError as e:
        print(f"WARNING: {e}")
