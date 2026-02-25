# -*- coding: utf-8 -*-
"""
main.py — テクニカル分析システム エントリーポイント
===================================================
起動フロー:
  1. .env 読み込み（config.py で自動実行）
  2. DB 初期化
  3. 銘柄マスター CSV 読み込み
  4. APIトークン取得
  5. 日次データバッチ更新（バックグラウンド）
  6. GUI 起動
"""

import os
import sys
import logging
import threading
import argparse

# ベースディレクトリを Python パスに追加
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from config import LOG_DIR, DB_PATH
from database import init_db, load_universe_csv
from kabu_api import kabus_get_token
from data_pipeline import run_daily_update
from gui import launch_gui

# ══════════════════════════════════════════════════════════════════════════════
# ログ設定
# ══════════════════════════════════════════════════════════════════════════════
def setup_logging():
    log_file = os.path.join(LOG_DIR, "technical_analysis.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# メイン処理
# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="テクニカル分析システム")
    parser.add_argument("--no-update", action="store_true",
                        help="データ更新をスキップして GUI だけ起動")
    parser.add_argument("--batch-only", action="store_true",
                        help="バッチ更新のみ実行（GUI なし）")
    args = parser.parse_args()

    setup_logging()
    logger.info("=" * 60)
    logger.info("テクニカル分析システム起動")
    logger.info("=" * 60)

    # 1. DB 初期化
    conn = init_db()
    logger.info(f"DB: {DB_PATH}")

    # 2. 銘柄マスター読み込み
    symbols = load_universe_csv(conn)
    logger.info(f"ユニバース: {len(symbols)} 銘柄")

    # 3. API トークン取得 & データ更新
    if not args.no_update:
        try:
            token = kabus_get_token()
            logger.info("APIトークン取得成功")

            if args.batch_only:
                # バッチ更新のみ
                def progress(current, total, symbol):
                    if current % 100 == 0 or current == total:
                        logger.info(f"  進捗: {current}/{total} ({symbol})")

                result = run_daily_update(conn, token, symbols, progress_callback=progress)
                logger.info(f"バッチ更新結果: {result}")
                conn.close()
                return
            else:
                # バックグラウンドでデータ更新
                # ※ SQLite は別スレッドから同じ接続を使えないため、
                #   スレッド専用の接続を作成する
                def background_update():
                    try:
                        bg_conn = init_db()  # スレッド専用 DB 接続
                        result = run_daily_update(bg_conn, token, symbols)
                        bg_conn.close()
                        logger.info(f"バックグラウンド更新完了: {result}")
                    except Exception as e:
                        logger.error(f"バックグラウンド更新エラー: {e}")

                update_thread = threading.Thread(
                    target=background_update, daemon=True
                )
                update_thread.start()
                logger.info("バックグラウンドでデータ更新を開始")

        except Exception as e:
            logger.warning(f"APIトークン取得失敗（オフラインモードで続行）: {e}")
    else:
        logger.info("データ更新スキップ（--no-update）")

    # 4. GUI 起動
    logger.info("GUI起動")
    launch_gui(conn)

    # クリーンアップ
    conn.close()
    logger.info("システム終了")


if __name__ == "__main__":
    main()
