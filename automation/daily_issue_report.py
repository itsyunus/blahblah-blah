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

issues = []
with SOURCE.open(encoding="utf-8-sig", newline="") as f:
    for source_row in csv.DictReader(f):
        try:
            raised = dt.datetime.strptime(source_row.get("Timestamp Issues Raised", "").strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=TZ)
        except ValueError:
            if (source_row.get("Timestamp Issues Raised") or "").strip():
                raise SystemExit("Unrecognized timestamp format in source CSV; refusing to email a possibly incomplete report")
            continue
        if not (START <= raised < END):
            continue
        incident = (source_row.get("Incident Type") or "").strip()
        issues.append({
            "client": (source_row.get("Clients") or "").strip() or "Client not stated",
            "vehicle": (source_row.get("Vehicle Number") or "").strip() or "Vehicle not stated",
            "priority": "Critical" if incident.lower() == "critical" else ("No critical" if incident else "Not specified"),
            "request": (source_row.get("Sub-request") or "").strip() or "Request not stated",
            "details": (source_row.get("Issue Details") or "").strip() or "No issue details recorded",
            "remarks": (source_row.get("Remarks (Incident Details)") or "").strip() or "No incident remarks recorded",
            "resolved": (source_row.get("Resolved Y/N") or "").strip() or "Not stated",
            "status": (source_row.get("Date - Current Status") or "").strip() or "No current status recorded",
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

rows = []
for item in issues:
    p_class = {"Critical": "critical", "No critical": "normal", "Not specified": "unspecified"}[item["priority"]]
    r_class = {"yes": "resolved", "no": "open", "not required": "not-required"}.get(item["resolved"].lower(), "unspecified")
    issue = f'<strong>{esc(item["request"])}</strong><span class="detail">{esc(item["details"])}</span>'
    rows.append(f"""<tr>
      <td class="client-cell"><strong>{esc(item['client'])}</strong><span class="vehicle">{esc(item['vehicle'])}</span></td>
      <td>{badge(item['priority'], p_class)}</td>
      <td class="issue-cell">{issue}</td>
      <td>{esc(item['remarks'])}</td>
      <td>{badge(item['resolved'], r_class)}</td>
      <td>{esc(item['status'])}</td>
    </tr>""")

clients = len({x["client"] for x in issues})
document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cautio | Daily Fleet Issue Report</title>
  <style>
    :root {{ --ink:#0A0F1C; --green:#10B981; --cyan:#06B6D4; --text:#0F172A; --muted:#64748B; --line:#E2E8F0; --paper:#FFFFFF; --bg:#F1F5F9; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; padding:24px 16px; background:#F7F7F4; color:var(--text); font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; -webkit-font-smoothing:antialiased; }}
    .report {{ max-width:1100px; margin:0 auto; overflow:hidden; background:var(--paper); border:1px solid #E3E5E0; }}
    .accent {{ height:4px; background:#177A51; }}
    .hero {{ padding:24px 30px 21px; color:#fff; background:var(--ink); }}
    .brand-row {{ display:flex; justify-content:space-between; align-items:center; gap:20px; }}
    .brand {{ display:flex; align-items:center; }} .brand-lockup {{ display:flex; flex-direction:column; align-items:flex-start; gap:0; }}
    .logo {{ display:block; width:120px; height:36px; }}
    .tagline {{ margin-top:2px; color:#94A3B8; font-size:11px; }}
    h1 {{ margin:20px 0 5px; font-size:25px; line-height:1.2; letter-spacing:-.35px; }}
    .subhead {{ margin:0; color:#CBD5E1; font-size:12px; }}
    .window {{ display:inline-block; margin-top:14px; color:#B9C8C0; font-size:11px; }}
    .content {{ padding:24px 28px 26px; }}
    .section-heading {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin-bottom:11px; }}
    h2 {{ margin:0; font-size:12px; font-weight:700; letter-spacing:.5px; text-transform:uppercase; color:#334155; }}
    .section-note {{ color:#64748B; font-size:11px; }}
    .summary-grid {{ display:grid; grid-template-columns:repeat(4,1fr); margin-bottom:15px; border-top:1px solid #D9DDD8; border-bottom:1px solid #D9DDD8; }}
    .metric {{ min-height:70px; padding:11px 15px 10px; border-right:1px solid #E5E8E3; }} .metric:last-child {{ border-right:0; }}
    .metric-label {{ color:var(--muted); font-size:10px; font-weight:700; letter-spacing:.35px; text-transform:uppercase; }}
    .metric-value {{ margin-top:3px; color:#0F172A; font-size:23px; line-height:1.1; font-weight:700; }}
    .metric-hint {{ margin-top:3px; color:#64748B; font-size:10px; }}
    .metric.critical .metric-value {{ color:#A33A32; }}
    .metric.normal .metric-value {{ color:#176B48; }}
    .metric.unknown .metric-value {{ color:#8A5B18; }}
    .resolution {{ display:flex; align-items:center; flex-wrap:wrap; gap:8px 18px; margin:12px 0 23px; padding:10px 0; border-bottom:1px solid #E5E8E3; color:#475569; font-size:11px; }}
    .resolution strong {{ color:#0F172A; margin-right:4px; }} .res-item {{ display:inline-flex; align-items:center; gap:6px; }}
    .table-shell {{ overflow:hidden; border-top:1px solid #D7DDD8; border-bottom:1px solid #D7DDD8; }}
    .scroll {{ overflow-x:auto; }}
    table {{ width:100%; min-width:920px; border-collapse:collapse; table-layout:fixed; }}
    col.client {{ width:16%; }} col.priority {{ width:11%; }} col.issue {{ width:24%; }} col.remarks {{ width:20%; }} col.resolved {{ width:10%; }} col.status {{ width:19%; }}
    thead {{ background:#F5F6F3; }} th {{ padding:10px 11px; border-bottom:1px solid #D7DDD8; color:#526158; text-align:left; font-size:9px; font-weight:700; letter-spacing:.45px; text-transform:uppercase; }}
    td {{ padding:10px 11px; border-bottom:1px solid #E7EAE6; color:#334155; vertical-align:top; font-size:11px; line-height:1.45; overflow-wrap:anywhere; }}
    tbody tr:nth-child(even) {{ background:#FAFBF9; }} tbody tr:last-child td {{ border-bottom:0; }}
    .client-cell strong {{ display:block; color:#0F172A; font-size:11px; }} .vehicle {{ display:block; margin-top:3px; color:#64748B; font:10px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .issue-cell strong {{ display:block; color:#0F172A; font-weight:700; }} .detail {{ display:block; margin-top:3px; color:#475569; }}
    .pill {{ display:inline; padding:0; border:0; border-radius:0; background:transparent; font-size:11px; font-weight:700; line-height:1.4; white-space:normal; }}
    .pill.critical,.pill.open {{ color:#A33A32; }}
    .pill.normal,.pill.resolved {{ color:#176B48; }}
    .pill.unspecified,.pill.not-required {{ color:#8A5B18; }}
    .footer {{ padding:16px 24px; border-top:1px solid #E3E5E0; background:#F5F6F3; color:#64716A; text-align:left; font-size:10px; }}
    .footer strong {{ display:block; margin-bottom:3px; color:#25332B; font-size:12px; }}
    @media(max-width:720px) {{ body {{ padding:0; }} .report {{ border-radius:0; }} .hero {{ padding:22px 18px; }} .content {{ padding:20px 14px; }} .summary-grid {{ grid-template-columns:repeat(2,1fr); }} .report-tag {{ font-size:8px; }} .window {{ font-size:9px; }} }}
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
      <p class="subhead">Read-only summary of reported fleet issues and footage requests</p>
      <div class="window">{START.strftime("%d %b %Y, %I:%M %p IST")} <span aria-hidden="true">&rarr;</span> {END.strftime("%d %b %Y, %I:%M %p IST")}</div>
    </header>
    <div class="content">
      <div class="section-heading"><h2>Executive summary</h2><span class="section-note">{clients} clients &bull; {total} issues</span></div>
      <section class="summary-grid" aria-label="Issue summary">
        <div class="metric"><div class="metric-label">Total issues</div><div class="metric-value">{total}</div><div class="metric-hint">In this reporting window</div></div>
        <div class="metric critical"><div class="metric-label">Critical</div><div class="metric-value">{counts['critical']}</div><div class="metric-hint">Marked critical in the tracker</div></div>
        <div class="metric normal"><div class="metric-label">No critical</div><div class="metric-value">{counts['no_critical']}</div><div class="metric-hint">Marked normal in the tracker</div></div>
        <div class="metric unknown"><div class="metric-label">Not specified</div><div class="metric-value">{counts['priority_unknown']}</div><div class="metric-hint">Incident type not entered</div></div>
      </section>
      <div class="resolution" aria-label="Resolution summary">
        <strong>Resolution</strong>
        <span class="res-item">{counts['resolved']} resolved</span>
        <span class="res-item">{counts['not_resolved']} not resolved</span>
        <span class="res-item">{counts['not_required']} not required</span>
        <span class="res-item">{counts['resolution_unknown']} not stated</span>
      </div>
      <div class="section-heading"><h2>All reported issues</h2><span class="section-note">Critical issues shown first</span></div>
      <div class="table-shell"><div class="scroll">
        <table aria-label="Daily issue details">
          <colgroup><col class="client"><col class="priority"><col class="issue"><col class="remarks"><col class="resolved"><col class="status"></colgroup>
          <thead><tr><th>Client / vehicle</th><th>Criticality</th><th>Issue / request</th><th>Incident remarks</th><th>Resolved?</th><th>Current status</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div></div>
    </div>
    <footer class="footer"><strong>Let's Make Roads Safer, Together</strong>Issues- Realtime &bull; Read-only extract &bull; {total} matching records</footer>
  </main>
</body>
</html>"""

OUTPUT.write_text(document, encoding="utf-8")
print(f"wrote {OUTPUT}; issues={total}; clients={clients}; critical={counts['critical']}; no_critical={counts['no_critical']}; priority_unspecified={counts['priority_unknown']}; resolved={counts['resolved']}; not_resolved={counts['not_resolved']}; not_required={counts['not_required']}; resolution_not_stated={counts['resolution_unknown']}")

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
