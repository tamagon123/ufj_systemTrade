# -*- coding: utf-8 -*-
"""
gui.py — テクニカル分析 GUI
=============================
tkinter + matplotlib を統合したデスクトップアプリケーション。
- 左ペイン: 銘柄リスト（検索・フィルタ）+ 本日のシグナル + 過去データ取得
- 中央:    ローソク足チャート + SMA + 出来高 + 価格帯別出来高（オーバーレイ）
           + OHLCVクロスヘア表示
- 右ペイン: シグナル一覧（良い=🟢 / 悪い=🔴）+ パフォーマンス統計
- 下部:    日付範囲選択・タイムフレーム切替・MA パラメータ設定
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import OrderedDict

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

from config import MA_PARAMS, DB_PATH, BASE_DIR
from database import init_db, get_daily, get_universe, load_universe_csv
from signals import add_sma_columns, detect_ma_signals, get_latest_signals
from candlestick import detect_all_patterns
from timeframes import resample_weekly, resample_monthly
from volume_profile import compute_volume_profile, find_support_resistance
from history_fetcher import fetch_history_batch
from signal_performance import analyze_signal_performance, format_performance_text
from data_pipeline import run_daily_update
from kabu_api import kabus_get_token

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# フォント設定
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_FONT_SCALE = 1.0  # 1.0 = 標準, 1.2 = やや大, 1.5 = 大


def _fs(base_size: int, scale: float = DEFAULT_FONT_SCALE) -> int:
    """フォントサイズをスケーリング"""
    return max(7, int(base_size * scale))


# ══════════════════════════════════════════════════════════════════════════════
# メイン GUI クラス
# ══════════════════════════════════════════════════════════════════════════════
class TechnicalAnalysisApp:
    """テクニカル分析メインウィンドウ"""

    def __init__(self, root: tk.Tk, conn: sqlite3.Connection):
        self.root = root
        self.conn = conn
        self.root.title("国内全上場株式 テクニカル分析システム")
        self.root.geometry("1600x900")
        self.root.minsize(1200, 700)

        # 状態
        self.current_symbol = None
        self.current_timeframe = "daily"
        self.current_df = pd.DataFrame()       # 全期間データ
        self.current_view_df = pd.DataFrame()  # 表示範囲データ
        self.ma_params = {k: dict(v) for k, v in MA_PARAMS.items()}
        self._signal_cache = {}
        self._crosshair_lines = []  # クロスヘア線

        # フォントスケール
        self.font_scale = DEFAULT_FONT_SCALE

        # スタイル
        style = ttk.Style()
        style.theme_use("clam")

        self._build_ui()
        self._load_symbols()

    # ──────────────────────────────────────────────────────────────────────
    # UI 構築
    # ──────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        s = self.font_scale

        # メインフレーム
        main_pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pw.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ===== 左ペイン：銘柄リスト + 本日のシグナル =====
        left_frame = ttk.Frame(main_pw, width=280)
        main_pw.add(left_frame, weight=0)

        # --- Notebook で「銘柄一覧」と「本日のシグナル」を切替 ---
        self.left_nb = ttk.Notebook(left_frame)
        self.left_nb.pack(fill=tk.BOTH, expand=True)

        # --- Tab 1: 銘柄検索 ---
        tab_symbols = ttk.Frame(self.left_nb)
        self.left_nb.add(tab_symbols, text="📋 銘柄一覧")

        ttk.Label(tab_symbols, text="🔍 銘柄検索",
                  font=("", _fs(12, s), "bold")).pack(pady=(4, 2))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        search_entry = ttk.Entry(tab_symbols, textvariable=self.search_var,
                                 width=28, font=("", _fs(11, s)))
        search_entry.pack(padx=4, pady=2)

        # フィルタ: 市場
        filter_frame = ttk.Frame(tab_symbols)
        filter_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(filter_frame, text="市場:",
                  font=("", _fs(10, s))).pack(side=tk.LEFT)
        self.market_var = tk.StringVar(value="すべて")
        self.market_combo = ttk.Combobox(
            filter_frame, textvariable=self.market_var,
            values=["すべて"], state="readonly", width=18,
            font=("", _fs(10, s)),
        )
        self.market_combo.pack(side=tk.LEFT, padx=2)
        self.market_combo.bind("<<ComboboxSelected>>", self._on_search)

        # 銘柄リスト
        list_frame = ttk.Frame(tab_symbols)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.symbol_listbox = tk.Listbox(
            list_frame, yscrollcommand=scrollbar.set,
            font=("Consolas", _fs(11, s)), selectmode=tk.SINGLE,
        )
        self.symbol_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.symbol_listbox.yview)
        self.symbol_listbox.bind("<<ListboxSelect>>", self._on_symbol_select)

        self.symbol_count_label = ttk.Label(tab_symbols, text="0 銘柄",
                                            font=("", _fs(10, s)))
        self.symbol_count_label.pack(pady=2)

        # --- Tab 2: 本日のシグナル ---
        tab_today = ttk.Frame(self.left_nb)
        self.left_nb.add(tab_today, text="🔔 本日のシグナル")

        # 出来高フィルタ
        vol_filter_frame = ttk.Frame(tab_today)
        vol_filter_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(vol_filter_frame, text="出来高≧",
                  font=("", _fs(10, s))).pack(side=tk.LEFT)
        self.scan_vol_var = tk.StringVar(value="0")
        ttk.Entry(vol_filter_frame, textvariable=self.scan_vol_var,
                  width=12, font=("", _fs(10, s))).pack(side=tk.LEFT, padx=2)
        ttk.Label(vol_filter_frame, text="株",
                  font=("", _fs(10, s))).pack(side=tk.LEFT)

        # 時間軸チェックボックス
        tf_frame = ttk.Frame(tab_today)
        tf_frame.pack(fill=tk.X, padx=4, pady=(2, 2))
        self.scan_weekly_var = tk.BooleanVar(value=False)
        self.scan_monthly_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tf_frame, text="週足を含める",
                        variable=self.scan_weekly_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(tf_frame, text="月足を含める",
                        variable=self.scan_monthly_var).pack(side=tk.LEFT)

        scan_bar = ttk.Frame(tab_today)
        scan_bar.pack(fill=tk.X, padx=4, pady=2)
        self.scan_btn = ttk.Button(scan_bar, text="🔍 全銘柄スキャン",
                                   command=self._on_scan_today)
        self.scan_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.scan_progress_var = tk.DoubleVar(value=0)
        self.scan_progress = ttk.Progressbar(
            tab_today, variable=self.scan_progress_var, maximum=100,
        )
        self.scan_progress.pack(fill=tk.X, padx=4, pady=2)

        # 本日のシグナル結果
        today_container = ttk.Frame(tab_today)
        today_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        today_scroll = ttk.Scrollbar(today_container)
        today_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.today_text = tk.Text(
            today_container, width=35, wrap=tk.WORD,
            font=("", _fs(10, s)), bg="#1e1e2e", fg="#cdd6f4",
            yscrollcommand=today_scroll.set, state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
        )
        self.today_text.pack(fill=tk.BOTH, expand=True)
        today_scroll.config(command=self.today_text.yview)
        self.today_text.tag_configure("bullish", foreground="#a6e3a1")
        self.today_text.tag_configure("bearish", foreground="#f38ba8")
        self.today_text.tag_configure("header",
                                       foreground="#89b4fa",
                                       font=("", _fs(11, s), "bold"))
        self.today_text.tag_configure("symbol",
                                       foreground="#f9e2af",
                                       font=("", _fs(11, s), "bold"))
        self.today_text.tag_configure("link",
                                       foreground="#89dceb",
                                       font=("", _fs(10, s), "underline"))
        # クリックで銘柄にジャンプ
        self.today_text.tag_bind("link", "<Button-1>", self._on_today_click)
        self._today_link_map = {}  # tag_name -> code

        # データ取得ボタン群（タブ外・下部）
        self.daily_btn = ttk.Button(
            left_frame, text="📡 本日データ取得",
            command=self._on_fetch_daily,
        )
        self.daily_btn.pack(fill=tk.X, padx=4, pady=(4, 2))

        self.fetch_btn = ttk.Button(
            left_frame, text="📥 過去データ取得",
            command=self._on_fetch_history,
        )
        self.fetch_btn.pack(fill=tk.X, padx=4, pady=(2, 2))

        # フォントサイズ設定
        font_frame = ttk.Frame(left_frame)
        font_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(font_frame, text="文字サイズ:",
                  font=("", _fs(9, s))).pack(side=tk.LEFT)
        self.font_scale_var = tk.DoubleVar(value=self.font_scale)
        for scale_val, label in [(0.8, "小"), (1.0, "標準"), (1.2, "大"), (1.5, "特大")]:
            ttk.Radiobutton(
                font_frame, text=label,
                variable=self.font_scale_var, value=scale_val,
                command=self._on_font_scale_change,
            ).pack(side=tk.LEFT, padx=2)

        # ===== 中央ペイン：チャート =====
        center_frame = ttk.Frame(main_pw)
        main_pw.add(center_frame, weight=3)

        # チャート info bar
        info_bar = ttk.Frame(center_frame)
        info_bar.pack(fill=tk.X, padx=4, pady=2)
        self.info_label = ttk.Label(info_bar, text="銘柄を選択してください",
                                    font=("", _fs(13, s), "bold"))
        self.info_label.pack(side=tk.LEFT)

        # タイムフレーム切替
        tf_frame = ttk.Frame(info_bar)
        tf_frame.pack(side=tk.RIGHT)
        self.tf_var = tk.StringVar(value="daily")
        for tf, label in [("daily", "日足"), ("weekly", "週足"), ("monthly", "月足")]:
            ttk.Radiobutton(
                tf_frame, text=label, variable=self.tf_var, value=tf,
                command=self._on_timeframe_change,
            ).pack(side=tk.LEFT, padx=4)

        # 画像保存ボタン
        ttk.Button(info_bar, text="📷 保存",
                   command=self._save_chart).pack(side=tk.RIGHT, padx=4)

        # --- OHLCV 表示バー ---
        self.ohlcv_frame = ttk.Frame(center_frame)
        self.ohlcv_frame.pack(fill=tk.X, padx=4, pady=(0, 1))
        self.ohlcv_label = tk.Label(
            self.ohlcv_frame, text="ローソク足にマウスを合わせるとOHLCVを表示",
            font=("Consolas", _fs(10, s)),
            bg="#313244", fg="#a6adc8", anchor="w", padx=8, pady=3,
        )
        self.ohlcv_label.pack(fill=tk.X)

        # --- 日付範囲選択バー ---
        date_bar = ttk.Frame(center_frame)
        date_bar.pack(fill=tk.X, padx=4, pady=(0, 2))

        ttk.Label(date_bar, text="📅 表示期間:",
                  font=("", _fs(10, s))).pack(side=tk.LEFT)

        # プリセットボタン
        for months, label in [(1, "1M"), (3, "3M"), (6, "6M"),
                               (12, "1Y"), (24, "2Y"), (0, "全期間")]:
            btn = ttk.Button(
                date_bar, text=label, width=5,
                command=lambda m=months: self._set_date_range_months(m),
            )
            btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(date_bar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=6)

        # カスタム日付入力
        ttk.Label(date_bar, text="開始:",
                  font=("", _fs(9, s))).pack(side=tk.LEFT)
        self.date_start_var = tk.StringVar()
        self.date_start_entry = ttk.Entry(
            date_bar, textvariable=self.date_start_var, width=12,
            font=("", _fs(10, s)),
        )
        self.date_start_entry.pack(side=tk.LEFT, padx=2)

        ttk.Label(date_bar, text="終了:",
                  font=("", _fs(9, s))).pack(side=tk.LEFT)
        self.date_end_var = tk.StringVar()
        self.date_end_entry = ttk.Entry(
            date_bar, textvariable=self.date_end_var, width=12,
            font=("", _fs(10, s)),
        )
        self.date_end_entry.pack(side=tk.LEFT, padx=2)

        ttk.Button(date_bar, text="適用",
                   command=self._apply_date_range).pack(side=tk.LEFT, padx=4)

        # matplotlib Figure (2 subplots: 価格+出来高)
        self.fig, self.axes = plt.subplots(
            2, 1, figsize=(12, 7),
            gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05},
            facecolor="#1e1e2e",
        )
        self.fig.subplots_adjust(left=0.07, right=0.93, top=0.96, bottom=0.08)
        for ax in self.axes:
            ax.set_facecolor("#1e1e2e")
            for spine in ax.spines.values():
                spine.set_color("#45475a")

        self.canvas = FigureCanvasTkAgg(self.fig, master=center_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # クリックイベントでクロスヘア+OHLCV表示
        self.canvas.mpl_connect("button_press_event", self._on_chart_click)

        toolbar_frame = ttk.Frame(center_frame)
        toolbar_frame.pack(fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()

        # ===== 右ペイン：シグナル =====
        right_frame = ttk.Frame(main_pw, width=320)
        main_pw.add(right_frame, weight=0)

        ttk.Label(right_frame, text="📊 シグナル一覧",
                  font=("", _fs(12, s), "bold")).pack(pady=(4, 2))

        # シグナルスクロールビュー
        signal_container = ttk.Frame(right_frame)
        signal_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        signal_scroll = ttk.Scrollbar(signal_container)
        signal_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.signal_text = tk.Text(
            signal_container, width=38, wrap=tk.WORD,
            font=("", _fs(11, s)), bg="#1e1e2e", fg="#cdd6f4",
            yscrollcommand=signal_scroll.set, state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
        )
        self.signal_text.pack(fill=tk.BOTH, expand=True)
        signal_scroll.config(command=self.signal_text.yview)

        # タグ設定
        self.signal_text.tag_configure("bullish", foreground="#a6e3a1")
        self.signal_text.tag_configure("bearish", foreground="#f38ba8")
        self.signal_text.tag_configure("header",
                                        foreground="#89b4fa",
                                        font=("", _fs(12, s), "bold"))
        self.signal_text.tag_configure("date_tag", foreground="#6c7086")
        self.signal_text.tag_configure("perf",
                                        foreground="#7f849c",
                                        font=("", _fs(9, s)))

        # ===== 下部バー：MA パラメータ =====
        bottom_frame = ttk.LabelFrame(self.root, text="移動平均線パラメータ")
        bottom_frame.pack(fill=tk.X, padx=4, pady=4)

        self.ma_spinboxes = {}
        for tf, tf_label in [("daily", "日足"), ("weekly", "週足"),
                              ("monthly", "月足")]:
            tf_grp = ttk.Frame(bottom_frame)
            tf_grp.pack(side=tk.LEFT, padx=10, pady=2)
            ttk.Label(tf_grp, text=tf_label,
                      font=("", _fs(10, s), "bold")).pack(side=tk.LEFT, padx=(0, 4))
            for pname, plabel in [("short", "短期"), ("medium", "中期"),
                                   ("long", "長期")]:
                ttk.Label(tf_grp, text=plabel,
                          font=("", _fs(9, s))).pack(side=tk.LEFT)
                var = tk.IntVar(value=self.ma_params[tf][pname])
                sb = ttk.Spinbox(tf_grp, from_=1, to=999, width=4,
                                 textvariable=var, font=("", _fs(10, s)))
                sb.pack(side=tk.LEFT, padx=(0, 6))
                self.ma_spinboxes[(tf, pname)] = var

        ttk.Button(bottom_frame, text="更新",
                   command=self._apply_ma_params).pack(side=tk.RIGHT, padx=10)

    # ──────────────────────────────────────────────────────────────────────
    # フォントスケール変更
    # ──────────────────────────────────────────────────────────────────────
    def _on_font_scale_change(self):
        """フォントスケールを変更して全体を再構築"""
        new_scale = self.font_scale_var.get()
        if new_scale == self.font_scale:
            return
        self.font_scale = new_scale
        # 主要ウィジェットのフォントを更新
        s = self.font_scale
        self.info_label.config(font=("", _fs(13, s), "bold"))
        self.ohlcv_label.config(font=("Consolas", _fs(10, s)))
        self.symbol_listbox.config(font=("Consolas", _fs(11, s)))
        self.signal_text.config(font=("", _fs(11, s)))
        self.signal_text.tag_configure("header",
                                        font=("", _fs(12, s), "bold"))
        self.signal_text.tag_configure("perf",
                                        font=("", _fs(9, s)))
        self.today_text.config(font=("", _fs(10, s)))
        self.today_text.tag_configure("header",
                                       font=("", _fs(11, s), "bold"))
        self.today_text.tag_configure("symbol",
                                       font=("", _fs(11, s), "bold"))
        # チャートを再描画
        if not self.current_view_df.empty:
            params = self.ma_params.get(self.current_timeframe,
                                        self.ma_params["daily"])
            self._draw(self.current_view_df, params)

    # ──────────────────────────────────────────────────────────────────────
    # OHLCV クロスヘア表示
    # ──────────────────────────────────────────────────────────────────────
    def _on_chart_click(self, event):
        """チャートをクリックした時、OHLCVデータを表示"""
        if self.current_view_df.empty or event.inaxes != self.axes[0]:
            return

        df = self.current_view_df
        x_idx = int(round(event.xdata)) if event.xdata is not None else -1
        if x_idx < 0 or x_idx >= len(df):
            return

        row = df.iloc[x_idx]
        date_str = df.index[x_idx].strftime("%Y/%m/%d")
        change = row["close"] - row["open"]
        change_pct = (change / row["open"] * 100) if row["open"] != 0 else 0
        sign = "+" if change >= 0 else ""
        color = "#e74c3c" if change >= 0 else "#3498db"

        vol_str = f"{row['volume']:,.0f}"

        text = (
            f"📅 {date_str}  │  "
            f"始値: {row['open']:,.0f}  "
            f"高値: {row['high']:,.0f}  "
            f"安値: {row['low']:,.0f}  "
            f"終値: {row['close']:,.0f}  "
            f"({sign}{change:,.0f} / {sign}{change_pct:.2f}%)  │  "
            f"出来高: {vol_str}"
        )
        self.ohlcv_label.config(text=text, fg=color)

        # クロスヘア線の更新
        ax = self.axes[0]
        for line in self._crosshair_lines:
            try:
                line.remove()
            except Exception:
                pass
        self._crosshair_lines = []

        vline = ax.axvline(x=x_idx, color="#585b70", linewidth=0.7,
                           linestyle="--", alpha=0.6)
        hline = ax.axhline(y=row["close"], color="#585b70", linewidth=0.7,
                           linestyle="--", alpha=0.6)
        self._crosshair_lines = [vline, hline]
        self.canvas.draw_idle()

    # ──────────────────────────────────────────────────────────────────────
    # 日付範囲
    # ──────────────────────────────────────────────────────────────────────
    def _set_date_range_months(self, months: int):
        """プリセット期間を設定して再描画"""
        if self.current_df.empty:
            return
        if months == 0:
            self.date_start_var.set("")
            self.date_end_var.set("")
        else:
            end = self.current_df.index[-1]
            start = end - pd.DateOffset(months=months)
            self.date_start_var.set(start.strftime("%Y-%m-%d"))
            self.date_end_var.set(end.strftime("%Y-%m-%d"))
        self._apply_date_range()

    def _apply_date_range(self):
        if self.current_df.empty:
            return
        self._redraw_with_range()

    def _get_view_df(self) -> pd.DataFrame:
        df = self.current_df
        if df.empty:
            return df
        start = self.date_start_var.get().strip()
        end = self.date_end_var.get().strip()
        try:
            if start:
                df = df[df.index >= pd.Timestamp(start)]
            if end:
                df = df[df.index <= pd.Timestamp(end)]
        except Exception:
            pass
        return df

    def _redraw_with_range(self):
        if self.current_df.empty:
            return
        df = self._get_view_df()
        if df.empty:
            return
        self.current_view_df = df
        tf = self.current_timeframe
        params = self.ma_params.get(tf, self.ma_params["daily"])
        self._draw(df, params)
        self._update_signals(df, tf, params)

    # ──────────────────────────────────────────────────────────────────────
    # 銘柄リスト
    # ──────────────────────────────────────────────────────────────────────
    def _load_symbols(self):
        self.universe_df = get_universe(self.conn)
        if self.universe_df.empty:
            load_universe_csv(self.conn)
            self.universe_df = get_universe(self.conn)

        markets = sorted(self.universe_df["market"].unique().tolist())
        self.market_combo["values"] = ["すべて"] + markets
        self._refresh_symbol_list()

    def _refresh_symbol_list(self):
        keyword = self.search_var.get().strip()
        market = self.market_var.get()

        df = self.universe_df
        if market and market != "すべて":
            df = df[df["market"] == market]
        if keyword:
            mask = (
                df["code"].str.contains(keyword, case=False, na=False)
                | df["name"].str.contains(keyword, case=False, na=False)
            )
            df = df[mask]

        self.symbol_listbox.delete(0, tk.END)
        for _, row in df.iterrows():
            display = f"{row['code']}  {row['name']}"
            self.symbol_listbox.insert(tk.END, display)
        self.symbol_count_label.config(text=f"{len(df)} 銘柄")

    def _on_search(self, *args):
        self._refresh_symbol_list()

    def _on_symbol_select(self, event):
        sel = self.symbol_listbox.curselection()
        if not sel:
            return
        item = self.symbol_listbox.get(sel[0])
        code = item.split()[0]
        self._select_symbol(code, switch_tab=True)

    def _select_symbol(self, code: str, switch_tab: bool = False):
        """銘柄を選択してチャートを表示（デフォルト3ヶ月）"""
        self.current_symbol = code
        self._signal_cache = {}
        self._update_chart()
        # デフォルト表示期間: 3ヶ月
        if not self.current_df.empty:
            end = self.current_df.index[-1]
            start = end - pd.DateOffset(months=3)
            self.date_start_var.set(start.strftime("%Y-%m-%d"))
            self.date_end_var.set(end.strftime("%Y-%m-%d"))
            self._redraw_with_range()
        if switch_tab:
            self.left_nb.select(0)

    # ──────────────────────────────────────────────────────────────────────
    # タイムフレーム / MA パラメータ
    # ──────────────────────────────────────────────────────────────────────
    def _on_timeframe_change(self):
        self.current_timeframe = self.tf_var.get()
        self._signal_cache = {}
        self._update_chart()

    def _apply_ma_params(self):
        for (tf, pname), var in self.ma_spinboxes.items():
            self.ma_params[tf][pname] = var.get()
        self._signal_cache = {}
        self._update_chart()

    # ──────────────────────────────────────────────────────────────────────
    # チャート更新
    # ──────────────────────────────────────────────────────────────────────
    def _update_chart(self):
        if not self.current_symbol:
            return

        code = self.current_symbol
        tf = self.current_timeframe
        params = self.ma_params.get(tf, self.ma_params["daily"])

        df = get_daily(self.conn, code)
        if df.empty:
            self.info_label.config(text=f"{code}  データなし")
            self._clear_chart()
            return

        if tf == "weekly":
            df = resample_weekly(df)
        elif tf == "monthly":
            df = resample_monthly(df)

        if df.empty:
            self.info_label.config(text=f"{code}  データ不足")
            self._clear_chart()
            return

        df = add_sma_columns(df, tf, params)
        self.current_df = df

        sym_row = self.universe_df[self.universe_df["code"] == code]
        name = sym_row["name"].iloc[0] if not sym_row.empty else ""
        tf_labels = {"daily": "日足", "weekly": "週足", "monthly": "月足"}
        self.info_label.config(text=f"{code}  {name}  [{tf_labels.get(tf, tf)}]")

        view_df = self._get_view_df()
        if view_df.empty:
            view_df = df
        self.current_view_df = view_df

        self._draw(view_df, params)
        self._update_signals(view_df, tf, params)

    def _clear_chart(self):
        for ax in self.axes:
            ax.clear()
        self.canvas.draw()

    def _draw(self, df: pd.DataFrame, params: Dict):
        """ローソク足 + SMA + 出来高 + 価格帯別出来高（オーバーレイ）を描画"""
        s = self.font_scale
        ax_price, ax_vol = self.axes

        for ax in self.axes:
            ax.clear()
            ax.set_facecolor("#1e1e2e")
            for spine in ax.spines.values():
                spine.set_color("#45475a")

        self._crosshair_lines = []

        if len(df) == 0:
            self.canvas.draw()
            return

        dates = df.index
        x = np.arange(len(df))
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        volumes = df["volume"].values

        # --- ローソク足（vlines + バーで高速描画） ---
        width = max(0.3, min(0.7, 50 / max(len(df), 1)))
        up = closes >= opens
        down = ~up

        # ヒゲ（高値-安値の縦線）
        ax_price.vlines(x[up], lows[up], highs[up],
                        color="#e74c3c", linewidth=0.8)
        ax_price.vlines(x[down], lows[down], highs[down],
                        color="#3498db", linewidth=0.8)
        # 実体（始値-終値のバー）
        ax_price.bar(x[up], (closes - opens)[up], width,
                     bottom=opens[up], color="#e74c3c",
                     edgecolor="none", linewidth=0)
        ax_price.bar(x[down], (opens - closes)[down], width,
                     bottom=closes[down], color="#3498db",
                     edgecolor="none", linewidth=0)

        # --- SMA ---
        if "SMA_short" in df.columns:
            ax_price.plot(x, df["SMA_short"], color="#f9e2af", linewidth=1.2,
                         label=f"SMA{params['short']}", alpha=0.9)
        if "SMA_medium" in df.columns:
            ax_price.plot(x, df["SMA_medium"], color="#a6e3a1", linewidth=1.2,
                         label=f"SMA{params['medium']}", alpha=0.9)
        if "SMA_long" in df.columns:
            ax_price.plot(x, df["SMA_long"], color="#89b4fa", linewidth=1.2,
                         label=f"SMA{params['long']}", alpha=0.9)

        ax_price.legend(loc="upper left", fontsize=_fs(9, s), framealpha=0.3,
                       facecolor="#313244", edgecolor="#45475a", labelcolor="#cdd6f4")

        # --- 価格帯別出来高（オーバーレイ、ビン数削減）---
        bin_edges, bin_centers, vol_at_price = compute_volume_profile(df, n_bins=30)
        if len(bin_centers) > 0:
            max_vol = vol_at_price.max() if vol_at_price.max() > 0 else 1
            normalized = vol_at_price / max_vol * len(df) * 0.15
            bar_height = (bin_edges[1] - bin_edges[0]) * 0.8 if len(bin_edges) > 1 else 1
            ax_price.barh(bin_centers, normalized, height=bar_height,
                         left=0, color="#74c7ec", alpha=0.25, zorder=0)

        # --- 両サイド価格 + 点線罫線 ---
        ax_price.yaxis.set_ticks_position("both")
        ax_price.tick_params(axis="y", which="both", colors="#cdd6f4",
                            labelsize=_fs(9, s),
                            left=True, right=True, labelleft=True, labelright=True)
        ax_price.grid(axis="y", alpha=0.2, color="#585b70",
                      linestyle=":", linewidth=0.5)
        ax_price.grid(axis="x", alpha=0.08, color="#45475a",
                      linestyle="-", linewidth=0.3)

        # --- 出来高 ---
        ax_vol.bar(x, volumes, width, color="#7f849c", alpha=0.5)
        ax_vol.yaxis.set_ticks_position("both")
        ax_vol.tick_params(axis="y", which="both", colors="#cdd6f4",
                          labelsize=_fs(8, s),
                          left=True, right=True, labelleft=True, labelright=True)
        ax_vol.grid(axis="y", alpha=0.15, color="#585b70",
                    linestyle=":", linewidth=0.5)

        ax_vol.yaxis.set_major_formatter(
            mticker.FuncFormatter(
                lambda v, _: f"{v/1e6:.0f}M" if v >= 1e6
                else f"{v/1e3:.0f}K" if v >= 1e3 else f"{v:.0f}"
            )
        )

        # --- X 軸ラベル（日付表示）---
        if len(dates) > 0:
            n = len(dates)
            n_labels = min(15, max(8, n // 20))
            step = max(1, n // n_labels)
            tick_positions = list(range(0, n, step))
            if (n - 1) not in tick_positions:
                tick_positions.append(n - 1)
            tick_labels = [dates[i].strftime("%Y/%m/%d") for i in tick_positions]

            ax_vol.set_xticks(tick_positions)
            ax_vol.set_xticklabels(tick_labels, rotation=45, ha="right",
                                   fontsize=_fs(8, s), color="#a6adc8")
            ax_price.set_xticks(tick_positions)
            ax_price.set_xticklabels([])

        self.canvas.draw_idle()

    # ──────────────────────────────────────────────────────────────────────
    # シグナル更新（バックグラウンド + キャッシュ）
    # ──────────────────────────────────────────────────────────────────────
    def _update_signals(self, df: pd.DataFrame, timeframe: str, params: Dict):
        self.signal_text.config(state=tk.NORMAL)
        self.signal_text.delete("1.0", tk.END)
        self.signal_text.insert(tk.END, "⏳ シグナル計算中...\n", "header")
        self.signal_text.config(state=tk.DISABLED)

        def compute():
            try:
                cache_key = (f"{self.current_symbol}_{timeframe}_"
                             f"{hash(frozenset(params.items()))}")
                if cache_key in self._signal_cache:
                    all_ma, all_candle, perf_stats = self._signal_cache[cache_key]
                else:
                    full_df = self.current_df
                    all_ma = detect_ma_signals(full_df, timeframe, params)
                    all_candle = detect_all_patterns(full_df, timeframe)
                    all_full = all_ma + all_candle
                    perf_stats = analyze_signal_performance(full_df, all_full)
                    self._signal_cache[cache_key] = (all_ma, all_candle, perf_stats)

                if not df.empty:
                    cs, ce = df.index[0], df.index[-1]
                    view_ma = [x for x in all_ma if cs <= x["date"] <= ce]
                    view_candle = [x for x in all_candle if cs <= x["date"] <= ce]
                else:
                    view_ma, view_candle = [], []

                lookback_date = df.index[-20] if len(df) >= 20 else df.index[0]
                recent = [x for x in (view_ma + view_candle)
                          if x["date"] >= lookback_date]
                all_signals = sorted(recent, key=lambda x: x["date"],
                                     reverse=True)

                self.root.after(
                    0, lambda: self._render_signals(all_signals, perf_stats))

            except Exception as e:
                logger.error(f"シグナル計算エラー: {e}")
                self.root.after(0, lambda: self._render_signal_error(str(e)))

        threading.Thread(target=compute, daemon=True).start()

    def _render_signals(self, all_signals, perf_stats):
        s = self.font_scale
        self.signal_text.config(state=tk.NORMAL)
        self.signal_text.delete("1.0", tk.END)

        if not all_signals:
            self.signal_text.insert(tk.END, "直近のシグナルはありません\n", "header")
        else:
            bullish = [x for x in all_signals if x["type"] == "bullish"]
            bearish = [x for x in all_signals if x["type"] == "bearish"]

            if bullish:
                self.signal_text.insert(
                    tk.END,
                    f"🟢 良いシグナル（買い示唆）{len(bullish)}件\n", "header")
                self.signal_text.insert(tk.END, "─" * 32 + "\n")
                for sig in bullish:
                    self._insert_signal_row(sig, perf_stats)

            if bearish:
                self.signal_text.insert(
                    tk.END,
                    f"\n🔴 悪いシグナル（売り示唆）{len(bearish)}件\n", "header")
                self.signal_text.insert(tk.END, "─" * 32 + "\n")
                for sig in bearish:
                    self._insert_signal_row(sig, perf_stats)

        self.signal_text.config(state=tk.DISABLED)

    def _insert_signal_row(self, sig, perf_stats):
        date_str = (sig["date"].strftime("%m/%d")
                    if hasattr(sig["date"], "strftime") else str(sig["date"]))
        tag = "bullish" if sig["type"] == "bullish" else "bearish"
        self.signal_text.insert(tk.END, f"  [{date_str}] ", "date_tag")
        self.signal_text.insert(tk.END, f"{sig['name']}\n", tag)
        self.signal_text.insert(tk.END, f"    {sig['detail']}\n")
        if sig["name"] in perf_stats:
            pt = format_performance_text(perf_stats[sig["name"]])
            if pt:
                self.signal_text.insert(tk.END, f"{pt}\n", "perf")
        self.signal_text.insert(tk.END, "\n")

    def _render_signal_error(self, error_msg):
        self.signal_text.config(state=tk.NORMAL)
        self.signal_text.delete("1.0", tk.END)
        self.signal_text.insert(
            tk.END, f"シグナル計算エラー:\n{error_msg}\n", "bearish")
        self.signal_text.config(state=tk.DISABLED)

    # ──────────────────────────────────────────────────────────────────────
    # 本日のシグナル スキャン
    # ──────────────────────────────────────────────────────────────────────
    def _on_scan_today(self):
        """全銘柄をスキャンして本日のシグナルがある銘柄をピックアップ"""
        self.scan_btn.config(state=tk.DISABLED)
        self.today_text.config(state=tk.NORMAL)
        self.today_text.delete("1.0", tk.END)
        self.today_text.insert(tk.END, "⏳ 全銘柄スキャン中...\n", "header")
        self.today_text.config(state=tk.DISABLED)
        self.scan_progress_var.set(0)

        threading.Thread(target=self._run_scan_today, daemon=True).start()

    def _run_scan_today(self):
        """バックグラウンドで全銘柄をスキャンし本日のシグナルを検出（複数時間軸対応）"""
        try:
            # 出来高フィルタ値を取得
            try:
                vol_min = int(self.scan_vol_var.get().replace(",", ""))
            except (ValueError, AttributeError):
                vol_min = 0

            # スキャン対象の時間軸
            scan_weekly = self.scan_weekly_var.get()
            scan_monthly = self.scan_monthly_var.get()

            bg_conn = init_db()
            codes = self.universe_df["code"].tolist()
            names_map = dict(zip(
                self.universe_df["code"], self.universe_df["name"]))
            total = len(codes)

            # 時間軸ごとの結果を格納: {"daily": {"bullish": [], "bearish": []}, ...}
            tf_labels = {"daily": "日足", "weekly": "週足", "monthly": "月足"}
            results = {}
            for tf_key in ["daily", "weekly", "monthly"]:
                results[tf_key] = {"bullish": [], "bearish": []}
            scanned = 0

            for i, code in enumerate(codes):
                # 進捗更新（10銘柄ごと）
                if i % 10 == 0:
                    pct = (i / total) * 100
                    msg = f"{i}/{total} スキャン中... ({code})"
                    self.root.after(
                        0, lambda p=pct, m=msg: (
                            self.scan_progress_var.set(p),
                        ))

                try:
                    df = get_daily(bg_conn, code)
                    if df.empty or len(df) < 10:
                        continue

                    # 出来高フィルタ: 最終日の出来高が閾値未満ならスキップ
                    if vol_min > 0 and df["volume"].iloc[-1] < vol_min:
                        continue

                    name = names_map.get(code, "")
                    scanned += 1

                    # --- 日足シグナル ---
                    df_d = df.tail(80).copy()
                    df_d = add_sma_columns(df_d, "daily")
                    last_d = df_d.index[-1]
                    sigs_d = detect_ma_signals(df_d, "daily") + detect_all_patterns(df_d, "daily")
                    for sig in sigs_d:
                        if sig["date"] == last_d:
                            entry = {"code": code, "name": name,
                                     "signal": sig["name"], "type": sig["type"],
                                     "detail": sig["detail"]}
                            results["daily"][sig["type"]].append(entry)

                    # --- 週足シグナル ---
                    if scan_weekly and len(df) >= 20:
                        df_w = resample_weekly(df)
                        if not df_w.empty and len(df_w) >= 10:
                            df_w = df_w.tail(80).copy()
                            df_w = add_sma_columns(df_w, "weekly")
                            last_w = df_w.index[-1]
                            sigs_w = detect_ma_signals(df_w, "weekly") + detect_all_patterns(df_w, "weekly")
                            for sig in sigs_w:
                                if sig["date"] == last_w:
                                    entry = {"code": code, "name": name,
                                             "signal": sig["name"], "type": sig["type"],
                                             "detail": sig["detail"]}
                                    results["weekly"][sig["type"]].append(entry)

                    # --- 月足シグナル ---
                    if scan_monthly and len(df) >= 60:
                        df_m = resample_monthly(df)
                        if not df_m.empty and len(df_m) >= 10:
                            df_m = df_m.tail(80).copy()
                            df_m = add_sma_columns(df_m, "monthly")
                            last_m = df_m.index[-1]
                            sigs_m = detect_ma_signals(df_m, "monthly") + detect_all_patterns(df_m, "monthly")
                            for sig in sigs_m:
                                if sig["date"] == last_m:
                                    entry = {"code": code, "name": name,
                                             "signal": sig["name"], "type": sig["type"],
                                             "detail": sig["detail"]}
                                    results["monthly"][sig["type"]].append(entry)

                except Exception as e:
                    logger.debug(f"スキャンスキップ: {code} → {e}")
                    continue

            bg_conn.close()

            # 合計数
            total_sigs = sum(
                len(results[tf]["bullish"]) + len(results[tf]["bearish"])
                for tf in results)
            logger.info(
                f"シグナルスキャン完了: {scanned}/{total}銘柄, 合計{total_sigs}件")

            self.root.after(0, lambda: self.scan_progress_var.set(100))
            self.root.after(
                0, lambda r=results: self._render_today_results(r))

        except Exception as e:
            logger.error(f"本日シグナルスキャンエラー: {e}")
            self.root.after(
                0, lambda: self._render_today_error(str(e)))

    def _render_today_results(self, results: dict):
        """スキャン結果を「本日のシグナル」タブに時間軸別に表示"""
        s = self.font_scale
        self.scan_btn.config(state=tk.NORMAL)
        self.today_text.config(state=tk.NORMAL)
        self.today_text.delete("1.0", tk.END)
        self._today_link_map = {}

        tf_labels = {"daily": "日足", "weekly": "週足", "monthly": "月足"}
        tf_icons = {"daily": "📅", "weekly": "📆", "monthly": "🗓️"}

        # 全体集計
        grand_bullish = sum(len(results[tf]["bullish"]) for tf in results)
        grand_bearish = sum(len(results[tf]["bearish"]) for tf in results)
        grand_total = grand_bullish + grand_bearish

        self.today_text.insert(
            tk.END,
            f"📊 シグナル合計: {grand_total}件\n"
            f"（🟢 {grand_bullish} 買い / "
            f"🔴 {grand_bearish} 売り）\n",
            "header",
        )

        link_global_idx = 0

        for tf_key in ["daily", "weekly", "monthly"]:
            bullish = results[tf_key]["bullish"]
            bearish = results[tf_key]["bearish"]
            tf_total = len(bullish) + len(bearish)
            if tf_total == 0:
                continue

            label = tf_labels[tf_key]
            icon = tf_icons[tf_key]

            self.today_text.insert(
                tk.END,
                f"\n{'━' * 30}\n"
                f"{icon} 【{label}】 {tf_total}件"
                f"（🟢{len(bullish)} / 🔴{len(bearish)}）\n"
                f"{'━' * 30}\n\n",
                "header",
            )

            if bullish:
                self.today_text.insert(tk.END, "🟢 良いシグナル\n", "header")
                self.today_text.insert(tk.END, "─" * 28 + "\n")
                grouped = {}
                for r in bullish:
                    key = r["code"]
                    if key not in grouped:
                        grouped[key] = {"name": r["name"], "signals": []}
                    grouped[key]["signals"].append(r)

                for code, info in grouped.items():
                    tag_name = f"link_{link_global_idx}"
                    self._today_link_map[tag_name] = code
                    self.today_text.tag_configure(
                        tag_name, foreground="#89dceb",
                        font=("", _fs(10, s), "underline"),
                    )
                    self.today_text.tag_bind(
                        tag_name, "<Button-1>",
                        lambda e, c=code: self._select_symbol(c),
                    )
                    self.today_text.insert(
                        tk.END, f"  {code} {info['name']}\n", tag_name)
                    for sig in info["signals"]:
                        self.today_text.insert(
                            tk.END, f"    ▸ {sig['signal']}\n", "bullish")
                    self.today_text.insert(tk.END, "\n")
                    link_global_idx += 1

            if bearish:
                self.today_text.insert(tk.END, "🔴 悪いシグナル\n", "header")
                self.today_text.insert(tk.END, "─" * 28 + "\n")
                grouped = {}
                for r in bearish:
                    key = r["code"]
                    if key not in grouped:
                        grouped[key] = {"name": r["name"], "signals": []}
                    grouped[key]["signals"].append(r)

                for code, info in grouped.items():
                    tag_name = f"link_{link_global_idx}"
                    self._today_link_map[tag_name] = code
                    self.today_text.tag_configure(
                        tag_name, foreground="#89dceb",
                        font=("", _fs(10, s), "underline"),
                    )
                    self.today_text.tag_bind(
                        tag_name, "<Button-1>",
                        lambda e, c=code: self._select_symbol(c),
                    )
                    self.today_text.insert(
                        tk.END, f"  {code} {info['name']}\n", tag_name)
                    for sig in info["signals"]:
                        self.today_text.insert(
                            tk.END, f"    ▸ {sig['signal']}\n", "bearish")
                    self.today_text.insert(tk.END, "\n")
                    link_global_idx += 1

        if grand_total == 0:
            self.today_text.insert(
                tk.END, "本日のシグナルはありません\n", "header")

        self.today_text.config(state=tk.DISABLED)

    def _render_today_error(self, error_msg):
        self.scan_btn.config(state=tk.NORMAL)
        self.today_text.config(state=tk.NORMAL)
        self.today_text.delete("1.0", tk.END)
        self.today_text.insert(
            tk.END, f"スキャンエラー:\n{error_msg}\n", "bearish")
        self.today_text.config(state=tk.DISABLED)

    def _on_today_click(self, event):
        """「本日のシグナル」タブの銘柄リンクをクリック"""
        pass  # 個別タグで直接 _select_symbol にバインド済み

    # ──────────────────────────────────────────────────────────────────────
    # チャート画像保存
    # ──────────────────────────────────────────────────────────────────────
    def _save_chart(self):
        if self.current_view_df.empty:
            messagebox.showinfo("保存", "チャートが表示されていません")
            return

        # 保存オプションダイアログ
        save_win = tk.Toplevel(self.root)
        save_win.title("画像保存オプション")
        save_win.geometry("500x300")
        save_win.resizable(False, False)
        save_win.transient(self.root)
        save_win.grab_set()

        ttk.Label(save_win, text="📷 画像保存オプション",
                  font=("", 12, "bold")).pack(pady=(10, 6))

        include_ohlcv = tk.BooleanVar(value=True)
        include_signals = tk.BooleanVar(value=True)

        ttk.Checkbutton(save_win, text="OHLCVデータを含める（選択日の情報）",
                        variable=include_ohlcv).pack(anchor="w", padx=20, pady=2)
        ttk.Checkbutton(save_win, text="シグナル情報を含める",
                        variable=include_signals).pack(anchor="w", padx=20, pady=2)

        # 日付選択
        date_frame = ttk.Frame(save_win)
        date_frame.pack(fill=tk.X, padx=20, pady=6)
        ttk.Label(date_frame, text="対象日:").pack(side=tk.LEFT)
        last_date = self.current_view_df.index[-1].strftime("%Y-%m-%d")
        save_date_var = tk.StringVar(value=last_date)
        ttk.Entry(date_frame, textvariable=save_date_var,
                  width=14).pack(side=tk.LEFT, padx=4)

        def do_save():
            save_win.destroy()
            save_dir = os.path.join(BASE_DIR, "charts")
            os.makedirs(save_dir, exist_ok=True)
            default_name = f"{self.current_symbol}_{self.current_timeframe}.png"
            filepath = filedialog.asksaveasfilename(
                initialdir=save_dir, initialfile=default_name,
                defaultextension=".png",
                filetypes=[("PNG 画像", "*.png")],
            )
            if not filepath:
                return

            # テキストオーバーレイを追加
            texts_added = []
            df = self.current_view_df

            if include_ohlcv.get():
                target_date = save_date_var.get().strip()
                try:
                    ts = pd.Timestamp(target_date)
                    if ts in df.index:
                        row = df.loc[ts]
                    else:
                        row = df.iloc[-1]
                        target_date = df.index[-1].strftime("%Y-%m-%d")
                except Exception:
                    row = df.iloc[-1]
                    target_date = df.index[-1].strftime("%Y-%m-%d")

                ohlcv_str = (
                    f"{target_date}  "
                    f"始:{row['open']:,.0f}  "
                    f"高:{row['high']:,.0f}  "
                    f"安:{row['low']:,.0f}  "
                    f"終:{row['close']:,.0f}  "
                    f"出来高:{row['volume']:,.0f}"
                )
                t = self.fig.text(
                    0.5, 0.005, ohlcv_str,
                    ha="center", va="bottom",
                    fontsize=9, color="#cdd6f4",
                    fontfamily="monospace",
                    bbox=dict(boxstyle="round,pad=0.3",
                              facecolor="#313244", alpha=0.8,
                              edgecolor="#45475a"),
                )
                texts_added.append(t)

            if include_signals.get():
                # キャッシュから直近シグナルを5件取得
                sig_lines = []
                cache_key = None
                for k, v in self._signal_cache.items():
                    cache_key = k
                    break
                if cache_key and cache_key in self._signal_cache:
                    all_ma, all_candle, _ = self._signal_cache[cache_key]
                    all_sigs = sorted(
                        all_ma + all_candle,
                        key=lambda s: s["date"], reverse=True)
                    for sig in all_sigs[:5]:
                        icon = "🟢" if sig["type"] == "bullish" else "🔴"
                        d = sig["date"].strftime("%m/%d")
                        sig_lines.append(f"{icon} [{d}] {sig['name']}")

                if sig_lines:
                    sig_str = "\n".join(sig_lines)
                    t = self.fig.text(
                        0.98, 0.98, sig_str,
                        ha="right", va="top",
                        fontsize=8, color="#cdd6f4",
                        fontfamily="sans-serif",
                        bbox=dict(boxstyle="round,pad=0.4",
                                  facecolor="#313244", alpha=0.85,
                                  edgecolor="#45475a"),
                    )
                    texts_added.append(t)

            self.fig.savefig(filepath, dpi=150,
                             facecolor=self.fig.get_facecolor())

            # 追加テキストを除去（画面には残さない）
            for t in texts_added:
                t.remove()
            self.canvas.draw_idle()

            messagebox.showinfo("保存", f"保存しました:\n{filepath}")

        ttk.Button(save_win, text="💾 保存", command=do_save).pack(pady=10)

    # ──────────────────────────────────────────────────────────────────────
    # 本日データ取得（API経由）
    # ──────────────────────────────────────────────────────────────────────
    def _on_fetch_daily(self):
        """本日の板データを API 経由で取得"""
        ok = messagebox.askyesno(
            "本日データ取得",
            "kabuStation API から全銘柄の\n"
            "本日の板情報を取得します。\n\n"
            "kabuStationが起動している必要があります。\n"
            "続行しますか？",
        )
        if not ok:
            return

        self.daily_progress_win = tk.Toplevel(self.root)
        self.daily_progress_win.title("本日データ取得中...")
        self.daily_progress_win.geometry("420x150")
        self.daily_progress_win.resizable(False, False)
        self.daily_progress_win.transient(self.root)
        self.daily_progress_win.grab_set()

        ttk.Label(
            self.daily_progress_win, text="📡 本日データを取得中...",
            font=("", _fs(12, self.font_scale), "bold"),
        ).pack(pady=(12, 6))

        self.daily_progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(
            self.daily_progress_win, variable=self.daily_progress_var,
            maximum=100, length=360, mode="determinate",
        ).pack(padx=20, pady=4)

        self.daily_progress_label = ttk.Label(
            self.daily_progress_win, text="APIトークン取得中...")
        self.daily_progress_label.pack(pady=4)

        self.daily_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._run_fetch_daily, daemon=True).start()

    def _run_fetch_daily(self):
        """バックグラウンドで API 日次データ取得を実行"""
        try:
            token = kabus_get_token()
            self.root.after(
                0, lambda: self.daily_progress_label.config(
                    text="データ取得中..."))

            bg_conn = init_db()
            symbols = [{"code": row["code"]}
                       for _, row in self.universe_df.iterrows()]

            def on_progress(current, total, symbol):
                pct = (current / total) * 100
                self.root.after(0, lambda: self.daily_progress_var.set(pct))
                if current % 50 == 0 or current == total:
                    msg = f"{current}/{total} ({symbol})"
                    self.root.after(
                        0, lambda m=msg: self.daily_progress_label.config(
                            text=m))

            result = run_daily_update(
                bg_conn, token, symbols, progress_callback=on_progress)
            bg_conn.close()

            def on_done():
                self.daily_progress_win.destroy()
                self.daily_btn.config(state=tk.NORMAL)
                messagebox.showinfo(
                    "完了",
                    f"本日データ取得が完了しました。\n\n"
                    f"  対象: {result['total']} 銘柄\n"
                    f"  成功: {result['success']}\n"
                    f"  スキップ: {result['skipped']}\n"
                    f"  失敗: {result['failed']}\n"
                    f"  対象日: {result['target_date']}",
                )
                if self.current_symbol:
                    self._update_chart()

            self.root.after(0, on_done)

        except Exception as e:
            logger.error(f"本日データ取得エラー: {e}")

            def on_error():
                self.daily_progress_win.destroy()
                self.daily_btn.config(state=tk.NORMAL)
                messagebox.showerror(
                    "エラー",
                    f"本日データ取得に失敗しました:\n{e}\n\n"
                    "kabuStationが起動しているか確認してください。",
                )

            self.root.after(0, on_error)

    # ──────────────────────────────────────────────────────────────────────
    # 過去データ取得
    # ──────────────────────────────────────────────────────────────────────
    def _on_fetch_history(self):
        ok = messagebox.askyesno(
            "過去データ取得",
            "全銘柄の過去2年分の日足データを\n"
            "Yahoo Finance から取得します。\n\n"
            "全銘柄の取得には数十分かかります。\n"
            "続行しますか？",
        )
        if not ok:
            return

        self.progress_win = tk.Toplevel(self.root)
        self.progress_win.title("過去データ取得中...")
        self.progress_win.geometry("420x150")
        self.progress_win.resizable(False, False)
        self.progress_win.transient(self.root)
        self.progress_win.grab_set()

        ttk.Label(
            self.progress_win, text="📥 過去データを取得中...",
            font=("", _fs(12, self.font_scale), "bold"),
        ).pack(pady=(12, 6))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self.progress_win, variable=self.progress_var,
            maximum=100, length=360, mode="determinate",
        )
        self.progress_bar.pack(padx=20, pady=4)

        self.progress_label = ttk.Label(self.progress_win, text="準備中...")
        self.progress_label.pack(pady=4)

        self.fetch_btn.config(state=tk.DISABLED)

        threading.Thread(target=self._run_fetch_history, daemon=True).start()

    def _run_fetch_history(self):
        try:
            bg_conn = init_db()
            symbols = [{"code": row["code"]}
                       for _, row in self.universe_df.iterrows()]

            def on_progress(batch_idx, total_batches, msg):
                pct = (batch_idx / total_batches) * 100
                self.root.after(0, lambda: self.progress_var.set(pct))
                self.root.after(
                    0, lambda m=msg: self.progress_label.config(text=m))

            result = fetch_history_batch(
                symbols, bg_conn, years=2, progress_cb=on_progress)
            bg_conn.close()

            def on_done():
                self.progress_win.destroy()
                self.fetch_btn.config(state=tk.NORMAL)
                messagebox.showinfo(
                    "完了",
                    f"過去データ取得が完了しました。\n\n"
                    f"  対象: {result['total']} 銘柄\n"
                    f"  成功: {result['success']}\n"
                    f"  スキップ: {result['skipped']}\n"
                    f"  失敗: {result['failed']}\n"
                    f"  期間: {result['period']}",
                )

            self.root.after(0, on_done)

        except Exception as e:
            logger.error(f"過去データ取得エラー: {e}")

            def on_error():
                self.progress_win.destroy()
                self.fetch_btn.config(state=tk.NORMAL)
                messagebox.showerror(
                    "エラー", f"過去データ取得に失敗しました:\n{e}")

            self.root.after(0, on_error)


# ══════════════════════════════════════════════════════════════════════════════
# GUI 起動
# ══════════════════════════════════════════════════════════════════════════════
def launch_gui(conn: sqlite3.Connection):
    """GUI を起動する"""
    root = tk.Tk()
    app = TechnicalAnalysisApp(root, conn)
    root.mainloop()
