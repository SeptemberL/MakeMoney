"""到价提醒（price_level_interval）单元测试。"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from signals.signal_notify_system import (
    PRICE_LEVEL_INTERVAL_MIN_SECONDS,
    SignalConfig,
    SignalMessageTemplate,
    SendType,
    SingleType,
    create_signal_instance,
    validate_signal_rule_payload,
)


class TestPriceLevelIntervalSignal(unittest.TestCase):
    def _cfg(self, **kwargs):
        defaults = dict(
            stock_code="600000",
            stock_name="测试",
            group_ids=[1],
            signal_type=SingleType.PRICE_LEVEL_INTERVAL,
            params={"target_price": 10.0, "mode": "at_or_above"},
            message_template=SignalMessageTemplate(template="p={price:.2f} t={target_price:.2f}"),
            send_type=SendType.INTERVAL,
            send_interval_seconds=PRICE_LEVEL_INTERVAL_MIN_SECONDS,
            runtime_state={},
        )
        defaults.update(kwargs)
        return SignalConfig(**defaults)

    def test_reject_interval_below_min(self):
        cfg = self._cfg(send_interval_seconds=30)
        with self.assertRaises(ValueError):
            create_signal_instance(cfg)

    def test_reject_wrong_send_type(self):
        cfg = self._cfg(send_type=SendType.ON_TRIGGER)
        with self.assertRaises(ValueError):
            create_signal_instance(cfg)

    def test_reject_bad_mode(self):
        cfg = self._cfg(params={"target_price": 10.0, "mode": "invalid"})
        with self.assertRaises(ValueError):
            create_signal_instance(cfg)

    def test_validate_payload_helper(self):
        validate_signal_rule_payload(
            signal_type=SingleType.PRICE_LEVEL_INTERVAL,
            params={"target_price": 5.5, "mode": "at_or_below"},
            send_type=SendType.INTERVAL,
            send_interval_seconds=120,
            message_template="x {price}",
        )
        with self.assertRaises(ValueError):
            validate_signal_rule_payload(
                signal_type=SingleType.PRICE_LEVEL_INTERVAL,
                params={"target_price": 5.5, "mode": "at_or_below"},
                send_type=SendType.INTERVAL,
                send_interval_seconds=10,
                message_template="x {price}",
            )

    def test_interval_throttle_at_or_above(self):
        cfg = self._cfg()
        sig = create_signal_instance(cfg)
        t0 = datetime(2026, 1, 1, 10, 0, 0)
        m1 = sig.update(11.0, now=t0)
        self.assertEqual(len(m1), 1)
        m2 = sig.update(11.0, now=t0 + timedelta(seconds=30))
        self.assertEqual(len(m2), 0)
        m3 = sig.update(11.0, now=t0 + timedelta(seconds=60))
        self.assertEqual(len(m3), 1)

    def test_no_send_when_condition_false(self):
        cfg = self._cfg()
        sig = create_signal_instance(cfg)
        t0 = datetime(2026, 1, 1, 10, 0, 0)
        self.assertEqual(len(sig.update(9.0, now=t0)), 0)

    def test_state_roundtrip(self):
        t0 = datetime(2026, 1, 1, 10, 0, 0)
        cfg = self._cfg()
        sig = create_signal_instance(cfg)
        sig.update(11.0, now=t0)
        state = sig.get_runtime_state()
        self.assertIn("last_sent_at", state)
        cfg2 = self._cfg(runtime_state=state)
        sig2 = create_signal_instance(cfg2)
        self.assertEqual(len(sig2.update(11.0, now=t0 + timedelta(seconds=30))), 0)
        self.assertEqual(len(sig2.update(11.0, now=t0 + timedelta(seconds=60))), 1)

    def test_flash_false_does_not_reset_interval(self):
        """条件短时变假再变真，仍须满足与上次发送的完整间隔。"""
        cfg = self._cfg()
        sig = create_signal_instance(cfg)
        t0 = datetime(2026, 1, 1, 10, 0, 0)
        sig.update(11.0, now=t0)
        sig.update(9.0, now=t0 + timedelta(seconds=10))
        m = sig.update(11.0, now=t0 + timedelta(seconds=20))
        self.assertEqual(len(m), 0)
        m2 = sig.update(11.0, now=t0 + timedelta(seconds=60))
        self.assertEqual(len(m2), 1)


if __name__ == "__main__":
    unittest.main()
