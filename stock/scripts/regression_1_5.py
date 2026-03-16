#!/usr/bin/env python3
"""
阶段 1.5 整体回归测试：在 Flask 已启动的前提下，请求关键页面/接口并记录结果。
使用方式：
  1. 终端一：python main.py
  2. 终端二：python scripts/regression_1_5.py
  或指定 base_url：python scripts/regression_1_5.py --base http://127.0.0.1:5123
"""
import argparse
import sys
from pathlib import Path

# 项目根目录加入 path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import urllib.request
    import urllib.error
    import ssl
except ImportError:
    pass


def get(url: str, timeout: int = 10, allow_insecure: bool = True):
    try:
        req = urllib.request.Request(url, method="GET")
        if url.startswith("https://") and allow_insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            r = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        else:
            r = urllib.request.urlopen(req, timeout=timeout)
        return r.getcode(), r.read()[:500]
    except urllib.error.HTTPError as e:
        return e.code, getattr(e, "read", lambda: b"")()[:500]
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser(description="阶段 1.5 回归：请求关键接口")
    parser.add_argument("--base", default="http://127.0.0.1:5123", help="Flask base URL")
    parser.add_argument("--no-insecure", action="store_true", help="禁用 SSL 忽略（用于 HTTPS）")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    allow_insecure = not args.no_insecure

    checks = [
        ("GET /", f"{base}/"),
        ("GET /stock_filter", f"{base}/stock_filter"),
        ("GET /api/get-timed-scan-list", f"{base}/api/get-timed-scan-list"),
        ("GET /api/stock_data/000001", f"{base}/api/stock_data/000001"),
        ("GET /api/stocks", f"{base}/api/stocks"),
        ("GET /quant", f"{base}/quant"),
        ("GET /market_open_score", f"{base}/market_open_score"),
    ]
    print("阶段 1.5 回归检查（base=%s）\n" % base)
    ok = 0
    for name, url in checks:
        code, body = get(url, allow_insecure=allow_insecure)
        if code == 200:
            status = "OK"
            ok += 1
        elif code is None:
            status = "ERR: " + (body or "?")[:80]
        else:
            status = "HTTP %s" % code
        print("  %-40s %s" % (name, status))
    print("\n通过: %s/%s" % (ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
