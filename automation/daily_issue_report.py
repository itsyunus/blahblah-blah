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
END = now.replace(hour=21, minute=0, second=0, microsecond=0)
if now < END:
    END -= dt.timedelta(days=1)
START = END - dt.timedelta(days=1)

def esc(value):
    return html.escape((value or "").replace("\r", " ").replace("\n", " ").strip())

def parse_timestamp(value, row_number):
    raw = (value or "").replace("\u00a0", " ").strip()
    if not raw:
        return None, False
    formats = (
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M",
        "%d/%m/%Y, %H:%M:%S", "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y, %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
    )
    for fmt in formats:
        try:
            return dt.datetime.strptime(raw, fmt).replace(tzinfo=TZ), True
        except ValueError:
            pass
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.time() == dt.time.min and len(raw) <= 10:
            return parsed.replace(tzinfo=TZ), False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        else:
            parsed = parsed.astimezone(TZ)
        return parsed, True
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            day = dt.datetime.strptime(raw, fmt).date()
            return dt.datetime.combine(day, dt.time.min, TZ), False
        except ValueError:
            pass
    if any(ch.isdigit() for ch in raw):
        raise SystemExit(f"Unrecognized Timestamp Issues Raised on CSV row {row_number}: {raw!r}; refusing to send an incomplete report")
    return None, False

def is_customer_footage(row):
    sub_request = (row.get("Sub-request") or "").strip().casefold()
    searchable = " ".join((row.get(k) or "") for k in ("Sub-request", "Issue Details", "Remarks (Incident Details)")).casefold()
    if "ai camera" in searchable or "ai-camera" in searchable:
        return False
    return any(term in searchable for term in ("footage", "video request", "customer request", "requested video")) or sub_request in {"footage", "video", "customer footage"}

issues = []
date_only_or_missing = 0
with SOURCE.open(encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    required = {"Timestamp Issues Raised", "Clients", "Vehicle Number", "Sub-request", "Issue Details", "Remarks (Incident Details)", "Resolved Y/N", "Date - Current Status", "Incident Type"}
    missing = required.difference(reader.fieldnames or [])
    if missing:
        raise SystemExit("Issues- Realtime export is missing expected columns: " + ", ".join(sorted(missing)))
    for row_number, row in enumerate(reader, start=2):
        raised, has_time = parse_timestamp(row.get("Timestamp Issues Raised"), row_number)
        if raised is None:
            continue
        if not has_time:
            if START.date() <= raised.date() <= END.date():
                date_only_or_missing += 1
            continue
        if not (START <= raised < END) or not is_customer_footage(row):
            continue
        incident = (row.get("Incident Type") or "").strip()
        resolved = (row.get("Resolved Y/N") or "").strip() or "Not stated"
        issues.append({
            "client": (row.get("Clients") or "").strip() or "Client not stated",
            "vehicle": (row.get("Vehicle Number") or "").strip() or "Vehicle not stated",
            "priority": "Critical" if incident.casefold() == "critical" else ("No critical" if incident else "Not specified"),
            "request": (row.get("Sub-request") or "").strip() or "Customer footage request",
            "details": (row.get("Issue Details") or "").strip() or "No issue details recorded",
            "remarks": (row.get("Remarks (Incident Details)") or "").strip() or "No remarks recorded",
            "resolved": resolved,
            "status": (row.get("Date - Current Status") or "").strip() or "No current status recorded",
        })

priority_order = {"Critical": 0, "No critical": 1, "Not specified": 2}
issues.sort(key=lambda item: (priority_order[item["priority"]], item["client"].casefold(), item["vehicle"]))
total = len(issues)
critical = sum(item["priority"] == "Critical" for item in issues)
resolved = sum(item["resolved"].casefold() == "yes" for item in issues)
not_resolved = sum(item["resolved"].casefold() == "no" for item in issues)

from collections import Counter, defaultdict

pending = not_resolved
other = total - resolved - pending
rate = f"{resolved / total:.0%}" if total else "0%"
clients = defaultdict(Counter)
for item in issues:
    key = item["resolved"].casefold()
    clients[item["client"]]["completed" if key == "yes" else "pending" if key == "no" else "other"] += 1

def cell(value, color="#eef3ef", bg="#141c18", weight="normal"):
    return f'<td bgcolor="{bg}" style="background-color:{bg};color:{color};font-weight:{weight};padding:9px 7px;border-bottom:1px solid #35433b;font-size:13px;line-height:1.5;vertical-align:top;overflow-wrap:anywhere;">{esc(value)}</td>'

def kpi(label, value, color):
    return f'<td width="50%" style="padding:4px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td bgcolor="#141c18" align="center" style="background:#141c18;border:1px solid #35433b;border-radius:8px;padding:12px 5px;color:#eef3ef"><span style="font-size:12px;color:#b5c3ba">{esc(label)}</span><br><strong style="font-size:25px;color:{color}">{esc(str(value))}</strong></td></tr></table></td>'

def bar(parts, denominator):
    if not denominator:
        return '<div style="background:#303c34;height:12px;border-radius:4px"></div>'
    segments = "".join(f'<td width="{n / denominator * 100:.4f}%" bgcolor="{color}" style="background-color:{color};height:14px;font-size:1px;line-height:14px;">&nbsp;</td>' for n, color in parts if n)
    return f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="table-layout:fixed"><tr>{segments}</tr></table>'

legend = f'<p style="font-size:12px;line-height:1.6;color:#eef3ef;margin:8px 0 0"><strong style="color:#80e6a5">Completed {resolved}</strong> &nbsp; <strong style="color:#ffaaa3">Pending {pending}</strong> &nbsp; Other {other}</p>'
status_bar = bar([(resolved,"#79e3a0"),(pending,"#f37870"),(other,"#9baaa0")], total)
client_rows = []
maximum = max((sum(c.values()) for c in clients.values()), default=0)
for name, c in sorted(clients.items(), key=lambda pair: (-sum(pair[1].values()), pair[0].casefold())):
    n = sum(c.values())
    chart = bar([(c["completed"],"#79e3a0"),(c["pending"],"#f37870"),(c["other"],"#9baaa0"),(maximum-n,"#303c34")], maximum)
    client_rows.append(f'<tr><td style="padding:7px 0;border-bottom:1px solid #303c34;color:#eef3ef;font-size:13px"><strong>{esc(name)}</strong><span style="font-size:12px"> &mdash; {n}</span><div style="padding-top:4px">{chart}</div><div style="font-size:11px;color:#b5c3ba;padding-top:3px">Completed {c["completed"]} / Pending {c["pending"]} / Other {c["other"]}</div></td></tr>')
client_chart = "".join(client_rows) or '<tr><td style="padding:8px;color:#b5c3ba">No matching requests.</td></tr>'
critical_records = []
regular_records = []
for item in issues:
    records = critical_records if item['priority'] == 'Critical' else regular_records
    i = len(records)
    bg = "#141c18" if i % 2 == 0 else "#1e2922"
    priority_color = "#ffaaa3" if item["priority"] == "Critical" else "#eef3ef"
    key = item["resolved"].casefold()
    resolution = "Completed" if key == "yes" else "Pending" if key == "no" else item["resolved"]
    status_color = "#80e6a5" if key == "yes" else "#ffaaa3" if key == "no" else "#b5c3ba"
    details = f'<strong>{esc(item["request"])}</strong><br>{esc(item["details"])}<br><strong>Remarks:</strong> {esc(item["remarks"])}<br><strong>Current status:</strong> {esc(item["status"])}'
    records.append(f'<tr>{cell(item["client"] + " / " + item["vehicle"], bg=bg, weight="bold")}{cell(item["priority"], priority_color, bg, "bold")}<td bgcolor="{bg}" style="background:{bg};color:#eef3ef;padding:9px 7px;font-size:13px;line-height:1.5;border-bottom:1px solid #35433b;vertical-align:top;overflow-wrap:anywhere">{details}</td>{cell(resolution, status_color, bg, "bold")}</tr>')
critical_rows = "".join(critical_records) or '<tr><td colspan="4" style="padding:16px;color:#b5c3ba">No critical footage requests in this reporting window.</td></tr>'
rows = "".join(regular_records) or '<tr><td colspan="4" style="padding:16px;color:#b5c3ba">No other footage requests.</td></tr>'
date_note = f'<p style="font-size:12px;color:#ffe1a1;background:#382f20;padding:8px">{date_only_or_missing} source row(s) with date-only timestamps could not be placed in the reporting window.</p>' if date_only_or_missing else ""
window = f"{START:%d %b %Y}, 9:00 PM – {END:%d %b %Y}, 9:00 PM IST"
document = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark"><title>Cautio | Footage Request Dashboard</title></head>
<body bgcolor="#0c120f" style="margin:0;padding:0;background:#0c120f;color:#eef3ef;font-family:Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#0c120f"><tr><td align="center" style="padding:8px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%">
<tr><td bgcolor="#141c18" align="center" style="background:#141c18;color:#eef3ef;padding:22px 12px;border:1px solid #35433b;border-top:4px solid #79e3a0;border-radius:10px"><strong style="font-size:32px;letter-spacing:-1.5px;color:#eef3ef">caut<span style="color:#79e3a0">i</span>o</strong><h1 style="font-size:21px;margin:12px 0 5px;color:#eef3ef">Footage Request Dashboard</h1><p style="font-size:13px;margin:0;color:#b5c3ba">Client-wise request monitoring and completion report</p><p style="font-size:12px;margin:7px 0 0;color:#79e3a0">{window}</p></td></tr>
<tr><td style="padding:10px 0"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="table-layout:fixed"><tr>{kpi("Total Requests",total,"#eef3ef")}{kpi("Completed",resolved,"#80e6a5")}</tr><tr>{kpi("Pending",pending,"#ffaaa3")}{kpi("Completion Rate",rate,"#eef3ef")}</tr></table><p style="margin:4px 0 0;text-align:center;font-size:13px;color:#eef3ef">Critical: <strong>{critical}</strong> &nbsp; | &nbsp; Other resolution: <strong>{other}</strong></p></td></tr>
<tr><td bgcolor="#141c18" style="background:#141c18;border:1px solid #35433b;border-radius:8px;padding:14px;color:#eef3ef"><h2 style="margin:0 0 12px;text-align:center;font-size:16px;color:#eef3ef">Completed vs Pending</h2>{status_bar}{legend}</td></tr>
<tr><td style="height:10px;font-size:1px">&nbsp;</td></tr>
<tr><td bgcolor="#141c18" style="background:#141c18;border:1px solid #35433b;border-radius:8px;padding:14px;color:#eef3ef"><h2 style="margin:0 0 6px;text-align:center;font-size:16px;color:#eef3ef">Client-wise Requests</h2><table role="presentation" width="100%" cellspacing="0" cellpadding="0">{client_chart}</table></td></tr>
<tr><td style="height:10px;font-size:1px">&nbsp;</td></tr>
<tr><td bgcolor="#141c18" style="background:#141c18;border:1px solid #35433b;border-radius:8px;padding:8px;color:#eef3ef"><h2 style="margin:7px 0 12px;text-align:center;font-size:16px;color:#eef3ef">Critical Footage Requests ({critical})</h2><table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;table-layout:fixed;width:100%;overflow-wrap:anywhere"><thead><tr bgcolor="#f37870" style="background:#f37870;color:#141c18"><th width="23%" style="padding:8px 4px;font-size:12px;color:#141c18">Client / Vehicle</th><th width="17%" style="padding:8px 4px;font-size:12px;color:#141c18">Priority</th><th width="40%" style="padding:8px 4px;font-size:12px;color:#141c18">Incident Details</th><th width="20%" style="padding:8px 4px;font-size:12px;color:#141c18">Status</th></tr></thead><tbody>{critical_rows}</tbody></table></td></tr>
<tr><td style="height:10px;font-size:1px">&nbsp;</td></tr>
<tr><td bgcolor="#141c18" style="background:#141c18;border:1px solid #35433b;border-radius:8px;padding:8px;color:#eef3ef"><h2 style="margin:7px 0 12px;text-align:center;font-size:16px;color:#eef3ef">Other Footage Requests ({total - critical})</h2><table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;table-layout:fixed;width:100%;overflow-wrap:anywhere"><thead><tr bgcolor="#79e3a0" style="background:#79e3a0;color:#141c18"><th width="23%" style="padding:8px 4px;font-size:12px;color:#141c18">Client / Vehicle</th><th width="17%" style="padding:8px 4px;font-size:12px;color:#141c18">Priority</th><th width="40%" style="padding:8px 4px;font-size:12px;color:#141c18">Incident Details</th><th width="20%" style="padding:8px 4px;font-size:12px;color:#141c18">Status</th></tr></thead><tbody>{rows}</tbody></table>{date_note}</td></tr>
<tr><td align="center" style="padding:12px 5px;font-size:11px;color:#b5c3ba">The future of safety on every journey<br>Customer-requested footage only &bull; Issues- Realtime</td></tr>
</table></td></tr></table></body></html>"""
OUTPUT.write_text(document, encoding="utf-8")
print(f"wrote {OUTPUT}; footage_requests={total}; critical={critical}; resolved={resolved}; not_resolved={not_resolved}")

required_mail = ("REPORT_TO", "MAIL_HOST", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_FROM")
missing_mail = [name for name in required_mail if not os.environ.get(name)]
if missing_mail:
    raise SystemExit("Email not configured; missing required GitHub secrets: " + ", ".join(missing_mail))
message = EmailMessage()
message["Subject"] = f"Cautio customer footage report | {START:%d %b} 9 PM–{END:%d %b} 9 PM IST"
message["From"] = os.environ["MAIL_FROM"]
message["To"] = os.environ["REPORT_TO"]
message.set_content(f"{total} customer footage requests, {critical} critical, {resolved} resolved, {not_resolved} not resolved. Open in an HTML-capable mail app for the full report.")
message.add_alternative(document, subtype="html")
with smtplib.SMTP(os.environ["MAIL_HOST"], int(os.environ["MAIL_PORT"]), timeout=30) as server:
    server.starttls()
    server.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
    server.send_message(message)
print("Customer footage report emailed to configured recipient.")
