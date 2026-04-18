"""回测引擎单元测试（不依赖数据库）。"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import pandas as pd

from backtest.engine import normalize_stock_code, run_ma_crossover_backtest
from backtest.types import BacktestInput


def _make_uptrend_df(n: int = 80) -> pd.DataFrame:
    base = datetime(2024, 1, 1)
    rows = []
    p = 10.0
    for i in range(n):
        p += 0.05
        d = base + timedelta(days=i)
        rows.append({"trade_date": d, "close": p})
    return pd.DataFrame(rows)


class TestBacktestEngine(unittest.TestCase):
    def test_normalize_stock_code(self):
        self.assertEqual(normalize_stock_code("600000"), "600000")
        self.assertEqual(normalize_stock_code("600000.SH"), "600000")
        self.assertIsNone(normalize_stock_code("abc"))

    def test_empty_df(self):
        inp = BacktestInput(
            stock_code="600000",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        r = run_ma_crossover_backtest(None, inp)
        self.assertFalse(r.success)
        self.assertIn("没有可用", r.error or "")

    def test_insufficient_bars(self):
        df = _make_uptrend_df(5)
        inp = BacktestInput(
            stock_code="600000",
            start_date="2024-01-01",
            end_date="2024-12-31",
            long_window=20,
        )
        r = run_ma_crossover_backtest(df, inp)
        self.assertFalse(r.success)
        self.assertIn("不足", r.error or "")

    def test_uptrend_has_result(self):
        df = _make_uptrend_df(120)
        inp = BacktestInput(
            stock_code="600000",
            start_date="2024-01-01",
            end_date="2024-12-31",
            short_window=5,
            long_window=20,
            initial_cash=100_000.0,
        )
        r = run_ma_crossover_backtest(df, inp)
        self.assertTrue(r.success)
        self.assertGreater(r.bars, 50)
        self.assertIsNotNone(r.final_equity)


if __name__ == "__main__":
    unittest.main()
