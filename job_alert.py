"""
job_alert.py
Monitors Indeed RSS feeds for roles matched to Amber's background.
Emails only NEW listings with fit-tier badges (Best / Strong / Good).
Runs every 2 hours, 6am–6pm CT via GitHub Actions.
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
from bs4 import BeautifulSoup

# ── Timeout config ─────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 10       # seconds per individual HTTP request
MAX_TOTAL_SECONDS = 300      # 5 minute hard cap on the entire run

def _timeout_handler(signum, frame):
    raise TimeoutError("Total run time exceeded 5 minutes — exiting cleanly.")

signal.signal(signal.SIGALRM, _timeout_handler)
signal.alarm(MAX_TOTAL_SECONDS)

# ── Config (GitHub Actions secrets) ───────────────────────────────────────────
EMAIL_SENDER   = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_TO       = os.environ["EMAIL_TO"]

SEEN_FILE = "seen_jobs.json"

NOW   = datetime.datetime.now()
TODAY = NOW.strftime("%B %d, %Y")
TIME  = NOW.strftime("%I:%M %p")

# ── Search Targets ─────────────────────────────────────────────────────────────
# fit: "best" | "strong" | "good"
SEARCHES = [

    # ════════════════════════════════════════════════════════════
    #  BEST FIT — Compliance Testing Analyst
    # ════════════════════════════════════════════════════════════
    {
        "category": "Compliance Testing",
        "fit": "best",
        "label": "Compliance Testing Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+testing+analyst&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Compliance Testing",
        "fit": "best",
        "label": "Compliance Testing Analyst — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+testing+analyst&f_WT=2&f_TPR=r86400&format=rss",
    },
    {
        "category": "Compliance Testing",
        "fit": "best",
        "label": "Compliance Testing — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+testing&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Compliance Testing",
        "fit": "best",
        "label": "Compliance Testing — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+testing&f_WT=2&f_TPR=r86400&format=rss",
    },

    # ════════════════════════════════════════════════════════════
    #  STRONG FIT — Internal Auditor
    # ════════════════════════════════════════════════════════════
    {
        "category": "Internal Audit",
        "fit": "strong",
        "label": "Internal Auditor — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=internal+auditor&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Internal Audit",
        "fit": "strong",
        "label": "Internal Auditor — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=internal+auditor&f_WT=2&f_TPR=r86400&format=rss",
    },
    {
        "category": "Internal Audit",
        "fit": "strong",
        "label": "Audit Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=audit+analyst+financial&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Internal Audit",
        "fit": "strong",
        "label": "Audit Analyst — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=audit+analyst+financial&f_WT=2&f_TPR=r86400&format=rss",
    },

    # ════════════════════════════════════════════════════════════
    #  STRONG FIT — Controls Testing Analyst
    # ════════════════════════════════════════════════════════════
    {
        "category": "Controls Testing",
        "fit": "strong",
        "label": "Controls Testing Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=controls+testing+analyst&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Controls Testing",
        "fit": "strong",
        "label": "Controls Testing Analyst — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=controls+testing+analyst&f_WT=2&f_TPR=r86400&format=rss",
    },
    {
        "category": "Controls Testing",
        "fit": "strong",
        "label": "SOX Controls Testing — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=SOX+controls+testing&f_WT=2&f_TPR=r86400&format=rss",
    },

    # ════════════════════════════════════════════════════════════
    #  STRONG FIT — Compliance Monitoring
    # ════════════════════════════════════════════════════════════
    {
        "category": "Compliance Monitoring",
        "fit": "strong",
        "label": "Compliance Monitoring Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+monitoring+analyst&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Compliance Monitoring",
        "fit": "strong",
        "label": "Compliance Monitoring Analyst — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+monitoring+analyst&f_WT=2&f_TPR=r86400&format=rss",
    },
    {
        "category": "Compliance Monitoring",
        "fit": "strong",
        "label": "Compliance Coordinator — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+coordinator&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Compliance Monitoring",
        "fit": "strong",
        "label": "Compliance Coordinator — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=compliance+coordinator&f_WT=2&f_TPR=r86400&format=rss",
    },

    # ════════════════════════════════════════════════════════════
    #  GOOD FIT — QA Specialist
    # ════════════════════════════════════════════════════════════
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "QA Specialist — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=QA+specialist&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "QA Specialist — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=QA+specialist&f_WT=2&f_TPR=r86400&format=rss",
    },
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "QA Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=QA+analyst&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "QA Analyst — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=QA+analyst&f_WT=2&f_TPR=r86400&format=rss",
    },
    {
        "category": "QA Specialist",
        "fit": "good",
        "label": "Process Improvement Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=process+improvement+analyst&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },

    # ════════════════════════════════════════════════════════════
    #  GOOD FIT — Reporting Analyst
    # ════════════════════════════════════════════════════════════
    {
        "category": "Reporting Analyst",
        "fit": "good",
        "label": "Reporting Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=reporting+analyst&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Reporting Analyst",
        "fit": "good",
        "label": "Reporting Analyst — Remote",
        "url": "https://www.linkedin.com/jobs/search/?keywords=reporting+analyst&f_WT=2&f_TPR=r86400&format=rss",
    },
    {
        "category": "Reporting Analyst",
        "fit": "good",
        "label": "Business Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=business+analyst+financial+services&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
    },
    {
        "category": "Reporting Analyst",
        "fit": "good",
        "label": "Operations Support Analyst — Des Moines",
        "url": "https://www.linkedin.com/jobs/search/?keywords=operations+support+analyst&location=Des+Moines%2C+Iowa&f_TPR=r86400&format=rss",
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

# ── RSS Fetching ───────────────────────────────────────────────────────────────

def fetch_jobs(search, seen):
    headers = {"User-Agent": "Mozilla/5.0 (job-alert-bot/1.0)"}
    try:
        resp = requests.get(search["url"], headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"  WARNING: Could not fetch {search['label']}: {e}")
        return [], set()

    soup = BeautifulSoup(resp.content, "xml")
    new_jobs = []
    new_ids  = set()

    for item in soup.find_all("item")[:10]:
        link = item.find("link").get_text(strip=True) if item.find("link") else ""
        jid  = job_id(link)
        if not link or jid in seen:
            continue

        title    = item.find("title").get_text(strip=True) if item.find("title") else "No title"
        company, location = "", ""
        desc_tag = item.find("description")
        if desc_tag:
            desc_soup = BeautifulSoup(desc_tag.get_text(), "html.parser")
            text = desc_soup.get_text(" ", strip=True)
            if " - " in text:
                parts    = text.split(" - ")
                company  = parts[1].strip() if len(parts) > 1 else ""
                location = parts[2].strip() if len(parts) > 2 else ""

        new_jobs.append({"title": title, "link": link, "company": company, "location": location})
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
                loc_part = f"&nbsp;&nbsp;&middot;&nbsp;&nbsp;{job['location']}" if job["location"] else ""
                cards += f"""
                <div style="border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;
                            margin-bottom:10px;background:#ffffff;">
                  <a href="{job['link']}" style="color:#1a3a5c;font-weight:600;font-size:15px;
                     text-decoration:none;line-height:1.4;">{job['title']}</a>
                  <div style="color:#64748b;font-size:13px;margin-top:3px;">
                    {job['company']}{loc_part}
                  </div>
                  <div style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    <span style="background:{cfg['bg']};color:{cfg['color']};border:1px solid {cfg['border']};
                                 font-size:11px;font-weight:600;padding:2px 9px;border-radius:12px;">
                      {cfg['label']}
                    </span>
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
                      border-radius:0 0 8px 8px;padding:14px;">
            {cards}
          </div>
        </div>"""

    if not sections:
        sections = '<p style="color:#94a3b8;text-align:center;font-size:13px;">No new listings this run.</p>'

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
<div style="max-width:640px;margin:30px auto;">

  <div style="background:#1a3a5c;color:#fff;padding:22px 28px;
              border-radius:10px 10px 0 0;text-align:center;">
    <div style="font-size:22px;font-weight:700;">Job Alert</div>
    <div style="font-size:13px;opacity:.75;margin-top:4px;">
      {TODAY} &nbsp;&middot;&nbsp; {TIME} &nbsp;&middot;&nbsp; {total_new} new listing{"s" if total_new != 1 else ""}
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
      Sent by your GitHub Actions job alert &nbsp;&middot;&nbsp; Sourced from LinkedIn &nbsp;&middot;&nbsp; Runs every 2 hours, 6am&ndash;6pm CT
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
        return

    html = build_html(all_results, total_new)
    send_email(html, total_new)
    save_seen(seen | all_new_ids)

if __name__ == "__main__":
    try:
        main()
    except TimeoutError as e:
        print(f"WARNING: {e}")
