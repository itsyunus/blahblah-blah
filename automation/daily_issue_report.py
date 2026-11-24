import csv
import datetime as dt
import html
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = Path(os.environ.get("ISSUES_CSV", "issues.csv"))
OUTPUT = Path(os.environ.get("REPORT_HTML", "daily-report.html"))
TZ = ZoneInfo("Asia/Kolkata")
now = dt.datetime.now(TZ)
END = now.replace(hour=9, minute=0, second=0, microsecond=0)
if now < END:
    END -= dt.timedelta(days=1)
START = END - dt.timedelta(days=1)

def esc(value):
    return html.escape((value or "").strip())

def parse_date(value):
    value = (value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None

days = []
with SOURCE.open(encoding="utf-8-sig", newline="") as source:
    reader = csv.DictReader(source)
    required_columns = {"Date", "Footage Request", "Delivered", "Pending", "Normal", "Critical"}
    missing_columns = required_columns.difference(reader.fieldnames or [])
    if missing_columns:
        raise SystemExit("Video Tracker CSV is missing columns: " + ", ".join(sorted(missing_columns)))
    for row in reader:
        day = parse_date(row.get("Date"))
        if day is None or not (START.date() <= day <= END.date()):
            continue
        values = {name: int(float((row.get(name) or "0").replace(",", "").strip() or 0)) for name in required_columns if name != "Date"}
        days.append({"date": day, **values})
days.sort(key=lambda item: item["date"])

def count(name):
    return sum(item[name] for item in days)

cards = []
for item in days:
    cards.append(f"""<article class="day-card">
      <h2>{item['date'].strftime('%A, %d %b %Y')}</h2>
      <div class="metrics">
        <div class="metric"><b>{item['Footage Request']}</b><span>Footage requests</span></div>
        <div class="metric delivered"><b>{item['Delivered']}</b><span>Delivered</span></div>
        <div class="metric pending"><b>{item['Pending']}</b><span>Pending</span></div>
        <div class="metric"><b>{item['Normal']}</b><span>Normal</span></div>
        <div class="metric critical"><b>{item['Critical']}</b><span>Critical</span></div>
      </div>
    </article>""")

if days:
    summary = f"{count('Footage Request')} footage requests · {count('Delivered')} delivered · {count('Pending')} pending"
else:
    summary = "No daily footage totals were found for the report dates."
window_note = "The Video Tracker records totals by calendar date, not by time. The selected date totals cannot be split precisely at the 9 AM boundaries."
document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>Cautio | Customer Footage Report</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;padding:12px;background:#edf2ee;color:#18241d;font:15px/1.45 Arial,Helvetica,sans-serif}}
.report{{max-width:560px;margin:0 auto;background:#fff;border:1px solid #d5dfd7;border-radius:12px;overflow:hidden}}
.hero{{padding:18px;background:#12382b;color:#fff}} .logo{{display:block;width:106px;height:32px}} .tagline{{color:#c4d7cb;font-size:11px}}
h1{{font-size:21px;line-height:1.2;margin:15px 0 4px}} .subtitle,.window{{color:#d4e0d9;font-size:12px;margin:0}} .window{{margin-top:8px}}
.content{{padding:15px}} .summary{{margin:0 0 13px;color:#354a3c;font-size:13px;font-weight:bold}}
.day-card{{margin:0 0 12px;border:1px solid #d8e1da;border-radius:9px;overflow:hidden;background:#fff}}
.day-card:nth-child(even){{background:#f4f8f5}} .day-card h2{{margin:0;padding:11px 12px;background:#e9f1eb;border-bottom:1px solid #d8e1da;color:#183e2d;font-size:15px}}
.metrics{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}} .metric{{padding:10px 12px;border-bottom:1px solid #e7ede8}}
.metric:nth-child(odd){{border-right:1px solid #e7ede8;background:#f7faf8}} .metric b{{display:block;font-size:19px;color:#203b2c}} .metric span{{font-size:11px;color:#53665a}}
.metric.delivered b{{color:#17643d}} .metric.pending b,.metric.critical b{{color:#982f27}}
.note{{padding:10px 12px;border-left:3px solid #966a13;background:#faf4e3;color:#684e19;font-size:11px;margin:12px 0}}
.empty{{padding:14px;background:#f4f8f5;border:1px solid #d8e1da;border-radius:8px;color:#45574b}}
.footer{{padding:12px 15px;background:#f1f5f2;border-top:1px solid #d8e1da;color:#52635a;font-size:11px}} .footer strong{{display:block;color:#203b2c;font-size:13px}}
@media(prefers-color-scheme:dark){{body{{background:#111a15!important;color:#edf5ef!important}}.report,.day-card{{background:#1c2921!important;border-color:#45564a!important}}.content{{background:#1c2921!important}}.summary{{color:#e4efe7!important}}.day-card:nth-child(even){{background:#24342a!important}}.day-card h2{{background:#2b4032!important;color:#f1f7f2!important;border-color:#45564a!important}}.metric,.metric:nth-child(odd){{background:#1c2921!important;border-color:#45564a!important}}.metric b{{color:#f1f7f2!important}}.metric span{{color:#c2d2c7!important}}.metric.delivered b{{color:#a8efbf!important}}.metric.pending b,.metric.critical b{{color:#ffb4ad!important}}.note{{background:#3c3421!important;color:#ffe39a!important}}.empty{{background:#24342a!important;color:#e3eee6!important}}.footer{{background:#17221b!important;color:#d0ddd4!important;border-color:#45564a!important}}.footer strong{{color:#f1f7f2!important}}}}
</style></head><body><main class="report"><header class="hero">
<svg class="logo" viewBox="0 0 120 36" role="img" aria-label="Cautio logo" xmlns="http://www.w3.org/2000/svg"><text x="0" y="28" fill="#FFFFFF" font-family="Arial,Helvetica,sans-serif" font-size="28" font-weight="800" letter-spacing="-1">cautio</text><circle cx="56.3" cy="6.8" r="2.5" fill="#34D399"/></svg>
<div class="tagline">The future of safety on every journey</div><h1>Customer footage report</h1><p class="subtitle">Requested footage only · AI camera events excluded</p>
<p class="window">{START.strftime('%d %b %Y, 9:00 AM')} – {END.strftime('%d %b %Y, 9:00 AM')} IST</p></header>
<section class="content"><p class="summary">{summary}</p>{''.join(cards) if cards else '<div class="empty">No footage totals found for these dates. Please check that the Video Tracker has date rows for the report window.</div>'}
<p class="note">{window_note}</p></section><footer class="footer"><strong>Let's Make Roads Safer, Together</strong>Read-only daily totals from Video Tracker</footer></main></body></html>"""
OUTPUT.write_text(document, encoding="utf-8")
print(f"wrote {OUTPUT}; calendar_days={len(days)}; footage_requests={count('Footage Request')}; delivered={count('Delivered')}; pending={count('Pending')}; critical={count('Critical')}")

required = ("REPORT_TO", "MAIL_HOST", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_FROM")
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit("Email not configured; missing required GitHub secrets: " + ", ".join(missing))
message = EmailMessage()
message["Subject"] = f"Cautio customer footage report | {START:%d %b} 9 AM–{END:%d %b} 9 AM IST"
message["From"] = os.environ["MAIL_FROM"]
message["To"] = os.environ["REPORT_TO"]
message.set_content(f"{summary}\n{window_note}\nOpen in an HTML-capable mail app for the daily breakdown.")
message.add_alternative(document, subtype="html")
with smtplib.SMTP(os.environ["MAIL_HOST"], int(os.environ["MAIL_PORT"]), timeout=30) as server:
    server.starttls()
    server.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
    server.send_message(message)
print("Customer footage report emailed to configured recipient.")
