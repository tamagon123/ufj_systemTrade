# UFJシステム取引仕様書

## 概要
本システムは、KabuStation APIを利用したリアルタイム取引システムであり、TDnet/EDINET開示情報、ニュース、板情報を監視し、HFT（高頻度取引）戦略に基づいて自動取引を実行する。

## システムアーキテクチャ

### 1. 主要コンポーネント
- **メインエンジン** (`main.py`): 取引ロジックと状態管理
- **GUIインターフェース**: 設定変更と監視
- **WebSocket接続**: リアルタイム約定通知
- **API連携**: KabuStation APIとの通信

### 2. データフロー
```
開示情報/ニュース → 監視リスト追加 → 板情報監視 → シグナル検知 → 注文発注 → WebSocket約定通知 → 状態遷移 → リスク管理
```

## 取引状態機械

### 状態定義
```python
class SystemState:
    mode = "MONITORING"    # 監視中
    mode = "ORDERING"      # 注文発注中
    mode = "TRADING"       # 取引中
```

### 状態遷移フロー
1. **MONITORING**: 市場監視、シグナル待機
2. **ORDERING**: 注文発注後、約定待機
3. **TRADING**: 約定確定後、リスク管理実行

## 主要機能

### 1. 情報収集機能

#### TDnet開示監視
- **監視対象**: ポジティブキーワードを含む開示情報
- **キーワード**: "上方修正", "増配", "復配", "株式分割", "自社株", "提携", "M&A", "特別利益", "決算"
- **除外キーワード**: "下方修正", "減配", "無配", "赤字"など
- **ポーリング間隔**: 10秒（ベース）

#### EDINET開示監視
- **対象書類**: 有価証券報告書、四半期報告書など
- **VIP企業フィルタ**: 大手企業の開示を優先
- **APIキー**: 必須設定

#### ニュース監視
- **情報源**: みんかぶ、Yahoo!ファイナンス
- **ボラティリティキーワード**: 急騰・急落関連
- **銘柄名解決**: 略称辞書による自動変換

### 2. 板情報監視機能

#### データ取得
- **API**: `kabus_get_board()`
- **更新間隔**: 場中1秒、場外10秒
- **取得データ**: 現在値、出来高、気配、板情報

#### 技術指標
- **移動平均線**: 短期/長期MA（オプション）
- **VWAP**: 加重平均価格（オプション）
- **出来高EMA**: 指数平滑移動平均
- **OBIシグナル**: 板ブレイクアウト検知

### 3. HFT取引戦略

#### シグナル条件
```python
# 買いシグナル
is_trend_up = True          # 上昇トレンド
is_oversold = False         # 買われ過ぎでない
has_price_action = True     # 価格アクションあり
is_obi_breakout = True     # 板ブレイクアウト
pattern_signal = "OBI_buy" # シグナルパターン
```

#### 注文戦略
- **注文タイプ**: FAK指値注文（FrontOrderType=20, TimeInForce=2）
- **価格決定**: 
  - 買い: Ask価格 + 0.1ティック
  - 売り: Bid価格 - 0.1ティック
- **数量**: 環境変数`ORDER_QTY`で指定

### 4. WebSocket約定通知機能

#### 接続管理
```python
# WebSocket接続開始
start_websocket_connection(token)

# 接続状態管理
websocket_running = True/False
```

#### 約定通知処理
```python
def on_websocket_message(ws, message):
    data = json.loads(message)
    if data.get("MessageType") == 2:  # 約定通知
        order_id = data.get("OrderID")
        symbol = data.get("Symbol")
        price = data.get("Price")
        qty = data.get("Qty")
        
        # 状態遷移: ORDERING → TRADING
        if system_state.mode == "ORDERING" and system_state.pending_order_id == order_id:
            system_state.mode = "TRADING"
            system_state.entry_price = price
            system_state.hard_stop_price = price - 0.5
```

### 5. リスク管理機能

#### ハードストップ
- **設定**: エントリー価格 - 0.5円
- **発動条件**: 現在価格が防衛ラインを下回った場合
- **アクション**: 即時決済

#### トレーリングストップ
- **設定**: 最高値から一定の下落で発動
- **更新**: 最高値の更新に応じて防衛ラインを上昇
- **計算**: `hard_stop_price = max(hard_stop_price, current_price - 0.5)`

#### 自動決済条件
1. **利確目標**: `profit_yen_per_100`で設定
2. **損切ライン**: `stoploss_yen_per_100`で設定
3. **膠着検出**: 価格変動と出来高が一定期間停滞
4. **大引け前**: `AUTO_EXIT_MARKET_CLOSE_HHMM`で強制決済

### 6. ボリンジャーバンド計算

#### 高速化実装（O(1)計算）
```python
class SystemState:
    price_history = deque(maxlen=20)  # 価格履歴
    sum_x = {}                        # 価格の合計
    sum_x2 = {}                       # 価格の二乗合計
    
    def calculate_bollinger_bands(self, symbol):
        n = len(self.price_history[symbol])
        mean = self.sum_x[symbol] / n
        variance = (self.sum_x2[symbol] / n) - (mean ** 2)
        std = math.sqrt(variance)
        upper = mean + 2 * std
        lower = mean - 2 * std
        return upper, mean, lower
```

## 環境変数設定

### API接続
```
KABUS_API_BASE_URL=http://localhost:18080
KABUS_API_PASSWORD=your_password
KABUS_EXCHANGE=1
```

### 注文設定
```
ORDER_MODE=auto
ORDER_SIDE_MODE=buy
ORDER_CASH_MARGIN=cash
ORDER_TYPE=limit_pct
ORDER_LIMIT_PCT=0.1
ORDER_QTY=100
ORDER_DRY_RUN=0
```

### 監視設定
```
WATCH_POLL_SECONDS=1
WATCH_WINDOW_SECONDS=180
WATCH_MAX_SYMBOLS=8
ORDER_MIN_PRICE_PCT=0.3
ORDER_CONSECUTIVE_HITS=2
```

### 自動決済
```
AUTO_EXIT_ENABLE=1
AUTO_EXIT_PROFIT_YEN_PER_100=500
AUTO_EXIT_STOPLOSS_YEN_PER_100=300
AUTO_EXIT_STAGNATION_SECONDS=300
AUTO_EXIT_MARKET_CLOSE_ENABLE=1
AUTO_EXIT_MARKET_CLOSE_HHMM=15:15
```

### メール通知
```
EMAIL_ENABLE=1
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_TO=recipient@example.com
EMAIL_SCHEDULE_TIMES=["09:05","12:05","15:05"]
```

## 実行フロー

### 1. 初期化
```python
def main():
    # ログ設定、環境変数読み込み
    # 各種モニター初期化
    # WebSocket接続開始（トークン取得後）
    # メインループ開始
```

### 2. メインループ
```python
while True:
    # 1. TDnet/EDINET/ニュース監視
    # 2. Watchlist監視
    # 3. トークン取得とWebSocket接続確認
    # 4. 各銘柄の板情報取得
    # 5. シグナル判定と注文発注
    # 6. ポジション管理と自動決済
    # 7. メール通知スケジュール確認
```

### 3. シグナル処理
```python
def process_signal(symbol, current_price, ask_price, bid_price, ...):
    if system_state.mode == "MONITORING":
        # シグナル条件チェック
        # 注文発注（ORDERING状態へ）
    elif system_state.mode == "ORDERING":
        # タイムアウトチェック
        # 注文キャンセル処理
    elif system_state.mode == "TRADING":
        # リスク管理（ハードストップ、トレーリング）
        # 決済条件チェック
```

## エラーハンドリング

### APIエラー
- **401 Unauthorized**: トークン再取得
- **429 Rate Limit**: バックオフ処理
- **ネットワークエラー**: リトライ処理

### WebSocketエラー
- **接続失敗**: 再接続試行
- **メッセージエラー**: ログ記録と継続
- **接続切断**: 自動再接続

### システムエラー
- **予期せぬ例外**: ログ記録とWebSocketクリーンアップ
- **KeyboardInterrupt**: 安全な終了処理

## ログ機能

### ログ種類
1. **TDnetログ**: `tdnet_YYYYMMDD.csv`
2. **監視ログ**: `watch/YYYYMMDD/{symbol}.csv`
3. **注文ログ**: `order_YYYYMMDD.csv`
4. **イベントログ**: `trade_events_YYYYMMDD.csv`
5. **EDINETログ**: `edinet_YYYYMMDD.csv`
6. **ニュースログ**: `news_YYYYMMDD.csv`

### ログ項目例（監視ログ）
```csv
datetime,tdnet_key,symbol,source,status,price,volume,baseline_price,baseline_volume,triggered
```

## セキュリティ考慮事項

### APIキー管理
- 環境変数による設定
- ログ出力時のマスキング
- Git管理外の`.env`ファイル

### 注文安全策
- ドライランモードの実装
- 注文確認ダイアログ
- 取引時間外の発注防止
- 手動監視銘柄のみモード

## パフォーマンス最適化

### ボリンジャーバンド
- O(1)計算による高速化
- dequeによる効率的なデータ管理

### API呼び出し
- レートリミット対応
- バックオフ戦略
- キャッシュ利用

### メモリ管理
- 履歴データの適切なクリア
- dequeによるメモリ制限
- ガベージコレクション考慮

## 拡張性

### 新戦略追加
- シグナル条件の拡張
- 注文タイプの追加
- リスク管理ルールの変更

### 新情報源
- 追加のニュースソース
- SNS情報の統合
- アナリストレポートの活用

### 機能拡張
- 機械学習モデルの統合
- ポートフォリオ管理
- バックテスト機能

## 注意事項

### 取引リスク
- 本システムは自動取引を行うため、損失発生の可能性がある
- 十分なテストとデモ取引による検証が必要
- リスク管理設定の慎重な調整が必須

### システム要件
- Python 3.8+
- KabuStation API接続環境
- 安定したインターネット接続
- 十分なメモリとCPUリソース

### 法規制
- 金融商品取引法の遵守
- 証券会社の取引規約の確認
- 税務申告の責任

---

*本仕様書は2026年2月23日現在のシステム状態を反映しています。*
