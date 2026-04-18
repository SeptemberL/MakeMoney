"""双均线交叉策略回测（逐日、收盘价成交）。"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from backtest.types import BacktestInput, BacktestResult


def run_ma_crossover_backtest(
    df: pd.DataFrame,
    inp: BacktestInput,
) -> BacktestResult:
    """
    df: 需含列 close，按 trade_date 升序；索引可为 RangeIndex。
    金叉买入、死叉卖出；全额做多/空仓；佣金按成交金额双边近似。
    """
    code = inp.stock_code
    short_w = max(1, int(inp.short_window))
    long_w = max(2, int(inp.long_window))
    if short_w >= long_w:
        return BacktestResult(
            success=False,
            error="短期均线周期必须小于长期均线周期",
            stock_code=code,
            start_date=inp.start_date,
            end_date=inp.end_date,
            strategy=inp.strategy,
            initial_cash=float(inp.initial_cash),
        )

    if df is None or df.empty:
        return BacktestResult(
            success=False,
            error="没有可用的行情数据（请确认本地已拉取该标的日线）",
            stock_code=code,
            start_date=inp.start_date,
            end_date=inp.end_date,
            strategy=inp.strategy,
            initial_cash=float(inp.initial_cash),
        )

    d = df.copy()
    if "close" not in d.columns:
        return BacktestResult(
            success=False,
            error="行情数据缺少 close 列",
            stock_code=code,
            start_date=inp.start_date,
            end_date=inp.end_date,
            strategy=inp.strategy,
            initial_cash=float(inp.initial_cash),
        )

    if "trade_date" not in d.columns:
        return BacktestResult(
            success=False,
            error="行情数据缺少 trade_date 列",
            stock_code=code,
            start_date=inp.start_date,
            end_date=inp.end_date,
            strategy=inp.strategy,
            initial_cash=float(inp.initial_cash),
        )

    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["close"])
    d["trade_date"] = pd.to_datetime(d["trade_date"])
    d = d.sort_values("trade_date").reset_index(drop=True)

    if len(d) < long_w + 2:
        return BacktestResult(
            success=False,
            error=f"有效 K 线不足（至少需要约 {long_w + 2} 根，当前 {len(d)}）",
            stock_code=code,
            start_date=inp.start_date,
            end_date=inp.end_date,
            strategy=inp.strategy,
            initial_cash=float(inp.initial_cash),
            bars=len(d),
        )

    close = d["close"].to_numpy(dtype=float)
    tseries = pd.to_datetime(d["trade_date"])

    ma_s = pd.Series(close).rolling(short_w, min_periods=short_w).mean().to_numpy()
    ma_l = pd.Series(close).rolling(long_w, min_periods=long_w).mean().to_numpy()

    cash = float(inp.initial_cash)
    shares = 0.0
    comm = float(inp.commission_rate)
    trades: list[dict] = []
    equity_curve: list[dict] = []

    def _date_str(i: int) -> str:
        dt = tseries.iloc[i]
        return pd.Timestamp(dt).strftime("%Y-%m-%d")

    peak = float(inp.initial_cash)
    max_dd = 0.0

    for i in range(1, len(close)):
        if np.isnan(ma_s[i]) or np.isnan(ma_l[i]) or np.isnan(ma_s[i - 1]) or np.isnan(ma_l[i - 1]):
            eq = cash + shares * close[i]
            equity_curve.append({"trade_date": _date_str(i), "equity": round(eq, 2)})
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)
            continue

        golden = ma_s[i - 1] <= ma_l[i - 1] and ma_s[i] > ma_l[i]
        death = ma_s[i - 1] >= ma_l[i - 1] and ma_s[i] < ma_l[i]

        price = float(close[i])

        if golden and shares == 0 and cash > 0:
            cost = cash * (1 - comm)
            qty = cost / price
            fee = cash - cost
            trades.append(
                {
                    "date": _date_str(i),
                    "side": "BUY",
                    "price": round(price, 4),
                    "quantity": round(qty, 4),
                    "fee": round(fee, 2),
                }
            )
            shares = qty
            cash = 0.0

        elif death and shares > 0:
            gross = shares * price
            fee = gross * comm
            cash = gross - fee
            trades.append(
                {
                    "date": _date_str(i),
                    "side": "SELL",
                    "price": round(price, 4),
                    "quantity": round(shares, 4),
                    "fee": round(fee, 2),
                }
            )
            shares = 0.0

        eq = cash + shares * close[i]
        equity_curve.append({"trade_date": _date_str(i), "equity": round(eq, 2)})
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)

    final_eq = cash + shares * float(close[-1])
    init = float(inp.initial_cash)
    total_ret = (final_eq - init) / init * 100.0 if init > 0 else 0.0

    return BacktestResult(
        success=True,
        error=None,
        stock_code=code,
        start_date=inp.start_date,
        end_date=inp.end_date,
        strategy=inp.strategy,
        total_return_pct=total_ret,
        max_drawdown_pct=max_dd * 100.0,
        final_equity=final_eq,
        initial_cash=init,
        trades=trades,
        equity_curve=equity_curve,
        bars=len(d),
    )


def normalize_stock_code(raw: str) -> Optional[str]:
    """返回 6 位数字代码；非法则 None。"""
    s = (raw or "").strip()
    if not s:
        return None
    if "." in s:
        s = s.split(".")[0]
    if len(s) == 6 and s.isdigit():
        return s
    return None
