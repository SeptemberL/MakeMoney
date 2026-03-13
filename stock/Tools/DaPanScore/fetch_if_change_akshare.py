#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 AKShare 获取中金所股指期货(IF/IH/IC/IM)当前涨跌百分比。
数据来源：新浪财经-期货实时行情 ak.futures_zh_realtime(symbol="品种名称")

支持代码：
  IF - 沪深300股指期货
  IH - 上证50股指期货
  IC - 中证500股指期货
  IM - 中证1000股指期货
"""

try:
    import akshare as ak
except ImportError:
    ak = None

# 期指代码 -> AKShare 品种名称（中金所）
INDEX_FUTURES_SYMBOLS = {
    "IF": "沪深300指数期货",
    "IH": "上证50指数期货",
    "IC": "中证500指数期货",
    "IM": "中证1000股指期货",
}


def _resolve_symbol(symbol: str) -> str | None:
    """将 IF/IH/IC/IM 解析为 AKShare 品种名称，无效返回 None。"""
    if not symbol:
        return None
    u = symbol.strip().upper()
    return INDEX_FUTURES_SYMBOLS.get(u)


def get_index_futures_change_pct(symbol: str = "IF") -> float | None:
    """
    获取指定股指期货连续合约的当前涨跌百分比。

    Args:
        symbol: 期指代码 "IF"(沪深300)、"IH"(上证50)、"IC"(中证500)、"IM"(中证1000)。

    Returns:
        涨跌幅百分比，如 0.94 表示涨 0.94%，-0.3 表示跌 0.3%。
        请求失败或 symbol 无效时返回 None。
    """
    if ak is None:
        print("请安装 akshare: pip install akshare")
        return None

    name = _resolve_symbol(symbol)
    if name is None:
        print(f"不支持的期指代码: {symbol}，可选: {list(INDEX_FUTURES_SYMBOLS.keys())}")
        return None

    try:
        df = ak.futures_zh_realtime(symbol=name)
    except Exception as e:
        print(f"获取 {symbol} 行情失败: {e}")
        return None

    if df is None or df.empty or "changepercent" not in df.columns:
        return None

    # 第一行为连续合约
    pct = df["changepercent"].iloc[0]
    if pct is None or (isinstance(pct, float) and (pct != pct)):  # NaN
        return None
    # AKShare 返回的 changepercent 为小数，如 0.009376 表示 0.94%
    return round(float(pct) * 100.0, 2)


def get_index_futures_quote(symbol: str = "IF") -> dict | None:
    """
    获取指定股指期货连续合约的行情摘要（现价、昨结、涨跌额、涨跌幅、名称）。

    Args:
        symbol: 期指代码 "IF"、"IH"、"IC"、"IM"。

    Returns:
        包含 name, symbol, price, prev_settlement, change, change_pct 的字典，失败返回 None。
    """
    if ak is None:
        return None

    name = _resolve_symbol(symbol)
    if name is None:
        return None

    try:
        df = ak.futures_zh_realtime(symbol=name)
    except Exception as e:
        print(f"获取 {symbol} 行情失败: {e}")
        return None

    if df is None or df.empty:
        return None

    row = df.iloc[0]
    price = row.get("trade")
    prev_settlement = row.get("presettlement") or row.get("prevsettlement")
    if price is None or prev_settlement is None:
        return None

    price = float(price)
    prev_settlement = float(prev_settlement)
    change = price - prev_settlement
    pct = row.get("changepercent")
    if pct is not None and (not (isinstance(pct, float) and (pct != pct))):
        change_pct = round(float(pct) * 100.0, 2)
    else:
        change_pct = round((change / prev_settlement * 100.0), 2) if prev_settlement else 0.0

    return {
        "name": str(row.get("name", name + "连续")),
        "symbol": str(row.get("symbol", symbol + "0")),
        "price": round(price, 2),
        "prev_settlement": round(prev_settlement, 2),
        "change": round(change, 2),
        "change_pct": change_pct,
    }


# 兼容旧调用：保留 IF 专用别名
def get_if_change_pct() -> float | None:
    """获取沪深300股指期货 IF 涨跌百分比（等价于 get_index_futures_change_pct('IF')）。"""
    return get_index_futures_change_pct("IF")


def get_if_quote() -> dict | None:
    """获取沪深300股指期货 IF 行情（等价于 get_index_futures_quote('IF')）。"""
    return get_index_futures_quote("IF")


if __name__ == "__main__":
    import sys

    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["IF", "IH", "IC", "IM"]
    for sym in symbols:
        pct = get_index_futures_change_pct(sym)
        if pct is not None:
            print(f"{sym} 涨跌百分比: {pct}%")
        quote = get_index_futures_quote(sym)
        if quote:
            print(
                f"  {quote['name']} 现价:{quote['price']} 昨结:{quote['prev_settlement']} "
                f"涨跌:{quote['change']} 涨跌幅:{quote['change_pct']}%"
            )
