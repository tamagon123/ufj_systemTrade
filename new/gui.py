# -*- coding: utf-8 -*-
"""
gui.py — テクニカル分析 GUI
=============================
tkinter + matplotlib を統合したデスクトップアプリケーション。
- 左ペイン: 銘柄リスト（検索・フィルタ）
- 中央:    ローソク足チャート + 3 SMA + 出来高 + 価格帯別出来高
- 右ペイン: シグナル一覧（良い=🟢 / 悪い=🔴）
- 下部:    タイムフレーム切替・MA パラメータ設定
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import logging
import threading
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.patches import FancyBboxPatch
import matplotlib.dates as mdates

from config import MA_PARAMS, DB_PATH, BASE_DIR
from database import init_db, get_daily, get_universe, load_universe_csv
from signals import add_sma_columns, detect_ma_signals, get_latest_signals
from candlestick import detect_all_patterns
from timeframes import resample_weekly, resample_monthly
from volume_profile import compute_volume_profile, find_support_resistance
from history_fetcher import fetch_history_batch
from signal_performance import analyze_signal_performance, format_performance_text

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# ローソク足チャート描画
# ══════════════════════════════════════════════════════════════════════════════
def _draw_candlestick(ax, df):
    """ローソク足を ax に描画する（matplotlib ネイティブ）"""
    width = 0.6
    width2 = 0.1

    up = df[df["close"] >= df["open"]]
    down = df[df["close"] < df["open"]]

    # 陽線 — 赤
    ax.bar(up.index, up["close"] - up["open"], width, bottom=up["open"],
           color="#e74c3c", edgecolor="#c0392b", linewidth=0.5)
    ax.bar(up.index, up["high"] - up["close"], width2, bottom=up["close"],
           color="#e74c3c", linewidth=0)
    ax.bar(up.index, up["open"] - up["low"], width2, bottom=up["low"],
           color="#e74c3c", linewidth=0)

    # 陰線 — 青
    ax.bar(down.index, down["open"] - down["close"], width, bottom=down["close"],
           color="#3498db", edgecolor="#2980b9", linewidth=0.5)
    ax.bar(down.index, down["high"] - down["open"], width2, bottom=down["open"],
           color="#3498db", linewidth=0)
    ax.bar(down.index, down["close"] - down["low"], width2, bottom=down["low"],
           color="#3498db", linewidth=0)


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
        self.current_df = pd.DataFrame()
        self.ma_params = {k: dict(v) for k, v in MA_PARAMS.items()}

        # スタイル
        style = ttk.Style()
        style.theme_use("clam")

        self._build_ui()
        self._load_symbols()

    # ──────────────────────────────────────────────────────────────────────
    # UI 構築
    # ──────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # メインフレーム
        main_pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pw.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ===== 左ペイン：銘柄リスト =====
        left_frame = ttk.Frame(main_pw, width=250)
        main_pw.add(left_frame, weight=0)

        ttk.Label(left_frame, text="🔍 銘柄検索", font=("", 11, "bold")).pack(pady=(4, 2))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        search_entry = ttk.Entry(left_frame, textvariable=self.search_var, width=28)
        search_entry.pack(padx=4, pady=2)

        # フィルタ: 市場
        filter_frame = ttk.Frame(left_frame)
        filter_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(filter_frame, text="市場:").pack(side=tk.LEFT)
        self.market_var = tk.StringVar(value="すべて")
        self.market_combo = ttk.Combobox(
            filter_frame, textvariable=self.market_var,
            values=["すべて"], state="readonly", width=18
        )
        self.market_combo.pack(side=tk.LEFT, padx=2)
        self.market_combo.bind("<<ComboboxSelected>>", self._on_search)

        # 銘柄リスト
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.symbol_listbox = tk.Listbox(
            list_frame, yscrollcommand=scrollbar.set,
            font=("Consolas", 10), selectmode=tk.SINGLE
        )
        self.symbol_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.symbol_listbox.yview)
        self.symbol_listbox.bind("<<ListboxSelect>>", self._on_symbol_select)

        self.symbol_count_label = ttk.Label(left_frame, text="0 銘柄")
        self.symbol_count_label.pack(pady=2)

        # 過去データ取得ボタン
        self.fetch_btn = ttk.Button(
            left_frame, text="📥 過去データ取得",
            command=self._on_fetch_history,
        )
        self.fetch_btn.pack(fill=tk.X, padx=4, pady=(4, 2))

        # ===== 中央ペイン：チャート =====
        center_frame = ttk.Frame(main_pw)
        main_pw.add(center_frame, weight=3)

        # チャート info bar
        info_bar = ttk.Frame(center_frame)
        info_bar.pack(fill=tk.X, padx=4, pady=2)
        self.info_label = ttk.Label(info_bar, text="銘柄を選択してください", font=("", 12, "bold"))
        self.info_label.pack(side=tk.LEFT)

        # タイムフレーム切替
        tf_frame = ttk.Frame(info_bar)
        tf_frame.pack(side=tk.RIGHT)
        self.tf_var = tk.StringVar(value="daily")
        for tf, label in [("daily", "日足"), ("weekly", "週足"), ("monthly", "月足")]:
            ttk.Radiobutton(
                tf_frame, text=label, variable=self.tf_var, value=tf,
                command=self._on_timeframe_change
            ).pack(side=tk.LEFT, padx=4)

        # 画像保存ボタン
        ttk.Button(info_bar, text="📷 保存", command=self._save_chart).pack(side=tk.RIGHT, padx=4)

        # matplotlib Figure
        self.fig, self.axes = plt.subplots(
            3, 1, figsize=(12, 7),
            gridspec_kw={"height_ratios": [4, 1, 0.6]},
            facecolor="#1e1e2e",
        )
        self.fig.subplots_adjust(hspace=0.05, left=0.06, right=0.88, top=0.96, bottom=0.06)
        for ax in self.axes:
            ax.set_facecolor("#1e1e2e")
            ax.tick_params(colors="#cdd6f4", labelsize=8)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            for spine in ax.spines.values():
                spine.set_color("#45475a")

        self.canvas = FigureCanvasTkAgg(self.fig, master=center_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        toolbar_frame = ttk.Frame(center_frame)
        toolbar_frame.pack(fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()

        # ===== 右ペイン：シグナル =====
        right_frame = ttk.Frame(main_pw, width=300)
        main_pw.add(right_frame, weight=0)

        ttk.Label(right_frame, text="📊 シグナル一覧", font=("", 11, "bold")).pack(pady=(4, 2))

        # シグナルスクロールビュー
        signal_container = ttk.Frame(right_frame)
        signal_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        signal_scroll = ttk.Scrollbar(signal_container)
        signal_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.signal_text = tk.Text(
            signal_container, width=35, wrap=tk.WORD,
            font=("", 10), bg="#1e1e2e", fg="#cdd6f4",
            yscrollcommand=signal_scroll.set, state=tk.DISABLED,
            borderwidth=0, highlightthickness=0,
        )
        self.signal_text.pack(fill=tk.BOTH, expand=True)
        signal_scroll.config(command=self.signal_text.yview)

        # タグ設定
        self.signal_text.tag_configure("bullish", foreground="#a6e3a1")
        self.signal_text.tag_configure("bearish", foreground="#f38ba8")
        self.signal_text.tag_configure("header", foreground="#89b4fa", font=("", 10, "bold"))
        self.signal_text.tag_configure("date_tag", foreground="#6c7086")
        self.signal_text.tag_configure("perf", foreground="#7f849c", font=("", 8))

        # ===== 下部バー：MA パラメータ =====
        bottom_frame = ttk.LabelFrame(self.root, text="移動平均線パラメータ")
        bottom_frame.pack(fill=tk.X, padx=4, pady=4)

        self.ma_spinboxes = {}
        for tf, tf_label in [("daily", "日足"), ("weekly", "週足"), ("monthly", "月足")]:
            tf_grp = ttk.Frame(bottom_frame)
            tf_grp.pack(side=tk.LEFT, padx=10, pady=2)
            ttk.Label(tf_grp, text=tf_label, font=("", 9, "bold")).pack(side=tk.LEFT, padx=(0, 4))
            for period_name, period_label in [("short", "短期"), ("medium", "中期"), ("long", "長期")]:
                ttk.Label(tf_grp, text=period_label).pack(side=tk.LEFT)
                var = tk.IntVar(value=self.ma_params[tf][period_name])
                sb = ttk.Spinbox(tf_grp, from_=1, to=999, width=4, textvariable=var)
                sb.pack(side=tk.LEFT, padx=(0, 6))
                self.ma_spinboxes[(tf, period_name)] = var

        ttk.Button(bottom_frame, text="更新", command=self._apply_ma_params).pack(side=tk.RIGHT, padx=10)

    # ──────────────────────────────────────────────────────────────────────
    # 銘柄リスト
    # ──────────────────────────────────────────────────────────────────────
    def _load_symbols(self):
        """universe テーブルからシンボル一覧を読み込む"""
        self.universe_df = get_universe(self.conn)
        if self.universe_df.empty:
            # CSV からロード
            load_universe_csv(self.conn)
            self.universe_df = get_universe(self.conn)

        # 市場フィルタ更新
        markets = sorted(self.universe_df["market"].unique().tolist())
        self.market_combo["values"] = ["すべて"] + markets

        self._refresh_symbol_list()

    def _refresh_symbol_list(self):
        """検索 & フィルタに応じてリストを更新"""
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
        self.current_symbol = code
        self._update_chart()

    # ──────────────────────────────────────────────────────────────────────
    # タイムフレーム / MA パラメータ
    # ──────────────────────────────────────────────────────────────────────
    def _on_timeframe_change(self):
        self.current_timeframe = self.tf_var.get()
        self._update_chart()

    def _apply_ma_params(self):
        """スピンボックスから MA パラメータを更新"""
        for (tf, pname), var in self.ma_spinboxes.items():
            self.ma_params[tf][pname] = var.get()
        self._update_chart()

    # ──────────────────────────────────────────────────────────────────────
    # チャート更新
    # ──────────────────────────────────────────────────────────────────────
    def _update_chart(self):
        """選択銘柄のチャートとシグナルを再描画"""
        if not self.current_symbol:
            return

        code = self.current_symbol
        tf = self.current_timeframe
        params = self.ma_params.get(tf, self.ma_params["daily"])

        # DB からデータ取得
        df = get_daily(self.conn, code)
        if df.empty:
            self.info_label.config(text=f"{code}  データなし")
            self._clear_chart()
            return

        # タイムフレーム変換
        if tf == "weekly":
            df = resample_weekly(df)
        elif tf == "monthly":
            df = resample_monthly(df)

        if df.empty:
            self.info_label.config(text=f"{code}  データ不足")
            self._clear_chart()
            return

        # SMA 追加
        df = add_sma_columns(df, tf, params)
        self.current_df = df

        # 銘柄名取得
        sym_row = self.universe_df[self.universe_df["code"] == code]
        name = sym_row["name"].iloc[0] if not sym_row.empty else ""
        tf_labels = {"daily": "日足", "weekly": "週足", "monthly": "月足"}
        self.info_label.config(text=f"{code}  {name}  [{tf_labels.get(tf, tf)}]")

        # 描画
        self._draw(df, params)
        self._update_signals(df, tf, params)

    def _clear_chart(self):
        for ax in self.axes:
            ax.clear()
        self.canvas.draw()

    def _draw(self, df: pd.DataFrame, params: Dict):
        """ローソク足 + SMA + 出来高 + 価格帯別出来高を描画"""
        ax_price, ax_vol, ax_vp = self.axes

        for ax in self.axes:
            ax.clear()
            ax.set_facecolor("#1e1e2e")

        if len(df) == 0:
            self.canvas.draw()
            return

        # 数値インデックスに変換（日付ラベルは手動で設定）
        dates = df.index
        x = np.arange(len(df))

        # --- ローソク足 ---
        width = 0.6
        width2 = 0.1
        up = df["close"] >= df["open"]
        down = ~up

        # 陽線
        ax_price.bar(x[up], (df["close"] - df["open"])[up], width,
                     bottom=df["open"][up], color="#e74c3c", edgecolor="#c0392b", linewidth=0.5)
        ax_price.bar(x[up], (df["high"] - df["close"])[up], width2,
                     bottom=df["close"][up], color="#e74c3c")
        ax_price.bar(x[up], (df["open"] - df["low"])[up], width2,
                     bottom=df["low"][up], color="#e74c3c")
        # 陰線
        ax_price.bar(x[down], (df["open"] - df["close"])[down], width,
                     bottom=df["close"][down], color="#3498db", edgecolor="#2980b9", linewidth=0.5)
        ax_price.bar(x[down], (df["high"] - df["open"])[down], width2,
                     bottom=df["open"][down], color="#3498db")
        ax_price.bar(x[down], (df["close"] - df["low"])[down], width2,
                     bottom=df["low"][down], color="#3498db")

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

        ax_price.legend(loc="upper left", fontsize=8, framealpha=0.3,
                       facecolor="#313244", edgecolor="#45475a", labelcolor="#cdd6f4")
        ax_price.yaxis.tick_right()
        ax_price.tick_params(axis="y", colors="#cdd6f4", labelsize=8)
        ax_price.grid(True, alpha=0.15, color="#45475a")

        # --- 出来高 ---
        colors = ["#e74c3c" if c else "#3498db" for c in up]
        ax_vol.bar(x, df["volume"], width, color=colors, alpha=0.6)
        ax_vol.yaxis.tick_right()
        ax_vol.tick_params(axis="y", colors="#cdd6f4", labelsize=7)
        ax_vol.grid(True, alpha=0.1, color="#45475a")

        # --- 価格帯別出来高（横棒グラフ） ---
        bin_edges, bin_centers, vol_at_price = compute_volume_profile(df)
        if len(bin_centers) > 0:
            max_vol = vol_at_price.max() if vol_at_price.max() > 0 else 1
            # 正規化して横幅として描画
            normalized = vol_at_price / max_vol
            bar_height = (bin_edges[1] - bin_edges[0]) * 0.8 if len(bin_edges) > 1 else 1
            ax_vp.barh(bin_centers, normalized, height=bar_height,
                       color="#cba6f7", alpha=0.5)
            ax_vp.set_xlim(0, 1.2)
            ax_vp.tick_params(axis="both", colors="#cdd6f4", labelsize=7)
            ax_vp.set_ylabel("価格帯別出来高", color="#cdd6f4", fontsize=7)
        else:
            ax_vp.set_visible(False)

        # X 軸ラベル（共通）
        if len(dates) > 0:
            step = max(1, len(dates) // 10)
            tick_positions = list(range(0, len(dates), step))
            tick_labels = [dates[i].strftime("%Y/%m/%d") for i in tick_positions]
            for ax in [ax_price, ax_vol]:
                ax.set_xticks(tick_positions)
                ax.set_xticklabels(tick_labels, rotation=45, ha="right",
                                   fontsize=7, color="#6c7086")
            ax_price.set_xticklabels([])  # 価格軸ではラベル非表示

        self.canvas.draw()

    # ──────────────────────────────────────────────────────────────────────
    # シグナル更新
    # ──────────────────────────────────────────────────────────────────────
    def _update_signals(self, df: pd.DataFrame, timeframe: str, params: Dict):
        """シグナル一覧テキストを更新（パフォーマンス分析付き）"""
        self.signal_text.config(state=tk.NORMAL)
        self.signal_text.delete("1.0", tk.END)

        # 全シグナル取得（パフォーマンス分析用）
        from signals import detect_ma_signals
        all_ma = detect_ma_signals(df, timeframe, params)
        all_candle = detect_all_patterns(df, timeframe)
        all_full = all_ma + all_candle

        # パフォーマンス分析（全期間のシグナルを使って統計）
        perf_stats = analyze_signal_performance(df, all_full)

        # 直近20日分に絞る
        ma_signals = get_latest_signals(df, timeframe, lookback=20, params=params)
        candle_signals = all_candle
        if candle_signals:
            cutoff = df.index[-20] if len(df) >= 20 else df.index[0]
            candle_signals = [s for s in candle_signals if s["date"] >= cutoff]

        all_signals = sorted(
            ma_signals + candle_signals,
            key=lambda s: s["date"],
            reverse=True,
        )

        if not all_signals:
            self.signal_text.insert(tk.END, "直近のシグナルはありません\n", "header")
        else:
            bullish = [s for s in all_signals if s["type"] == "bullish"]
            bearish = [s for s in all_signals if s["type"] == "bearish"]

            if bullish:
                self.signal_text.insert(tk.END, "🟢 良いシグナル（買い示唆）\n", "header")
                self.signal_text.insert(tk.END, "─" * 30 + "\n")
                for s in bullish:
                    date_str = s["date"].strftime("%m/%d") if hasattr(s["date"], "strftime") else str(s["date"])
                    self.signal_text.insert(tk.END, f"  [{date_str}] ", "date_tag")
                    self.signal_text.insert(tk.END, f"{s['name']}\n", "bullish")
                    self.signal_text.insert(tk.END, f"    {s['detail']}\n")
                    # パフォーマンス統計
                    if s["name"] in perf_stats:
                        perf_text = format_performance_text(perf_stats[s["name"]])
                        if perf_text:
                            self.signal_text.insert(tk.END, f"{perf_text}\n", "perf")
                    self.signal_text.insert(tk.END, "\n")

            if bearish:
                self.signal_text.insert(tk.END, "\n🔴 悪いシグナル（売り示唆）\n", "header")
                self.signal_text.insert(tk.END, "─" * 30 + "\n")
                for s in bearish:
                    date_str = s["date"].strftime("%m/%d") if hasattr(s["date"], "strftime") else str(s["date"])
                    self.signal_text.insert(tk.END, f"  [{date_str}] ", "date_tag")
                    self.signal_text.insert(tk.END, f"{s['name']}\n", "bearish")
                    self.signal_text.insert(tk.END, f"    {s['detail']}\n")
                    if s["name"] in perf_stats:
                        perf_text = format_performance_text(perf_stats[s["name"]])
                        if perf_text:
                            self.signal_text.insert(tk.END, f"{perf_text}\n", "perf")
                    self.signal_text.insert(tk.END, "\n")

        self.signal_text.config(state=tk.DISABLED)

    # ──────────────────────────────────────────────────────────────────────
    # チャート画像保存
    # ──────────────────────────────────────────────────────────────────────
    def _save_chart(self):
        """現在のチャートを PNG として保存"""
        if self.current_df.empty:
            messagebox.showinfo("保存", "チャートが表示されていません")
            return
        save_dir = os.path.join(BASE_DIR, "charts")
        os.makedirs(save_dir, exist_ok=True)
        default_name = f"{self.current_symbol}_{self.current_timeframe}.png"
        filepath = filedialog.asksaveasfilename(
            initialdir=save_dir,
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG 画像", "*.png")],
        )
        if filepath:
            self.fig.savefig(filepath, dpi=150, facecolor=self.fig.get_facecolor())
            messagebox.showinfo("保存", f"保存しました:\n{filepath}")

    # ──────────────────────────────────────────────────────────────────────
    # 過去データ取得
    # ──────────────────────────────────────────────────────────────────────
    def _on_fetch_history(self):
        """過去データ取得ボタン押下ハンドラ"""
        ok = messagebox.askyesno(
            "過去データ取得",
            "全銘柄の過去2年分の日足データを\n"
            "Yahoo Finance から取得します。\n\n"
            "全銘柄の取得には数十分かかります。\n"
            "続行しますか？",
        )
        if not ok:
            return

        # プログレスダイアログ
        self.progress_win = tk.Toplevel(self.root)
        self.progress_win.title("過去データ取得中...")
        self.progress_win.geometry("420x150")
        self.progress_win.resizable(False, False)
        self.progress_win.transient(self.root)
        self.progress_win.grab_set()

        ttk.Label(
            self.progress_win, text="📥 過去データを取得中...",
            font=("", 11, "bold"),
        ).pack(pady=(12, 6))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self.progress_win, variable=self.progress_var,
            maximum=100, length=360, mode="determinate",
        )
        self.progress_bar.pack(padx=20, pady=4)

        self.progress_label = ttk.Label(
            self.progress_win, text="準備中...",
        )
        self.progress_label.pack(pady=4)

        self.fetch_btn.config(state=tk.DISABLED)

        # バックグラウンドスレッドで実行
        t = threading.Thread(target=self._run_fetch_history, daemon=True)
        t.start()

    def _run_fetch_history(self):
        """バックグラウンドで yfinance データ取得を実行"""
        try:
            from database import init_db
            bg_conn = init_db()  # スレッド専用 DB 接続

            symbols = []
            for _, row in self.universe_df.iterrows():
                symbols.append({"code": row["code"]})

            def on_progress(batch_idx, total_batches, msg):
                pct = (batch_idx / total_batches) * 100
                self.root.after(0, lambda: self.progress_var.set(pct))
                self.root.after(
                    0, lambda m=msg: self.progress_label.config(text=m)
                )

            result = fetch_history_batch(
                symbols, bg_conn, years=2, progress_cb=on_progress,
            )
            bg_conn.close()

            # 完了通知（メインスレッドで実行）
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
                messagebox.showerror("エラー", f"過去データ取得に失敗しました:\n{e}")

            self.root.after(0, on_error)


# ══════════════════════════════════════════════════════════════════════════════
# GUI 起動
# ══════════════════════════════════════════════════════════════════════════════
def launch_gui(conn: sqlite3.Connection):
    """GUI を起動する"""
    root = tk.Tk()
    app = TechnicalAnalysisApp(root, conn)
    root.mainloop()
