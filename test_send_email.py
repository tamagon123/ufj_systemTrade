"""テストメール送信スクリプト - サンプルデータで進捗メールを1通送信します"""
import sys
import os

# main.py と同じ .env 読み込み
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key:
                os.environ.setdefault(key, val)

_load_dotenv(os.path.join(_BASE_DIR, ".env"))

import smtplib
import datetime
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# .env から読み込み
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
EMAIL_SMTP_USER = os.environ.get("EMAIL_SMTP_USER", "")
EMAIL_SMTP_PASSWORD = os.environ.get("EMAIL_SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

print(f"SMTP Host: {EMAIL_SMTP_HOST}:{EMAIL_SMTP_PORT}")
print(f"From: {EMAIL_SMTP_USER}")
print(f"To: {EMAIL_TO}")
print()

if not EMAIL_SMTP_USER or not EMAIL_SMTP_PASSWORD or not EMAIL_TO:
    print("ERROR: .env に EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_TO を設定してください")
    sys.exit(1)

# サンプルデータ
stats = {
    "interval_detections": 2,
    "interval_symbols": ["3407"],
    "interval_executions": 1,
    "interval_pnl": 4600.0,
    "daily_pnl": -8900.0,
}
time_label = datetime.datetime.now().strftime("%H:%M")
today_str = datetime.datetime.now().strftime("%Y/%m/%d")

symbols_str = ", ".join(stats["interval_symbols"]) if stats["interval_symbols"] else "―"
interval_pnl = stats["interval_pnl"]
daily_pnl = stats["daily_pnl"]

def _pnl_color(v):
    if v > 0: return "#16a34a"
    elif v < 0: return "#dc2626"
    return "#6b7280"

def _pnl_str(v):
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f} 円"

html = f"""\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>トレード進捗レポート</title>
</head>
<body style="margin:0; padding:0; background-color:#f3f4f6; font-family:'Segoe UI','Helvetica Neue','メイリオ',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6; padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.08); overflow:hidden;">

<!-- Header -->
<tr>
<td style="background:linear-gradient(135deg,#1e3a5f,#2563eb); padding:20px 28px;">
  <h1 style="margin:0; color:#ffffff; font-size:18px; font-weight:600;">📊 トレード進捗レポート</h1>
  <p style="margin:6px 0 0; color:#bfdbfe; font-size:13px;">{today_str}　{time_label} 時点 【テスト送信】</p>
</td>
</tr>

<!-- 30分間サマリー -->
<tr>
<td style="padding:24px 28px 8px;">
  <h2 style="margin:0 0 14px; font-size:15px; color:#374151; border-bottom:2px solid #e5e7eb; padding-bottom:8px;">⏱ 直近30分間</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="padding:8px 0; font-size:14px; color:#6b7280; width:40%;">検知数</td>
      <td style="padding:8px 0; font-size:16px; color:#111827; font-weight:600; text-align:right;">{stats["interval_detections"]} 件</td>
    </tr>
    <tr style="background-color:#f9fafb;">
      <td style="padding:8px 0 8px 8px; font-size:14px; color:#6b7280; border-radius:6px 0 0 6px;">取引銘柄</td>
      <td style="padding:8px 8px 8px 0; font-size:14px; color:#111827; text-align:right; border-radius:0 6px 6px 0;">{symbols_str}</td>
    </tr>
    <tr>
      <td style="padding:8px 0; font-size:14px; color:#6b7280;">約定数</td>
      <td style="padding:8px 0; font-size:16px; color:#111827; font-weight:600; text-align:right;">{stats["interval_executions"]} 件</td>
    </tr>
    <tr style="background-color:#f9fafb;">
      <td style="padding:8px 0 8px 8px; font-size:14px; color:#6b7280; border-radius:6px 0 0 6px;">損益（確定）</td>
      <td style="padding:8px 8px 8px 0; font-size:16px; font-weight:700; text-align:right; color:{_pnl_color(interval_pnl)}; border-radius:0 6px 6px 0;">{_pnl_str(interval_pnl)}</td>
    </tr>
  </table>
</td>
</tr>

<!-- 本日累計 -->
<tr>
<td style="padding:16px 28px 24px;">
  <h2 style="margin:0 0 14px; font-size:15px; color:#374151; border-bottom:2px solid #e5e7eb; padding-bottom:8px;">📅 本日の累計</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="padding:10px 12px; font-size:14px; color:#6b7280; background-color:{_pnl_color(daily_pnl)}10; border-radius:8px 0 0 8px;">累計確定損益</td>
      <td style="padding:10px 12px; font-size:20px; font-weight:700; text-align:right; color:{_pnl_color(daily_pnl)}; background-color:{_pnl_color(daily_pnl)}10; border-radius:0 8px 8px 0;">{_pnl_str(daily_pnl)}</td>
    </tr>
  </table>
</td>
</tr>

<!-- Footer -->
<tr>
<td style="background-color:#f9fafb; padding:14px 28px; border-top:1px solid #e5e7eb;">
  <p style="margin:0; font-size:11px; color:#9ca3af; text-align:center;">UFJ System Trade — 自動生成メール</p>
</td>
</tr>

</table>
</td></tr>
</table>
</body>
</html>
"""

subject = f"[トレード進捗] {today_str} {time_label} 【テスト】"

msg = MIMEMultipart("alternative")
msg["Subject"] = subject
msg["From"] = EMAIL_SMTP_USER
msg["To"] = EMAIL_TO
msg.attach(MIMEText(html, "html", "utf-8"))

print("メール送信中...")
try:
    with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
        server.sendmail(EMAIL_SMTP_USER, EMAIL_TO, msg.as_string())
    print("✅ テストメール送信成功！受信ボックスを確認してください。")
except Exception as e:
    print(f"❌ 送信エラー: {e}")
    sys.exit(1)
