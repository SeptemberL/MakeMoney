import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PivotPoint:
    idx: int
    price: float
    kind: str  # "H" or "L"


class Signal_MeirenJian:
    """
    美人肩形态（简化实现）
    - 通过 pivot high/low 提取关键点 LS/NL1/T/NL2/RS
    - 在最新一根 K（或接近末端的 pivot high）上打标，供 StockFilger.calculate_signal 逐行读取
    """

    def __init__(
        self,
        *,
        lookbackBars: int = 120,
        minBars: int = 60,
        pivotLeft: int = 3,
        pivotRight: int = 3,
        maxNecklineSlopeAbs: float = 0.02,
        minHeadAboveShoulderPct: float = 0.03,
        maxShoulderHeightDiffPct: float = 0.03,
        minPatternBars: int = 15,
        maxPatternBars: int = 90,
        minScore: float = 0.6,
    ):
        self.lookbackBars = int(lookbackBars)
        self.minBars = int(minBars)
        self.pivotLeft = int(pivotLeft)
        self.pivotRight = int(pivotRight)
        self.maxNecklineSlopeAbs = float(maxNecklineSlopeAbs)
        self.minHeadAboveShoulderPct = float(minHeadAboveShoulderPct)
        self.maxShoulderHeightDiffPct = float(maxShoulderHeightDiffPct)
        self.minPatternBars = int(minPatternBars)
        self.maxPatternBars = int(maxPatternBars)
        self.minScore = float(minScore)

    def _pivots(self, arr: List[float], left: int, right: int, kind: str) -> List[int]:
        if arr is None or len(arr) == 0:
            return []
        n = len(arr)
        out: List[int] = []
        for i in range(left, n - right):
            window = arr[i - left : i + right + 1]
            v = arr[i]
            if v is None or not math.isfinite(float(v)):
                continue
            if kind == "H":
                wmax = max(window)
                if v == wmax and sum(1 for x in window if x == v) == 1:
                    out.append(i)
            else:
                wmin = min(window)
                if v == wmin and sum(1 for x in window if x == v) == 1:
                    out.append(i)
        return out

    def _neckline_slope(self, nl1: PivotPoint, nl2: PivotPoint) -> float:
        dx = float(nl2.idx - nl1.idx)
        if dx <= 0:
            return float("inf")
        # 相对变化 / 每根K
        base = float(nl1.price) if float(nl1.price) != 0.0 else 1.0
        return ((float(nl2.price) - float(nl1.price)) / base) / dx

    def _score(
        self,
        *,
        ls: PivotPoint,
        t: PivotPoint,
        rs: PivotPoint,
        nl_slope_abs: float,
        span: int,
    ) -> float:
        shoulder_avg = (ls.price + rs.price) / 2.0 if (ls.price + rs.price) != 0 else max(ls.price, rs.price, 1.0)
        head_boost = max(0.0, (t.price - shoulder_avg) / max(shoulder_avg, 1e-9))
        head_score = min(1.0, head_boost / max(self.minHeadAboveShoulderPct, 1e-9))

        shoulder_diff = abs(ls.price - rs.price) / max(shoulder_avg, 1e-9)
        shoulder_score = max(0.0, 1.0 - (shoulder_diff / max(self.maxShoulderHeightDiffPct, 1e-9)))

        slope_score = max(0.0, 1.0 - (nl_slope_abs / max(self.maxNecklineSlopeAbs, 1e-9)))

        # span 越接近区间中间越好
        mid = (self.minPatternBars + self.maxPatternBars) / 2.0
        half = max(1.0, (self.maxPatternBars - self.minPatternBars) / 2.0)
        span_score = max(0.0, 1.0 - abs(float(span) - mid) / half)

        # 加权平均
        return float(0.35 * head_score + 0.30 * shoulder_score + 0.20 * slope_score + 0.15 * span_score)

    def _find_latest_pattern(self, df: pd.DataFrame) -> Tuple[bool, float, str, Optional[Dict[str, Any]]]:
        if df is None or df.empty:
            return False, 0.0, "empty_df", None
        if len(df) < self.minBars:
            return False, 0.0, "insufficient_bars", None

        dfw = df.tail(self.lookbackBars).copy()
        highs_s = pd.to_numeric(dfw.get("high"), errors="coerce")
        lows_s = pd.to_numeric(dfw.get("low"), errors="coerce")
        highs = [float(x) for x in highs_s.fillna(float("nan")).tolist()]
        lows = [float(x) for x in lows_s.fillna(float("nan")).tolist()]
        if len(highs) < self.minBars:
            return False, 0.0, "insufficient_window_bars", None

        ph = self._pivots(highs, self.pivotLeft, self.pivotRight, "H")
        pl = self._pivots(lows, self.pivotLeft, self.pivotRight, "L")
        if len(ph) < 3 or len(pl) < 2:
            return False, 0.0, "not_enough_pivots", None

        # 从最新的 pivot high 开始回溯找 RS
        for rs_i in reversed(ph):
            # RS 不要离末端太远（右侧还需要 pivotRight 支撑）
            if rs_i < len(dfw) - 1 - self.pivotRight - 1:
                # 允许 RS 不一定是最后一个 pivot high，但尽量靠后
                pass

            # 找头部 T：RS 之前最近的 pivot high，且更高
            t_candidates = [i for i in ph if i < rs_i]
            if not t_candidates:
                continue
            # 优先选择 rs_i 之前最高的 pivot high 作为头部
            t_i = max(t_candidates, key=lambda i: highs[i])

            # 找左肩 LS：T 之前的 pivot high，且接近 RS 高度
            ls_candidates = [i for i in ph if i < t_i]
            if not ls_candidates:
                continue
            # 选择距离 T 最近且高度与 RS 接近的点
            def ls_key(i: int) -> Tuple[float, int]:
                height_diff = abs(highs[i] - highs[rs_i]) / max((highs[i] + highs[rs_i]) / 2.0, 1e-9)
                return (height_diff, -(t_i - i))

            ls_i = min(ls_candidates, key=ls_key)

            # NL1 在 LS 与 T 之间的 pivot low
            nl1_candidates = [i for i in pl if ls_i < i < t_i]
            # NL2 在 T 与 RS 之间的 pivot low
            nl2_candidates = [i for i in pl if t_i < i < rs_i]
            if not nl1_candidates or not nl2_candidates:
                continue
            nl1_i = min(nl1_candidates, key=lambda i: lows[i])
            nl2_i = min(nl2_candidates, key=lambda i: lows[i])

            # 时间顺序
            if not (ls_i < nl1_i < t_i < nl2_i < rs_i):
                continue

            ls = PivotPoint(idx=ls_i, price=float(highs[ls_i]), kind="H")
            t = PivotPoint(idx=t_i, price=float(highs[t_i]), kind="H")
            rs = PivotPoint(idx=rs_i, price=float(highs[rs_i]), kind="H")
            nl1 = PivotPoint(idx=nl1_i, price=float(lows[nl1_i]), kind="L")
            nl2 = PivotPoint(idx=nl2_i, price=float(lows[nl2_i]), kind="L")

            # 约束：头部突出
            shoulder_avg = (ls.price + rs.price) / 2.0
            if t.price <= max(ls.price, rs.price) * (1.0 + self.minHeadAboveShoulderPct):
                continue

            # 约束：肩部高度差
            shoulder_diff = abs(ls.price - rs.price) / max(shoulder_avg, 1e-9)
            if shoulder_diff > self.maxShoulderHeightDiffPct:
                continue

            # 约束：跨度
            span = int(rs.idx - ls.idx)
            if span < self.minPatternBars or span > self.maxPatternBars:
                continue

            # 约束：颈线斜率
            slope = self._neckline_slope(nl1, nl2)
            if (slope is None) or (not math.isfinite(float(slope))) or abs(float(slope)) > self.maxNecklineSlopeAbs:
                continue

            score = self._score(ls=ls, t=t, rs=rs, nl_slope_abs=abs(float(slope)), span=span)
            meta = {
                "points": {
                    "LS": {"idx": int(ls.idx), "price": float(ls.price)},
                    "T": {"idx": int(t.idx), "price": float(t.price)},
                    "RS": {"idx": int(rs.idx), "price": float(rs.price)},
                    "NL1": {"idx": int(nl1.idx), "price": float(nl1.price)},
                    "NL2": {"idx": int(nl2.idx), "price": float(nl2.price)},
                },
                "neckline": {"slope": float(slope), "nl1": {"idx": nl1.idx, "price": nl1.price}, "nl2": {"idx": nl2.idx, "price": nl2.price}},
                "window": {"lookbackBars": int(self.lookbackBars), "bars": int(len(dfw))},
            }
            return (score >= self.minScore), float(score), "ok" if score >= self.minScore else "score_below_min", meta

        return False, 0.0, "no_pattern", None

    def calculate(self, df: pd.DataFrame):
        """
        返回 (df, avg_return, positive_prob)，以兼容 StockFilger.filter_stock 的解包逻辑。
        本信号暂不计算 avg_return/positive_prob（留作后续回测统计），返回 0。
        """
        avg_return = 0.0
        positive_prob = 0.0
        if df is None or df.empty:
            return df, avg_return, positive_prob

        df = df.copy()
        df = df.sort_values("trade_date")

        hit, score, reason, meta = self._find_latest_pattern(df)
        df["meirenjian_hit"] = 0
        df["meirenjian_score"] = 0.0
        df["meirenjian_reason"] = ""
        df["meirenjian_meta_json"] = ""

        # 打标到最后一行（与 calculate_signal 的逐行扫描兼容）
        last_idx = df.index[-1]
        df.loc[last_idx, "meirenjian_score"] = float(score)
        df.loc[last_idx, "meirenjian_reason"] = str(reason)
        if meta is not None:
            try:
                df.loc[last_idx, "meirenjian_meta_json"] = json.dumps(meta, ensure_ascii=False)
            except Exception:
                df.loc[last_idx, "meirenjian_meta_json"] = ""
        if hit:
            df.loc[last_idx, "meirenjian_hit"] = 1

        return df, avg_return, positive_prob

    def generate_signals(self, dayData) -> List[str]:
        """
        dayData 为单行 Series（由 StockFilger.calculate_signal 传入）
        """
        try:
            if int(dayData.get("meirenjian_hit") or 0) != 1:
                return []
            score = float(dayData.get("meirenjian_score") or 0.0)
            return [f"美人肩形态命中（score={score:.2f}）"]
        except Exception as e:
            logger.debug("Signal_MeirenJian generate_signals failed: %s", e)
            return []

