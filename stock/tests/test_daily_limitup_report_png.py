from __future__ import annotations

from pathlib import Path

from tasks.daily_limitup_report_png import read_daily_limitup_report_json, write_daily_limitup_report_png


def test_generate_png_pages_from_sample_report():
    # 依赖仓库里已有的示例输出（由 daily_limitup_report 生成）
    trade_date = "2026-03-30"
    report = read_daily_limitup_report_json(trade_date=trade_date)
    paths = write_daily_limitup_report_png(report)

    assert paths, "should generate at least one PNG"
    for p in paths:
        pp = Path(p)
        assert pp.exists(), f"missing png: {p}"
        assert pp.stat().st_size > 10_000, f"png too small: {p}"

