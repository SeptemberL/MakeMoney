from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import requests


@dataclass(frozen=True)
class StockQuote:
    code: str  # e.g. sz300308 / sh588170 / hk09992 / bj430047
    name: str
    now: float
    prev_close: float
    high: float
    low: float
    avg: float
    change: float
    change_percent: float
    volume: float
    turnover: float

    def to_dict(self) -> dict:
        return asdict(self)


_QT_URL = "https://qt.gtimg.cn/q="
_LINE_RE = re.compile(r'^v_([^=]+)="([^"]*)";?$')


def format_code(code: str) -> Optional[str]:
    """
    将用户输入转换为腾讯行情代码格式：
    - A股：sh600000 / sz000001
    - 北交所：bj430047 / bj920809
    - 港股：hk09992（5位左补0）

    规则对齐 TestScripts/nmstock_nga.html 中的 formatCode。
    """
    if code is None:
        return None
    code = str(code).strip().lower()
    if not code:
        return None

    # 兼容类似 000001.SZ / 600000.SH / 600000.SS(别名) / 430047.BJ
    if "." in code:
        left, right = code.split(".", 1)
        right = right.strip().lower()
        left = left.strip()

        # 兼容常见误写：A股后缀 `.SS` -> 实际应为 `.SH`
        if right == "ss":
            right = "sh"

        # 若 left 是 6 位数字，优先用数字前缀判定市场：
        # - 4/8/9 开头：北交所 bj
        # - 5[168]/6 开头：上交所 sh
        # - 1[568]/0/3 开头：深交所 sz
        # 这样即便后缀写错（如 `430047.SS`），也能落到正确市场。
        if re.match(r"^\d{6}$", left):
            if re.match(r"^(4|8|9)", left):
                return "bj" + left
            if re.match(r"^(5[168]|6)", left):
                return "sh" + left
            if re.match(r"^(1[568]|0|3)", left):
                return "sz" + left

        if right in ("sz", "sh", "bj", "hk"):
            code = f"{right}{left}"
        # else: keep as-is

    if re.match(r"^(sh|sz|hk|bj)", code):
        return code

    if re.match(r"^\d+$", code):
        if len(code) <= 4 or (len(code) == 5 and code.startswith("0")):
            return "hk" + code.zfill(5)
        if len(code) == 6:
            if re.match(r"^(5[168]|6)", code):
                return "sh" + code
            if re.match(r"^(1[568]|0|3)", code):
                return "sz" + code
            if re.match(r"^(4|8|9)", code):
                return "bj" + code

    return code


def _safe_float(v: str) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _parse_one(code: str, payload: str) -> Optional[StockQuote]:
    """
    payload 为 qt.gtimg.cn 返回的引号内字段串，使用 ~ 分隔。
    字段索引对齐 nmstock_nga.html：
    - d[1] name
    - d[3] now
    - d[4] prevClose
    - d[33] high
    - d[34] low
    - d[36] volume
    - d[37] turnover
    """
    d = payload.split("~")
    if len(d) < 38:
        return None

    name = d[1]
    now = _safe_float(d[3])
    prev_close = _safe_float(d[4])
    day_high = _safe_float(d[33]) or now
    day_low = _safe_float(d[34]) or now
    volume = _safe_float(d[36])
    turnover = _safe_float(d[37])

    if code.startswith("hk"):
        avg = turnover / volume if volume > 0 else prev_close
    else:
        avg = (turnover * 10000) / (volume * 100) if volume > 0 else prev_close
    avg = float(f"{avg:.3f}") if avg else 0.0

    change = now - prev_close if prev_close > 0 else 0.0
    change_percent = (change / prev_close) * 100 if prev_close > 0 else 0.0

    return StockQuote(
        code=code,
        name=name,
        now=now,
        prev_close=prev_close,
        high=day_high,
        low=day_low,
        avg=avg,
        change=change,
        change_percent=change_percent,
        volume=volume,
        turnover=turnover,
    )


def fetch_quotes(
    codes: Sequence[str],
    *,
    timeout: float = 6.0,
    session: Optional[requests.Session] = None,
) -> Dict[str, StockQuote]:
    """
    批量获取实时行情。

    参数 codes 支持：
    - "300308" / "588170" / "9992"
    - "sz300308" / "sh588170" / "hk09992" / "bj430047"
    - "000001.SZ" / "600000.SH"

    返回：
    - dict: { full_code: StockQuote }
    """
    if not codes:
        return {}

    formatted: List[str] = []
    for c in codes:
        fc = format_code(c)
        if fc:
            formatted.append(fc)
    if not formatted:
        return {}

    query = ",".join(formatted)
    s = session or requests.Session()
    resp = s.get(
        _QT_URL + query,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://qt.gtimg.cn/",
        },
    )
    resp.raise_for_status()
    text = resp.text

    results: Dict[str, StockQuote] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        code, payload = m.group(1), m.group(2)
        q = _parse_one(code, payload)
        if q:
            results[code] = q

    return results


def fetch_quote(code: str, *, timeout: float = 6.0, session: Optional[requests.Session] = None) -> Optional[StockQuote]:
    """单只股票实时行情（fetch_quotes 的便捷封装）。"""
    return fetch_quotes([code], timeout=timeout, session=session).get(format_code(code) or code)

