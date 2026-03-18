import os
import sys

# 允许直接运行本脚本：将项目根目录加入 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from stocks.stock_quote_tencent import fetch_quotes


def main():
    quotes = fetch_quotes(["300308", "588170", "9992", "000001.SZ", "600000.SH"])
    for k, q in quotes.items():
        print(
            k,
            q.name,
            "now=",
            q.now,
            "pct=",
            round(q.change_percent, 2),
            "avg=",
            q.avg,
            "high=",
            q.high,
            "low=",
            q.low,
        )


if __name__ == "__main__":
    main()

