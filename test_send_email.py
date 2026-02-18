"""test email with trade history from API format + env vars"""
import sys, os, smtplib, datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_dotenv(path):
    if not os.path.isfile(path): return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key: os.environ.setdefault(key, val)

_load_dotenv(os.path.join(_BASE_DIR, ".env"))

EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
EMAIL_SMTP_USER = os.environ.get("EMAIL_SMTP_USER", "")
EMAIL_SMTP_PASSWORD = os.environ.get("EMAIL_SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

if not EMAIL_SMTP_USER or not EMAIL_SMTP_PASSWORD or not EMAIL_TO:
    print("ERROR: .env needs EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_TO")
    sys.exit(1)

# --- sample data ---
stats = {
    "interval_detections": 5,
    "interval_symbols": ["7203", "9984", "6758"],
    "interval_executions": 3,
    "interval_pnl": -1200.0,
    "daily_pnl": 8700.0,
}

# API-sourced executions (sample data mimicking kabus_get_orders response)
executions = [
    {"time": "09:31:05", "symbol": "7203", "name": "トヨタ自動車",      "price": 2850.0, "qty": 100, "side": "買", "trade_type": "新規"},
    {"time": "09:45:12", "symbol": "7203", "name": "トヨタ自動車",      "price": 2892.0, "qty": 100, "side": "売", "trade_type": "返済"},
    {"time": "10:05:33", "symbol": "9984", "name": "ソフトバンクグループ", "price": 8920.0, "qty": 100, "side": "売", "trade_type": "新規"},
    {"time": "10:12:44", "symbol": "9984", "name": "ソフトバンクグループ", "price": 8980.0, "qty": 100, "side": "買", "trade_type": "返済"},
    {"time": "10:30:05", "symbol": "6758", "name": "ソニーグループ",    "price": 13500.0, "qty": 100, "side": "買", "trade_type": "新規"},
    {"time": "13:15:48", "symbol": "6758", "name": "ソニーグループ",    "price": 13420.0, "qty": 100, "side": "売", "trade_type": "返済"},
]

time_label = datetime.datetime.now().strftime("%H:%M")
today_str = datetime.datetime.now().strftime("%Y/%m/%d")

symbols_str = ", ".join(stats["interval_symbols"])
interval_pnl = stats["interval_pnl"]
daily_pnl = stats["daily_pnl"]

def _pnl_color(v):
    if v > 0: return "#16a34a"
    elif v < 0: return "#dc2626"
    return "#6b7280"
def _pnl_str(v):
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f} 円"

# --- trades table ---
trades_rows = ""
for i, t in enumerate(executions):
    bg = ' style="background-color:#f9fafb;"' if i % 2 == 1 else ''
    side_str = t.get("side", "")
    side_color = "#2563eb" if side_str == "買" else "#dc2626"
    tt = t.get("trade_type", "")
    tt_color = "#059669" if tt == "新規" else "#7c3aed" if tt == "返済" else "#374151"
    price_val = t.get("price", 0)
    price_str = f"{price_val:,.1f}" if isinstance(price_val, float) and price_val > 0 else ""
    trades_rows += f'''<tr{bg}>
  <td style="padding:6px 4px;font-size:12px;color:#374151;white-space:nowrap;">{t.get("time","")}</td>
  <td style="padding:6px 4px;font-size:12px;color:#374151;">{t.get("symbol","")}</td>
  <td style="padding:6px 4px;font-size:12px;color:#374151;">{t.get("name","")}</td>
  <td style="padding:6px 4px;font-size:12px;color:#374151;text-align:right;">{price_str}</td>
  <td style="padding:6px 4px;font-size:12px;color:{side_color};font-weight:600;text-align:center;">{side_str}</td>
  <td style="padding:6px 4px;font-size:12px;color:{tt_color};font-weight:600;text-align:center;">{tt}</td>
  <td style="padding:6px 4px;font-size:12px;color:#374151;text-align:right;">{t.get("qty", 0)}</td>
</tr>
'''

# --- env table ---
env_rows = ""
env_items = []
for key, val in sorted(os.environ.items()):
    if key.startswith(("KABUS_", "ORDER_", "WATCH_", "SURGE_", "CRASH_",
                       "OPENING_", "PM_OPENING_", "AUTO_EXIT_", "EDINET_",
                       "NEWS_", "EMAIL_", "ENABLE_", "PROMPT_", "MANUAL_",
                       "LUNCH_", "MORNING_", "AFTERHOURS_", "SPECIAL_")):
        display_val = val
        if "PASSWORD" in key or "API_KEY" in key:
            display_val = "****" if val else ""
        env_items.append({"key": key, "value": display_val})
for i, ev in enumerate(env_items):
    bg = ' style="background-color:#f9fafb;"' if i % 2 == 1 else ''
    env_rows += f'<tr{bg}><td style="padding:4px 6px;font-size:11px;color:#6b7280;font-family:monospace;">{ev["key"]}</td><td style="padding:4px 6px;font-size:11px;color:#111827;font-family:monospace;word-break:break-all;">{ev["value"]}</td></tr>\n'

html = f"""\
<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>trade report</title></head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:'Segoe UI','Helvetica Neue',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.08);overflow:hidden;">

<tr><td style="background:linear-gradient(135deg,#1e3a5f,#2563eb);padding:20px 28px;">
  <h1 style="margin:0;color:#fff;font-size:18px;font-weight:600;">📊 トレード進捗レポート</h1>
  <p style="margin:6px 0 0;color:#bfdbfe;font-size:13px;">{today_str} {time_label} 時点 【テスト送信】</p>
</td></tr>

<tr><td style="padding:24px 28px 8px;">
  <h2 style="margin:0 0 14px;font-size:15px;color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:8px;">⏱ 直近30分間</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="padding:8px 0;font-size:14px;color:#6b7280;width:40%;">検知数</td><td style="padding:8px 0;font-size:16px;color:#111827;font-weight:600;text-align:right;">{stats["interval_detections"]} 件</td></tr>
    <tr style="background-color:#f9fafb;"><td style="padding:8px 0 8px 8px;font-size:14px;color:#6b7280;">取引銘柄</td><td style="padding:8px 8px 8px 0;font-size:14px;color:#111827;text-align:right;">{symbols_str}</td></tr>
    <tr><td style="padding:8px 0;font-size:14px;color:#6b7280;">約定数</td><td style="padding:8px 0;font-size:16px;color:#111827;font-weight:600;text-align:right;">{stats["interval_executions"]} 件</td></tr>
    <tr style="background-color:#f9fafb;"><td style="padding:8px 0 8px 8px;font-size:14px;color:#6b7280;">損益（確定）</td><td style="padding:8px 8px 8px 0;font-size:16px;font-weight:700;text-align:right;color:{_pnl_color(interval_pnl)};">{_pnl_str(interval_pnl)}</td></tr>
  </table>
</td></tr>

<tr><td style="padding:16px 28px 8px;">
  <h2 style="margin:0 0 14px;font-size:15px;color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:8px;">📅 本日の累計</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="padding:10px 12px;font-size:14px;color:#6b7280;background-color:{_pnl_color(daily_pnl)}10;border-radius:8px 0 0 8px;">累計確定損益</td>
    <td style="padding:10px 12px;font-size:20px;font-weight:700;text-align:right;color:{_pnl_color(daily_pnl)};background-color:{_pnl_color(daily_pnl)}10;border-radius:0 8px 8px 0;">{_pnl_str(daily_pnl)}</td></tr>
  </table>
</td></tr>

<tr><td style="padding:16px 28px 8px;">
  <h2 style="margin:0 0 14px;font-size:15px;color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:8px;">📋 本日の約定履歴</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
    <tr style="background-color:#1e3a5f;">
      <th style="padding:8px 4px;font-size:11px;color:#fff;text-align:left;font-weight:600;">時刻</th>
      <th style="padding:8px 4px;font-size:11px;color:#fff;text-align:left;font-weight:600;">コード</th>
      <th style="padding:8px 4px;font-size:11px;color:#fff;text-align:left;font-weight:600;">銘柄名</th>
      <th style="padding:8px 4px;font-size:11px;color:#fff;text-align:right;font-weight:600;">約定価格</th>
      <th style="padding:8px 4px;font-size:11px;color:#fff;text-align:center;font-weight:600;">売買</th>
      <th style="padding:8px 4px;font-size:11px;color:#fff;text-align:center;font-weight:600;">取引区分</th>
      <th style="padding:8px 4px;font-size:11px;color:#fff;text-align:right;font-weight:600;">数量</th>
    </tr>
    {trades_rows}
  </table>
</td></tr>

<tr><td style="padding:16px 28px 24px;">
  <h2 style="margin:0 0 14px;font-size:15px;color:#374151;border-bottom:2px solid #e5e7eb;padding-bottom:8px;">⚙ 現在の設定値</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
    <tr style="background-color:#374151;">
      <th style="padding:6px;font-size:11px;color:#fff;text-align:left;font-weight:600;width:50%;">設定名</th>
      <th style="padding:6px;font-size:11px;color:#fff;text-align:left;font-weight:600;">値</th>
    </tr>
    {env_rows}
  </table>
</td></tr>

<tr><td style="background-color:#f9fafb;padding:14px 28px;border-top:1px solid #e5e7eb;">
  <p style="margin:0;font-size:11px;color:#9ca3af;text-align:center;">UFJ System Trade -- auto-generated</p>
</td></tr>

</table></td></tr></table></body></html>
"""

subject = f"[trade report] {today_str} {time_label} [test - API format]"
msg = MIMEMultipart("alternative")
msg["Subject"] = subject
msg["From"] = EMAIL_SMTP_USER
msg["To"] = EMAIL_TO
msg.attach(MIMEText(html, "html", "utf-8"))

print(f"From: {EMAIL_SMTP_USER}")
print(f"To: {EMAIL_TO}")
print("sending...")
try:
    with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
        server.sendmail(EMAIL_SMTP_USER, EMAIL_TO, msg.as_string())
    print("[OK] test email sent successfully")
except Exception as e:
    print(f"[ERROR] send failed: {e}")
    sys.exit(1)
