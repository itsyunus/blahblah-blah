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

rows = []
for item in issues:
    p_class = {"Critical": "critical", "No critical": "normal", "Not specified": "unspecified"}[item["priority"]]
    r_class = {"yes": "resolved", "no": "open", "not required": "not-required"}.get(item["resolved"].lower(), "unspecified")
    issue = f'<strong>{esc(item["request"])}</strong><span class="detail">{esc(item["details"])}</span>'
    rows.append(f"""<tr>
      <td class="client-cell" data-label="Client"><strong>{esc(item['client'])}</strong></td>
      <td class="vehicle-cell" data-label="Vehicle">{esc(item['vehicle'])}</td>
      <td data-label="Criticality">{badge(item['priority'], p_class)}</td>
      <td class="issue-cell" data-label="Issue / request">{issue}</td>
      <td data-label="Incident remarks">{esc(item['remarks'])}</td>
      <td data-label="Resolved?">{badge(item['resolved'], r_class)}</td>
      <td data-label="Current status">{esc(item['status'])}</td>
    </tr>""")

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
    .summary-table {{ width:100%; min-width:0; margin:0 0 22px; border-collapse:collapse; table-layout:auto; }}
    .summary-table th {{ padding:8px 7px; border:1px solid #D7DDD8; background:#F5F6F3; color:#526158; text-align:center; font-size:9px; font-weight:700; letter-spacing:.25px; text-transform:uppercase; }}
    .summary-table th:nth-child(even) {{ background:#EAF0EB; }}
    .summary-table td {{ padding:9px 7px; border:1px solid #D7DDD8; color:#0F172A; text-align:center; font-size:14px; font-weight:700; background:#FFFFFF; }}
    .summary-table td:nth-child(even) {{ background:#F2F6F2; }}
    .summary-table td.critical {{ color:#A33A32; }} .summary-table td.normal {{ color:#176B48; }} .summary-table td.unknown {{ color:#8A5B18; }}
    .table-shell {{ overflow:hidden; border-top:1px solid #D7DDD8; border-bottom:1px solid #D7DDD8; }}
    .scroll {{ overflow-x:auto; }}
    table {{ width:100%; min-width:920px; border-collapse:collapse; table-layout:fixed; }}
    .issue-table {{ min-width:920px; }}
    col.client {{ width:15%; }} col.vehicle {{ width:10%; }} col.priority {{ width:10%; }} col.issue {{ width:22%; }} col.remarks {{ width:18%; }} col.resolved {{ width:10%; }} col.status {{ width:15%; }}
    thead {{ background:#F5F6F3; }} th {{ padding:10px 11px; border-bottom:1px solid #D7DDD8; color:#526158; text-align:left; font-size:9px; font-weight:700; letter-spacing:.45px; text-transform:uppercase; }}
    td {{ padding:10px 11px; border-bottom:1px solid #E7EAE6; color:#334155; vertical-align:top; font-size:11px; line-height:1.45; overflow-wrap:anywhere; }}
    .issue-table tbody tr:nth-child(odd) td {{ background:#FFFFFF; }}
    .issue-table tbody tr:nth-child(odd) td:nth-child(even) {{ background:#F2F6F2; }}
    .issue-table tbody tr:nth-child(even) td {{ background:#F8FAF8; }}
    .issue-table tbody tr:nth-child(even) td:nth-child(even) {{ background:#EAF0EB; }}
    .issue-table tbody tr:last-child td {{ border-bottom:0; }}
    .client-cell strong {{ display:block; color:#0F172A; font-size:11px; }} .vehicle-cell {{ color:#64748B; font:10px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .issue-cell strong {{ display:block; color:#0F172A; font-weight:700; }} .detail {{ display:block; margin-top:3px; color:#475569; }}
    .pill {{ display:inline; padding:0; border:0; border-radius:0; background:transparent; font-size:11px; font-weight:700; line-height:1.4; white-space:normal; }}
    .pill.critical,.pill.open {{ color:#A33A32; }}
    .pill.normal,.pill.resolved {{ color:#176B48; }}
    .pill.unspecified,.pill.not-required {{ color:#8A5B18; }}
    .footer {{ padding:16px 24px; border-top:1px solid #E3E5E0; background:#F5F6F3; color:#64716A; text-align:left; font-size:10px; }}
    .footer strong {{ display:block; margin-bottom:3px; color:#25332B; font-size:12px; }}
    .window-note {{ margin:0 0 14px; padding:9px 11px; border-left:3px solid #8A5B18; background:#FBF6EA; color:#6F511C; font-size:11px; }}
    @media only screen and (max-width:640px) {{
      body {{ padding:0 !important; }} .report {{ width:100% !important; max-width:none !important; border:0 !important; }}
      .hero {{ padding:18px 14px !important; }} .content {{ padding:15px 12px !important; }} h1 {{ margin-top:16px; font-size:21px; }}
      .logo {{ width:100px; }} .window {{ font-size:10px; }} .section-heading {{ align-items:flex-start; }}
      .summary-table {{ display:block; width:100% !important; min-width:0 !important; }} .summary-table thead {{ display:none; }}
      .summary-table tbody, .summary-table tr {{ display:block; width:100%; }} .summary-table tr {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); }}
      .summary-table td {{ display:flex; flex-direction:column; align-items:flex-start; gap:4px; padding:8px !important; text-align:left !important; font-size:15px !important; }}
      .summary-table td::before {{ content:attr(data-label); color:#526158; font-size:9px; font-weight:700; letter-spacing:.3px; text-transform:uppercase; }}
      .table-shell {{ overflow:visible !important; border:0 !important; }} .scroll {{ overflow:visible !important; }}
      .issue-table {{ display:block; width:100% !important; min-width:0 !important; table-layout:auto !important; }}
      .issue-table thead {{ display:none; }} .issue-table tbody {{ display:block; width:100%; }}
      .issue-table tbody tr {{ display:block; margin:0 0 11px; border:1px solid #D7DDD8; }}
      .issue-table tbody td {{ display:grid; grid-template-columns:minmax(84px,30%) minmax(0,1fr); gap:8px; width:100%; padding:8px !important; font-size:12px !important; }}
      .issue-table tbody td::before {{ content:attr(data-label); color:#526158; font-size:9px; font-weight:700; letter-spacing:.25px; text-transform:uppercase; }}
      .client-cell strong {{ font-size:12px; }} .issue-cell strong {{ font-size:12px; }} .pill {{ font-size:12px; }}
      .footer {{ padding:13px 14px !important; }}
    }}
    @media (prefers-color-scheme:dark) {{
      body {{ background:#111827 !important; color:#E5E7EB !important; }} .report {{ background:#1F2937 !important; border-color:#374151 !important; }}
      .hero {{ background:#111827 !important; }} .subhead {{ color:#D1D5DB !important; }} .window {{ color:#BBF7D0 !important; }}
      h2,.client-cell strong,.issue-cell strong {{ color:#F9FAFB !important; }} .section-note,.vehicle-cell,.detail {{ color:#CBD5E1 !important; }}
      .summary-table th {{ background:#273548 !important; color:#F3F4F6 !important; border-color:#4B5563 !important; }}
      .summary-table th:nth-child(even),.summary-table td:nth-child(even),.summary-table td {{ background:#1F2937 !important; color:#F9FAFB !important; border-color:#4B5563 !important; }}
      .summary-table td.critical {{ color:#FCA5A5 !important; }} .summary-table td.normal {{ color:#86EFAC !important; }} .summary-table td.unknown {{ color:#FDE68A !important; }}
      .issue-table th {{ background:#273548 !important; color:#F3F4F6 !important; border-color:#4B5563 !important; }}
      .issue-table tbody tr:nth-child(odd) td {{ background:#1F2937 !important; color:#E5E7EB !important; border-color:#374151 !important; }}
      .issue-table tbody tr:nth-child(odd) td:nth-child(even) {{ background:#273444 !important; }}
      .issue-table tbody tr:nth-child(even) td {{ background:#263343 !important; color:#E5E7EB !important; border-color:#374151 !important; }}
      .issue-table tbody tr:nth-child(even) td:nth-child(even) {{ background:#2D3B4B !important; }}
      .issue-table tbody td::before,.summary-table td::before {{ color:#C4D2CA !important; }}
      .pill.critical,.pill.open {{ color:#FCA5A5 !important; }} .pill.normal,.pill.resolved {{ color:#86EFAC !important; }}
      .pill.unspecified,.pill.not-required {{ color:#FDE68A !important; }}
      .window-note {{ background:#3B3321 !important; color:#FDE68A !important; border-color:#FBBF24 !important; }}
      .footer {{ background:#111827 !important; color:#CBD5E1 !important; border-color:#374151 !important; }} .footer strong {{ color:#F9FAFB !important; }}
    }}
    [data-ogsc] .report {{ background:#1F2937 !important; color:#E5E7EB !important; }}
    [data-ogsc] .issue-table tbody td {{ color:#E5E7EB !important; border-color:#374151 !important; }}
    [data-ogsc] .issue-table tbody tr:nth-child(odd) td {{ background:#1F2937 !important; }}
    [data-ogsc] .issue-table tbody tr:nth-child(odd) td:nth-child(even) {{ background:#273444 !important; }}
    [data-ogsc] .issue-table tbody tr:nth-child(even) td {{ background:#263343 !important; }}
    [data-ogsc] .summary-table th {{ background:#273548 !important; color:#F3F4F6 !important; }}
    [data-ogsc] .summary-table td {{ background:#1F2937 !important; color:#F9FAFB !important; }}
    [data-ogsc] .pill.critical,[data-ogsc] .pill.open {{ color:#FCA5A5 !important; }}
    [data-ogsc] .pill.normal,[data-ogsc] .pill.resolved {{ color:#86EFAC !important; }}
    [data-ogsc] .pill.unspecified,[data-ogsc] .pill.not-required {{ color:#FDE68A !important; }}
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
      <div class="section-heading"><h2>Daily summary</h2><span class="section-note">{clients} clients &bull; {total} issues</span></div>
      <table class="summary-table" aria-label="Daily issue counts">
        <thead><tr><th>Total</th><th>Critical</th><th>No critical</th><th>Not specified</th><th>Resolved</th><th>Not resolved</th><th>Not required</th><th>Resolution unstated</th></tr></thead>
        <tbody><tr><td data-label="Total">{total}</td><td data-label="Critical" class="critical">{counts['critical']}</td><td data-label="No critical" class="normal">{counts['no_critical']}</td><td data-label="Not specified" class="unknown">{counts['priority_unknown']}</td><td data-label="Resolved" class="normal">{counts['resolved']}</td><td data-label="Not resolved" class="critical">{counts['not_resolved']}</td><td data-label="Not required">{counts['not_required']}</td><td data-label="Resolution unstated" class="unknown">{counts['resolution_unknown']}</td></tr></tbody>
      </table>
      {window_note}
      <div class="section-heading"><h2>All reported issues</h2><span class="section-note">Critical issues shown first</span></div>
      <div class="table-shell"><div class="scroll">
        <table class="issue-table" aria-label="Daily issue details">
          <colgroup><col class="client"><col class="vehicle"><col class="priority"><col class="issue"><col class="remarks"><col class="resolved"><col class="status"></colgroup>
          <thead><tr><th>Client</th><th>Vehicle</th><th>Criticality</th><th>Issue / request</th><th>Incident remarks</th><th>Resolved?</th><th>Current status</th></tr></thead>
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
