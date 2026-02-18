"""テストメール送信スクリプト - 実際のロジックを使用して進捗メールを送信する"""
import sys
import os

# main.pyと同じディレクトリに移動
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# .envの読み込みとモジュールインポートのため、main.pyを直接利用
# main.pyのグローバル変数を読み込む
from main import (
    _load_dotenv,
    kabus_get_token,
    create_email_stats,
    send_progress_email,
    _fetch_todays_executions,
    _compute_daily_pnl,
    EMAIL_ENABLE,
    EMAIL_SMTP_USER,
    EMAIL_TO,
)

def main():
    print("=" * 60)
    print("テストメール送信 - 実際のロジック使用")
    print("=" * 60)

    # 設定確認
    print(f"\n[設定確認]")
    print(f"  EMAIL_ENABLE  : {EMAIL_ENABLE}")
    print(f"  EMAIL_SMTP_USER: {EMAIL_SMTP_USER}")
    print(f"  EMAIL_TO      : {EMAIL_TO}")

    if not EMAIL_SMTP_USER or not EMAIL_TO:
        print("\n[ERROR] メール設定が未設定です。.envのEMAIL_*を確認してください。")
        return

    # KabuStation APIトークン取得
    print("\n[1/4] KabuStation APIトークン取得中...")
    try:
        token = kabus_get_token()
        print(f"  → トークン取得成功: {token[:8]}...")
    except Exception as e:
        print(f"  → トークン取得失敗: {e}")
        print("  → トークンなしで続行します（約定履歴/損益は取得できません）")
        token = None

    # 約定履歴取得テスト
    print("\n[2/4] 約定履歴取得テスト...")
    try:
        executions = _fetch_todays_executions(token)
        print(f"  → 本日の約定: {len(executions)}件")
        for ex in executions:
            print(f"     {ex.get('time','')} {ex.get('symbol','')} {ex.get('name','')} "
                  f"{ex.get('side','')} {ex.get('trade_type','')} "
                  f"{ex.get('price',0):,.1f}円 x{ex.get('qty',0)}")
    except Exception as e:
        print(f"  → 約定履歴取得エラー: {e}")
        executions = []

    # 損益計算テスト
    print("\n[3/4] 損益計算テスト (APIから都度取得)...")
    try:
        realized, unrealized = _compute_daily_pnl(token, executions)
        total = realized + unrealized
        print(f"  → 実現損益  : {realized:+,.0f}円")
        print(f"  → 含み損益  : {unrealized:+,.0f}円")
        print(f"  → 合計      : {total:+,.0f}円")
    except Exception as e:
        print(f"  → 損益計算エラー: {e}")

    # メール送信テスト
    print("\n[4/4] テストメール送信中...")
    stats = create_email_stats()
    stats["interval_detections"] = 0
    stats["interval_symbols"] = []
    stats["interval_executions"] = len(executions)

    time_label = "17:30（テスト送信）"

    try:
        result = send_progress_email(stats, time_label, token=token)
        if result:
            print(f"\n✅ テストメール送信成功！ → {EMAIL_TO}")
        else:
            print(f"\n❌ テストメール送信失敗")
    except Exception as e:
        print(f"\n❌ テストメール送信例外: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("テスト完了")

if __name__ == "__main__":
    main()
