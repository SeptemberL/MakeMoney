"""量化回测模块（策略执行与结果结构）。"""
from backtest.engine import run_ma_crossover_backtest
from backtest.types import BacktestInput, BacktestResult

__all__ = ["BacktestInput", "BacktestResult", "run_ma_crossover_backtest"]
