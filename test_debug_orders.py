"""返済注文のAPIレスポンスを確認するデバッグスクリプト"""
import sys, os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from main import _load_dotenv, kabus_get_token, kabus_get_orders, JST
import datetime

token = kabus_get_token()
print(f"Token: {token[:8]}...")

st, orders = kabus_get_orders(token, product=0, state="5")
print(f"Orders API status: {st}, count: {len(orders) if isinstance(orders, list) else 'N/A'}")

today_str = datetime.datetime.now(JST).strftime("%Y%m%d")

for order in (orders if isinstance(orders, list) else []):
    if not isinstance(order, dict):
        continue
    recv_time = str(order.get("RecvTime") or "")
    if recv_time and not recv_time.startswith(f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:8]}"):
        continue
    cum_qty = order.get("CumQty") or 0
    if not isinstance(cum_qty, (int, float)) or cum_qty <= 0:
        continue
    
    cash_margin = order.get("CashMargin")
    symbol = order.get("Symbol", "")
    side = order.get("Side")
    price = order.get("Price", 0)
    
    # 返済注文のみ詳細表示
    if cash_margin in (3, "3"):
        print(f"\n=== 返済注文: {symbol} ===")
        print(f"  Side: {side}, CashMargin: {cash_margin}, Price: {price}, CumQty: {cum_qty}")
        print(f"  RecvTime: {recv_time}")
        
        # ClosePositionsキーの確認
        cp = order.get("ClosePositions")
        print(f"  ClosePositions: {cp}")
        
        # Details確認
        details = order.get("Details")
        if isinstance(details, list):
            for i, d in enumerate(details):
                print(f"  Detail[{i}]: RecType={d.get('RecType')}, Price={d.get('Price')}, Qty={d.get('Qty')}, TransactTime={d.get('TransactTime')}")
        
        # 全キー表示
        print(f"  全キー: {list(order.keys())}")
    else:
        cm_label = "新規" if cash_margin in (2, "2") else "現物" if cash_margin in (1, "1") else str(cash_margin)
        print(f"  {cm_label}: {symbol} Side={side} Price={price} Qty={cum_qty}")
