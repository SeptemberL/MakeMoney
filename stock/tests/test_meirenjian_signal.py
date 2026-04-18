"""美人肩（MEIRENJIAN）筛选信号单元测试。"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

import pandas as pd

from signals.signal_meirenjian import Signal_MeirenJian


class TestMeirenJianSignal(unittest.TestCase):
    def _df(self):
        # 构造一个非常“干净”的合成形态：
        # LS(1)->NL1(2)->T(3)->NL2(4)->RS(5)
        base = datetime(2026, 1, 1)
        trade_dates = [base + timedelta(days=i) for i in range(7)]
        highs = [10, 12, 11, 15, 10, 12, 11]
        lows = [9, 10, 8, 11, 7, 10, 10]
        closes = [9.5, 11.5, 9.0, 14.0, 8.0, 11.0, 10.5]
        opens = [9.2, 11.0, 9.5, 13.0, 8.5, 10.5, 10.3]
        vols = [100] * 7

        return pd.DataFrame(
            {
                "trade_date": trade_dates,
                "code": ["000001"] * 7,
                "name": ["测试"] * 7,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": vols,
            }
        )

    def test_hit_simple_pattern(self):
        df = self._df()
        sig = Signal_MeirenJian(
            lookbackBars=7,
            minBars=6,
            pivotLeft=1,
            pivotRight=1,
            maxNecklineSlopeAbs=0.5,
            minHeadAboveShoulderPct=0.05,
            maxShoulderHeightDiffPct=0.05,
            minPatternBars=3,
            maxPatternBars=10,
            minScore=0.2,
        )
        out, _, _ = sig.calculate(df)
        self.assertEqual(int(out["meirenjian_hit"].iloc[-1]), 1)
        self.assertGreaterEqual(float(out["meirenjian_score"].iloc[-1]), 0.2)
        meta_json = str(out["meirenjian_meta_json"].iloc[-1] or "")
        meta = json.loads(meta_json)
        self.assertIn("points", meta)
        self.assertIn("neckline", meta)
        self.assertIn("window", meta)
        self.assertIn("LS", meta["points"])
        self.assertIn("T", meta["points"])
        self.assertIn("RS", meta["points"])

    def test_insufficient_bars(self):
        df = self._df().head(3)
        sig = Signal_MeirenJian(minBars=6)
        out, _, _ = sig.calculate(df)
        self.assertEqual(int(out["meirenjian_hit"].iloc[-1]), 0)
        self.assertEqual(str(out["meirenjian_reason"].iloc[-1]), "insufficient_bars")


if __name__ == "__main__":
    unittest.main()

