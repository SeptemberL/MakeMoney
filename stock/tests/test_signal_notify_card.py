"""signal_notify_card 编码与 payload 行生成。"""
from signals.signal_notify_card import (
    decode_notify_card_payload,
    encode_notify_card_payload,
    normalize_notify_card_input,
    rows_from_signal_payload,
)


def test_encode_decode_roundtrip():
    data = {"title": "检测到价", "stockName": "测试", "rows": [{"label": "a", "value": "b"}]}
    t = encode_notify_card_payload(data)
    back = decode_notify_card_payload(t)
    assert back["title"] == "检测到价"
    assert back["stockName"] == "测试"


def test_rows_from_price_level_payload():
    p = {
        "signal_type": "price_level_interval",
        "stock_name": "X",
        "stock_code": "1",
        "price": 10.5,
        "target_price": 10.0,
        "mode_label": "高于等于目标价",
        "time": "2026-01-01 12:00:00",
    }
    rows = rows_from_signal_payload(p)
    labels = [r["label"] for r in rows]
    assert "采用策略" in labels
    assert "目标价" in labels


def test_normalize_uses_signal_payload_for_rows():
    n = normalize_notify_card_input(
        {
            "signal_payload": {
                "signal_type": "price_range",
                "stock_name": "N",
                "stock_code": "C",
                "price": 1.0,
                "lower": 0.5,
                "upper": 2.0,
                "boundary": "inside_range",
                "time": "t",
            }
        }
    )
    assert n["stockName"] == "N"
    assert n["stockCode"] == "C"
    assert len(n["rows"]) >= 2
