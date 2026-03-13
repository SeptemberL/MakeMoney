#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取 A50 期指当月连续(CN00Y) 当前涨跌百分比。
数据来源：东方财富 push2 行情接口。
参考页面：https://quote.eastmoney.com/option/104.CN00Y.html
"""

import json
import urllib.request
import urllib.error


# 东方财富 A50 期指 secid（104 = 期货类）
SECID_A50 = "104.CN00Y"
API_URL = "https://push2.eastmoney.com/api/qt/stock/get"


def _make_request(secid: str) -> dict:
    """请求 push2 行情接口，返回解析后的 JSON。"""
    # 常用字段：f43=现价, f44=涨跌额, f60=昨收, f170=涨跌幅, f58=名称, f57=代码
    params = {
        "secid": secid,
        "fields": "f43,f44,f58,f60,f170",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API_URL}?{qs}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_a50_change_pct() -> float | None:
    """
    获取 A50 期指当月连续(CN00Y) 的当前涨跌百分比。

    Returns:
        涨跌幅百分比，如 0.5 表示涨 0.5%，-0.3 表示跌 0.3%。
        请求失败或数据异常时返回 None。
    """
    try:
        data = _make_request(SECID_A50)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"请求失败: {e}")
        return None

    if not data.get("data"):
        print("接口未返回行情数据")
        return None

    d = data["data"]
    # 东方财富价格类字段多为整数，需除以 100
    # f170: 涨跌幅（百分比），若存在则直接使用
    change_pct = d.get("f170")
    if change_pct is not None:
        return round(change_pct / 100.0, 2)

    # 若无 f170，用现价与昨收计算
    price = d.get("f43")  # 现价
    prev_close = d.get("f60")  # 昨收
    if price is not None and prev_close is not None and prev_close != 0:
        return round((price - prev_close) / prev_close * 100.0, 2)

    return None


def get_a50_quote() -> dict | None:
    """
    获取 A50 期指完整行情摘要（现价、昨收、涨跌额、涨跌幅、名称）。

    Returns:
        包含 name, price, prev_close, change, change_pct 的字典，失败返回 None。
    """
    try:
        data = _make_request(SECID_A50)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"请求失败: {e}")
        return None

    if not data.get("data"):
        return None

    d = data["data"]
    price = d.get("f43")
    prev_close = d.get("f60")
    if price is None or prev_close is None:
        return None

    # 价格需除以 100
    price = price / 100.0
    prev_close = prev_close / 100.0
    change = price - prev_close
    change_pct = d.get("f170")
    if change_pct is not None:
        change_pct = change_pct / 100.0
    else:
        change_pct = (change / prev_close * 100.0) if prev_close else 0

    return {
        "name": d.get("f58") or "A50期指当月连续",
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
    }


if __name__ == "__main__":
    pct = get_a50_change_pct()
    if pct is not None:
        print(f"A50期指当月连续 涨跌百分比: {pct}%")

    quote = get_a50_quote()
    if quote:
        print(
            f"{quote['name']} 现价:{quote['price']} 昨收:{quote['prev_close']} "
            f"涨跌:{quote['change']} 涨跌幅:{quote['change_pct']}%"
        )
