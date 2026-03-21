"""腾讯行情解析：均价分支与压力/支撑线（对齐 StockCalculateTools.html）。"""
import sys
import unittest
from unittest.mock import MagicMock

# stock_quote_tencent 顶层依赖 requests；本测试仅校验解析公式，无需真实 HTTP。
sys.modules.setdefault("requests", MagicMock())

from stocks.stock_quote_tencent import INTRADAY_AVG_K, _parse_one


def _payload(
    *,
    name="N",
    now="10.0",
    prev_close="9.0",
    high="11",
    low="8",
    volume="100000",
    turnover="1234.5",
):
    d = [""] * 38
    d[1] = name
    d[3] = now
    d[4] = prev_close
    d[33] = high
    d[34] = low
    d[36] = volume
    d[37] = turnover
    return "~".join(d)


class TestParseOneIntradayAvg(unittest.TestCase):
    def test_main_board_avg_formula(self):
        q = _parse_one("sz000001", _payload(volume="100000", turnover="1234.5"))
        self.assertIsNotNone(q)
        raw = (1234.5 * 10000) / (100000 * 100)
        expected = float(f"{raw:.3f}")
        self.assertAlmostEqual(q.avg, expected, places=3)

    def test_star_bj_avg_uses_volume_not_hundred(self):
        q = _parse_one("sh688001", _payload(volume="2000", turnover="40"))
        self.assertIsNotNone(q)
        # (40 * 10000) / 2000 = 200
        self.assertAlmostEqual(q.avg, 200.0, places=3)
        q2 = _parse_one("bj430047", _payload(volume="2000", turnover="40"))
        self.assertAlmostEqual(q2.avg, 200.0, places=3)

    def test_hk_avg_is_turnover_over_volume(self):
        q = _parse_one("hk09992", _payload(volume="1000", turnover="5000"))
        self.assertIsNotNone(q)
        self.assertAlmostEqual(q.avg, 5.0, places=3)

    def test_zero_volume_falls_back_prev_close(self):
        q = _parse_one("sz000001", _payload(volume="0", turnover="0", prev_close="9.25"))
        self.assertIsNotNone(q)
        self.assertAlmostEqual(q.avg, 9.25, places=3)

    def test_pressure_support_when_avg_positive(self):
        q = _parse_one("sz000001", _payload(volume="100000", turnover="1234.5"))
        self.assertIsNotNone(q)
        self.assertGreater(q.avg, 0)
        self.assertIsNotNone(q.pressure_line)
        self.assertIsNotNone(q.support_line)
        self.assertAlmostEqual(q.pressure_line, q.avg / INTRADAY_AVG_K, places=3)
        self.assertAlmostEqual(q.support_line, q.avg * INTRADAY_AVG_K, places=3)

    def test_pressure_support_none_when_avg_zero(self):
        q = _parse_one("sz000001", _payload(volume="0", turnover="0", prev_close="0"))
        self.assertIsNotNone(q)
        self.assertEqual(q.avg, 0.0)
        self.assertIsNone(q.pressure_line)
        self.assertIsNone(q.support_line)


if __name__ == "__main__":
    unittest.main()
