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
    return html.escape((value or "").replace("\r", " ").replace("\n", " ").strip())

def parse_raised_timestamp(value, row_number):
    raw = (value or "").replace("\u00a0", " ").strip()
    if not raw:
        return None, False

    full_formats = (
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M", "%d/%m/%Y, %H:%M:%S",
        "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y, %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
    )
    parsed = None
    for timestamp_format in full_formats:
        try:
            parsed = dt.datetime.strptime(raw, timestamp_format)
            break
        except ValueError:
            continue

    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.time() == dt.time.min and len(raw) <= 10:
                return parsed.replace(tzinfo=TZ), True
        except ValueError:
            pass

    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        else:
            parsed = parsed.astimezone(TZ)
        return parsed, False

    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            parsed_date = dt.datetime.strptime(raw, date_format).date()
            return dt.datetime.combine(parsed_date, dt.time.min, TZ), True
        except ValueError:
            continue

    raise SystemExit(f"Unrecognized timestamp format on CSV row {row_number}: {raw!r}; refusing to email a possibly incomplete report")

issues = []
with SOURCE.open(encoding="utf-8-sig", newline="") as f:
    for row_number, source_row in enumerate(csv.DictReader(f), start=2):
        raised, date_only = parse_raised_timestamp(source_row.get("Timestamp Issues Raised"), row_number)
        if raised is None:
            continue
        if date_only:
            # Date-only records cannot be placed precisely across the 9 AM boundary.
            # Keep them visible for either calendar date covered by the window and disclose the uncertainty.
            in_window = START.date() <= raised.date() <= END.date()
        else:
            in_window = START <= raised < END
        if not in_window:
            continue
        request = (source_row.get("Sub-request") or "").strip()
        # This email is specifically for customer requested footage, not AI camera events.
        if "footage" not in request.casefold():
            continue
        incident = (source_row.get("Incident Type") or "").strip()
        issues.append({
            "client": (source_row.get("Clients") or "").strip() or "Client not stated",
            "vehicle": (source_row.get("Vehicle Number") or "").strip() or "Vehicle not stated",
            "priority": "Critical" if incident.lower() == "critical" else ("No critical" if incident else "Not specified"),
            "request": request,
            "details": (source_row.get("Issue Details") or "").strip() or "No issue details recorded",
            "remarks": (source_row.get("Remarks (Incident Details)") or "").strip() or "No incident remarks recorded",
            "resolved": (source_row.get("Resolved Y/N") or "").strip() or "Not stated",
            "status": (source_row.get("Date - Current Status") or "").strip() or "No current status recorded",
            "time_uncertain": date_only,
        })

priority_order = {"Critical": 0, "No critical": 1, "Not specified": 2}
issues.sort(key=lambda x: (priority_order[x["priority"]], x["client"].casefold(), x["vehicle"]))
total = len(issues)
counts = {
    "critical": sum(x["priority"] == "Critical" for x in issues),
    "no_critical": sum(x["priority"] == "No critical" for x in issues),
    "priority_unknown": sum(x["priority"] == "Not specified" for x in issues),
    "resolved": sum(x["resolved"].lower() == "yes" for x in issues),
    "not_resolved": sum(x["resolved"].lower() == "no" for x in issues),
    "not_required": sum(x["resolved"].lower() == "not required" for x in issues),
    "resolution_unknown": sum(x["resolved"].lower() == "not stated" for x in issues),
}

def badge(text, kind):
    return f'<span class="pill {kind}">{esc(text)}</span>'

cards = []
for item in issues:
    p_class = {"Critical": "critical", "No critical": "normal", "Not specified": "unspecified"}[item["priority"]]
    r_class = {"yes": "resolved", "no": "open", "not required": "not-required"}.get(item["resolved"].lower(), "unspecified")
    cards.append(f"""<article class="issue-card">
      <div class="card-top"><div><div class="client">{esc(item['client'])}</div><div class="vehicle">Vehicle {esc(item['vehicle'])}</div></div>
        <div class="badges">{badge(item['priority'], p_class)}{badge(item['resolved'], r_class)}</div></div>
      <div class="card-body"><div class="field"><span class="label">Footage requested</span><strong>{esc(item['request'])}</strong></div>
        <div class="field"><span class="label">Issue details</span><span>{esc(item['details'])}</span></div>
        <div class="field"><span class="label">Remarks</span><span>{esc(item['remarks'])}</span></div>
        <div class="field"><span class="label">Current status</span><span>{esc(item['status'])}</span></div></div>
    </article>""")

clients = len({x["client"] for x in issues})
date_only_count = sum(item["time_uncertain"] for item in issues)
window_note = (
    f'<p class="window-note">{date_only_count} record(s) have a date but no time. They are included by calendar date; their exact position around the 9 AM boundary cannot be confirmed.</p>'
    if date_only_count else ""
)
document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <title>Cautio | Daily Fleet Issue Report</title>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ margin:0; padding:12px; background:#edf2ee; color:#18241d; font:15px/1.5 Arial,Helvetica,sans-serif; }}
    .report {{ width:100%; max-width:620px; margin:0 auto; overflow:hidden; border:1px solid #d5dfd7; border-radius:12px; background:#fff; }}
    .hero {{ padding:18px 18px 16px; color:#fff; background:#12382b; }}
    .logo {{ width:106px; height:32px; display:block; }} .tagline {{ margin-top:2px; color:#c4d7cb; font-size:11px; }}
    h1 {{ margin:16px 0 4px; font-size:22px; line-height:1.2; }} .subhead {{ margin:0; color:#d4e0d9; font-size:13px; }}
    .window {{ display:block; margin-top:10px; color:#d4e0d9; font-size:12px; }}
    .content {{ padding:16px; }} .summary {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:18px; }}
    .stat {{ flex:1 1 30%; min-width:90px; padding:10px; border:1px solid #dce5de; border-radius:8px; background:#f2f7f3; }}
    .stat b {{ display:block; font-size:20px; line-height:1.2; }} .stat span {{ color:#52635a; font-size:11px; }}
    h2 {{ margin:0 0 10px; color:#25392d; font-size:16px; }} .section-note {{ margin:-5px 0 12px; color:#56675d; font-size:12px; }}
    .issue-card {{ margin-bottom:12px; border:1px solid #d8e1da; border-radius:9px; overflow:hidden; background:#fff; }}
    .issue-card:nth-child(even) {{ background:#f4f8f5; }} .card-top {{ display:flex; justify-content:space-between; gap:10px; padding:12px; background:#e9f1eb; border-bottom:1px solid #d8e1da; }}
    .issue-card:nth-child(even) .card-top {{ background:#e2ece5; }} .client {{ color:#183e2d; font-size:15px; font-weight:700; }}
    .vehicle {{ margin-top:2px; color:#4f6257; font-size:12px; }} .badges {{ display:flex; align-items:flex-start; justify-content:flex-end; flex-wrap:wrap; gap:5px; }}
    .pill {{ display:inline-block; padding:3px 7px; border-radius:12px; background:#e9eeee; color:#26362d; font-size:11px; font-weight:700; white-space:nowrap; }}
    .pill.critical,.pill.open {{ background:#fde8e6; color:#982f27; }} .pill.normal,.pill.resolved {{ background:#e1f2e8; color:#17643d; }} .pill.unspecified,.pill.not-required {{ background:#f8f0d8; color:#765514; }}
    .card-body {{ padding:4px 12px 10px; }} .field {{ padding:8px 0; border-bottom:1px solid #e8ede9; overflow-wrap:anywhere; }} .field:last-child {{ border:0; }}
    .label {{ display:block; margin-bottom:2px; color:#53665a; font-size:10px; font-weight:700; letter-spacing:.35px; text-transform:uppercase; }}
    .field strong {{ color:#18241d; }} .window-note {{ margin:0 0 12px; padding:9px; border-left:3px solid #966a13; background:#faf4e3; color:#684e19; font-size:12px; }}
    .empty {{ padding:16px; border:1px solid #d8e1da; border-radius:8px; background:#f4f8f5; color:#45574b; }}
    .footer {{ padding:13px 16px; border-top:1px solid #d8e1da; background:#f1f5f2; color:#52635a; font-size:11px; }}
    .footer strong {{ display:block; color:#203b2c; font-size:13px; }}
    @media (prefers-color-scheme:dark) {{
      body {{ background:#111a15 !important; color:#edf5ef !important; }} .report,.issue-card {{ background:#1c2921 !important; border-color:#45564a !important; }}
      .content {{ background:#1c2921 !important; }} h2,.client,.field strong {{ color:#f1f7f2 !important; }} .section-note,.vehicle,.label {{ color:#c2d2c7 !important; }}
      .stat,.issue-card:nth-child(even) {{ background:#24342a !important; border-color:#45564a !important; }} .stat span {{ color:#d0ddd4 !important; }}
      .card-top,.issue-card:nth-child(even) .card-top {{ background:#2b4032 !important; border-color:#45564a !important; }}
      .field {{ border-color:#3d4c41 !important; }} .pill.critical,.pill.open {{ background:#542e2c !important; color:#ffb4ad !important; }}
      .pill.normal,.pill.resolved {{ background:#244a34 !important; color:#a8efbf !important; }} .pill.unspecified,.pill.not-required {{ background:#4a4028 !important; color:#ffe39a !important; }}
      .window-note {{ background:#3c3421 !important; color:#ffe39a !important; }} .empty {{ background:#24342a !important; color:#e3eee6 !important; }}
      .footer {{ background:#17221b !important; color:#d0ddd4 !important; border-color:#45564a !important; }} .footer strong {{ color:#f1f7f2 !important; }}
    }}
    [data-ogsc] .report,[data-ogsc] .issue-card {{ background:#1c2921 !important; color:#edf5ef !important; }}
    [data-ogsc] .field strong,[data-ogsc] .client {{ color:#f1f7f2 !important; }}
  </style>
</head>
<body>
  <main class="report">
    <div class="accent"></div>
    <header class="hero">
      <div class="brand-row">
        <div class="brand">
          <div class="brand-lockup">
          <svg class="logo" viewBox="0 0 120 36" role="img" aria-label="Cautio logo" xmlns="http://www.w3.org/2000/svg">
            <text x="0" y="28" fill="#FFFFFF" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="800" letter-spacing="-1">cautio</text>
            <circle cx="56.3" cy="6.8" r="2.5" fill="#34D399"/>
          </svg>
          <div class="tagline">The future of safety on every journey</div>
          </div>
        </div>
        <div class="section-note">Daily operations</div>
      </div>
      <h1>Daily fleet issue report</h1>
      <p class="subhead">Customer requested footage only</p>
      <div class="window">{START.strftime("%d %b %Y, %I:%M %p IST")} <span aria-hidden="true">&rarr;</span> {END.strftime("%d %b %Y, %I:%M %p IST")}</div>
    </header>
    <div class="content">
      <h2>Daily summary</h2><p class="section-note">{clients} clients &bull; {total} footage requests</p>
      <div class="summary"><div class="stat"><b>{total}</b><span>Requests</span></div><div class="stat"><b>{counts['critical']}</b><span>Critical</span></div><div class="stat"><b>{counts['resolved']}</b><span>Resolved</span></div><div class="stat"><b>{counts['not_resolved']}</b><span>Not resolved</span></div></div>
      {window_note}
      <h2>Customer requested footage</h2><p class="section-note">Critical requests are listed first.</p>
      {''.join(cards) if cards else '<div class="empty">No customer footage requests were recorded in this 9 AM to 9 AM reporting window.</div>'}
    </div>
    <footer class="footer"><strong>Let's Make Roads Safer, Together</strong>Issues- Realtime &bull; Read-only extract &bull; {total} matching records</footer>
  </main>
</body>
</html>"""

OUTPUT.write_text(document, encoding="utf-8")
print(f"wrote {OUTPUT}; footage_requests={total}; clients={clients}; critical={counts['critical']}; no_critical={counts['no_critical']}; priority_unspecified={counts['priority_unknown']}; resolved={counts['resolved']}; not_resolved={counts['not_resolved']}; not_required={counts['not_required']}; resolution_not_stated={counts['resolution_unknown']}")

# Send the single consolidated report only to an explicitly configured address.
required = ("REPORT_TO", "MAIL_HOST", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_FROM")
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit("Email not configured; missing required GitHub secrets: " + ", ".join(missing))
message = EmailMessage()
message["Subject"] = f"Cautio daily fleet issue report | {START:%d %b} 9 AM–{END:%d %b} 9 AM IST"
message["From"] = os.environ["MAIL_FROM"]
message["To"] = os.environ["REPORT_TO"]
message.set_content(f"Daily fleet issue report: {total} issues across {clients} clients. Open this email in an HTML-capable mail app to view the full report.")
message.add_alternative(document, subtype="html")
with smtplib.SMTP(os.environ["MAIL_HOST"], int(os.environ["MAIL_PORT"]), timeout=30) as server:
    server.starttls()
    server.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
    server.send_message(message)
print("Combined report emailed to configured report recipient.")
