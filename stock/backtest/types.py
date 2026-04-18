"""回测输入输出数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BacktestInput:
    stock_code: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    strategy: str = "ma_crossover"
    short_window: int = 5
    long_window: int = 20
    initial_cash: float = 100_000.0
    commission_rate: float = 0.0005  # 单边费率近似


@dataclass
class BacktestResult:
    success: bool
    error: Optional[str] = None
    stock_code: str = ""
    start_date: str = ""
    end_date: str = ""
    strategy: str = ""
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    final_equity: float = 0.0
    initial_cash: float = 0.0
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    bars: int = 0

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "error": self.error,
            "stock_code": self.stock_code,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "strategy": self.strategy,
            "total_return_pct": round(self.total_return_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "final_equity": round(self.final_equity, 2),
            "initial_cash": round(self.initial_cash, 2),
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "bars": self.bars,
        }
