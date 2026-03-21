"""
股票信号通知系统（基础版）
1.1~1.3 的最小可运行实现：
- 预留 UI 接口定义（用于悬浮页面配置）
- 信号系统基础框架（股票、群组、信号参数、模板、发送类型）
- 基础信号：股价区间上下限触发（上限一次、下限一次）
- 到价提醒（price_level_interval）：到达目标价条件后按固定秒数节流重复提醒
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# 到价提醒（price_level_interval）最小发送间隔（秒），与规格一致
PRICE_LEVEL_INTERVAL_MIN_SECONDS = 60


class SingleType(str, Enum):
    PRICE_RANGE = "price_range"
    FIBONACCI_RETRACE = "fibonacci_retrace"
    PRICE_LEVEL_INTERVAL = "price_level_interval"


class SendType(str, Enum):
    ON_TRIGGER = "on_trigger"
    INTERVAL = "interval"


@dataclass
class SignalMessageTemplate:
    template: str = (
        "股票 {stock_code}({stock_name}) 触发{signal_type}信号，"
        "当前价格: {price:.3f}，触发边界: {boundary}，"
        "区间[{lower:.3f}, {upper:.3f}]，时间: {time}"
    )

    def render(self, payload: Dict[str, Any]) -> str:
        safe_payload = dict(payload)
        safe_payload.setdefault("stock_code", "")
        safe_payload.setdefault("stock_name", "")
        safe_payload.setdefault("price", 0.0)
        safe_payload.setdefault("signal_type", "")
        safe_payload.setdefault("boundary", "")
        safe_payload.setdefault("lower", 0.0)
        safe_payload.setdefault("upper", 0.0)
        safe_payload.setdefault("zone_label", "")
        safe_payload.setdefault("fib_low", 0.0)
        safe_payload.setdefault("fib_high", 0.0)
        safe_payload.setdefault("level_382", 0.0)
        safe_payload.setdefault("level_500", 0.0)
        safe_payload.setdefault("level_618", 0.0)
        safe_payload.setdefault("target_price", 0.0)
        safe_payload.setdefault("mode", "")
        safe_payload.setdefault("mode_label", "")
        safe_payload.setdefault("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        return self.template.format(**safe_payload)


@dataclass
class SignalConfig:
    stock_code: str
    stock_name: str
    group_ids: List[int]
    signal_type: SingleType
    params: Dict[str, Any]
    message_template: SignalMessageTemplate = field(default_factory=SignalMessageTemplate)
    send_type: SendType = SendType.ON_TRIGGER
    send_interval_seconds: int = 0
    runtime_state: Dict[str, Any] = field(default_factory=dict)


class SingleBase(ABC):
    def __init__(self, config: SignalConfig):
        self.config = config
        self.last_sent_at: Optional[datetime] = None
        self.init()

    @abstractmethod
    def init(self) -> None:
        pass

    @abstractmethod
    def update(self, price: float, now: Optional[datetime] = None) -> List[str]:
        pass

    @abstractmethod
    def trigger(self, price: float) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def send_message(self, message: str, sender: Callable[[int, str], None]) -> None:
        pass

    @abstractmethod
    def get_runtime_state(self) -> Dict[str, Any]:
        pass


class PriceRangeSignal(SingleBase):
    def init(self) -> None:
        params = self.config.params or {}
        self.lower = float(params.get("lower"))
        self.upper = float(params.get("upper"))
        if self.lower >= self.upper:
            raise ValueError("参数错误：lower 必须小于 upper")
        state = self.config.runtime_state or {}
        self.sent_lower = bool(state.get("sent_lower", False))
        self.sent_upper = bool(state.get("sent_upper", False))
        self.last_notified_date = str(state.get("last_notified_date") or "").strip()
        self.last_price: Optional[float] = None

    def trigger(self, price: float) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        # 新规则：只要价格命中上下限区间 [lower, upper] 就触发通知
        if self.lower <= price <= self.upper:
            events.append({"boundary": "inside_range", "price": price})

        self.last_price = price
        return events

    def update(self, price: float, now: Optional[datetime] = None) -> List[str]:
        now = now or datetime.now()
        messages: List[str] = []
        events = self.trigger(price)
        today = now.strftime("%Y-%m-%d")
        if events and self.last_notified_date == today:
            # 同一规则同一天仅通知一次，次日可再次通知
            return messages
        for event in events:
            payload = {
                "stock_code": self.config.stock_code,
                "stock_name": self.config.stock_name,
                "price": event["price"],
                "signal_type": self.config.signal_type.value,
                "boundary": event["boundary"],
                "lower": self.lower,
                "upper": self.upper,
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            }
            messages.append(self.config.message_template.render(payload))
        if messages:
            self.last_notified_date = today
        return messages

    def send_message(self, message: str, sender: Callable[[int, str], None]) -> None:
        for gid in self.config.group_ids:
            sender(gid, message)

    def get_runtime_state(self) -> Dict[str, Any]:
        return {
            "sent_lower": self.sent_lower,
            "sent_upper": self.sent_upper,
            "last_notified_date": self.last_notified_date,
        }


# 黄金分割三类条件与 params.templates 中的键一致
FIB_ZONE_KEYS = ("normal_buy", "strong_support", "golden_pit")


class FibonacciRetraceSignal(SingleBase):
    def init(self) -> None:
        params = self.config.params or {}
        self.low = float(params.get("low"))
        self.high = float(params.get("high"))
        if self.low >= self.high:
            raise ValueError("参数错误：low 必须小于 high")
        diff = self.high - self.low
        self.level_382 = self.high - diff * 0.382
        self.level_500 = self.high - diff * 0.5
        self.level_618 = self.high - diff * 0.618
        raw_tpl = params.get("templates") if isinstance(params.get("templates"), dict) else {}
        self._zone_templates: Dict[str, str] = {}
        fallback = (self.config.message_template.template or "").strip()
        for key in FIB_ZONE_KEYS:
            t = raw_tpl.get(key)
            self._zone_templates[key] = (str(t).strip() if t is not None else "") or fallback
        state = self.config.runtime_state or {}
        self.last_notified_date = str(state.get("last_notified_date") or "").strip()
        self.last_price: Optional[float] = None

    def trigger(self, price: float) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        if price <= self.level_618:
            events.append({"zone": "golden_pit", "zone_label": "黄金坑", "price": price})
        elif price <= self.level_500:
            events.append({"zone": "strong_support", "zone_label": "强支撑", "price": price})
        elif price <= self.level_382:
            events.append({"zone": "normal_buy", "zone_label": "常规买点", "price": price})
        self.last_price = price
        return events

    def update(self, price: float, now: Optional[datetime] = None) -> List[str]:
        now = now or datetime.now()
        messages: List[str] = []
        events = self.trigger(price)
        today = now.strftime("%Y-%m-%d")
        if events and self.last_notified_date == today:
            return messages
        for event in events:
            zone = event["zone"]
            payload = {
                "stock_code": self.config.stock_code,
                "stock_name": self.config.stock_name,
                "price": event["price"],
                "signal_type": self.config.signal_type.value,
                "boundary": event["zone"],
                "zone_label": event["zone_label"],
                "lower": self.low,
                "upper": self.high,
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "fib_low": self.low,
                "fib_high": self.high,
                "level_382": self.level_382,
                "level_500": self.level_500,
                "level_618": self.level_618,
            }
            tmpl_text = self._zone_templates.get(zone) or self.config.message_template.template
            messages.append(SignalMessageTemplate(template=tmpl_text).render(payload))
        if messages:
            self.last_notified_date = today
        return messages

    def send_message(self, message: str, sender: Callable[[int, str], None]) -> None:
        for gid in self.config.group_ids:
            sender(gid, message)

    def get_runtime_state(self) -> Dict[str, Any]:
        return {
            "last_notified_date": self.last_notified_date,
        }


class PriceLevelIntervalSignal(SingleBase):
    """
    到价提醒（price_level_interval）：达到目标价条件且条件持续成立时，按 send_interval_seconds 节流发送消息。
    params: target_price, mode in (at_or_above, at_or_below)
    须 send_type=INTERVAL 且间隔 >= PRICE_LEVEL_INTERVAL_MIN_SECONDS。
    """

    MODES = ("at_or_above", "at_or_below")

    def init(self) -> None:
        params = self.config.params or {}
        raw_target = params.get("target_price")
        try:
            self.target_price = float(raw_target)
        except (TypeError, ValueError):
            raise ValueError("参数错误：target_price 必须为数值")
        if not math.isfinite(self.target_price):
            raise ValueError("参数错误：target_price 必须为有限数值")

        self.mode = str(params.get("mode") or "").strip()
        if self.mode not in self.MODES:
            raise ValueError(f"参数错误：mode 必须为 {self.MODES}")

        if self.config.send_type != SendType.INTERVAL:
            raise ValueError("到价提醒必须使用 send_type=interval（间隔发送）")

        self.interval_sec = int(self.config.send_interval_seconds or 0)
        if self.interval_sec < PRICE_LEVEL_INTERVAL_MIN_SECONDS:
            raise ValueError(
                f"参数错误：send_interval_seconds 须为不小于 {PRICE_LEVEL_INTERVAL_MIN_SECONDS} 的整数"
            )

        state = self.config.runtime_state or {}
        self.last_sent_at = None
        raw_ls = str(state.get("last_sent_at") or "").strip()
        if raw_ls:
            try:
                self.last_sent_at = datetime.fromisoformat(raw_ls.replace("Z", "+00:00"))
            except ValueError:
                self.last_sent_at = None

        lp = state.get("last_price")
        if lp is None or lp == "":
            self.last_price: Optional[float] = None
        else:
            try:
                self.last_price = float(lp)
            except (TypeError, ValueError):
                self.last_price = None

    def _condition(self, price: float) -> bool:
        if self.mode == "at_or_above":
            return price >= self.target_price
        return price <= self.target_price

    def trigger(self, price: float) -> List[Dict[str, Any]]:
        if self._condition(price):
            return [{"price": price}]
        return []

    def update(self, price: float, now: Optional[datetime] = None) -> List[str]:
        now = now or datetime.now()
        messages: List[str] = []
        self.last_price = price
        if not self._condition(price):
            return messages

        elapsed_ok = self.last_sent_at is None or (now - self.last_sent_at).total_seconds() >= float(
            self.interval_sec
        )
        if not elapsed_ok:
            return messages

        mode_label = "高于等于目标价" if self.mode == "at_or_above" else "低于等于目标价"
        payload = {
            "stock_code": self.config.stock_code,
            "stock_name": self.config.stock_name,
            "price": price,
            "signal_type": self.config.signal_type.value,
            "boundary": self.mode,
            "lower": self.target_price,
            "upper": self.target_price,
            "target_price": self.target_price,
            "mode": self.mode,
            "mode_label": mode_label,
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        messages.append(self.config.message_template.render(payload))
        self.last_sent_at = now
        return messages

    def send_message(self, message: str, sender: Callable[[int, str], None]) -> None:
        for gid in self.config.group_ids:
            sender(gid, message)

    def get_runtime_state(self) -> Dict[str, Any]:
        return {
            "last_sent_at": self.last_sent_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_sent_at else "",
            "last_price": self.last_price,
        }


def create_signal_instance(config: SignalConfig) -> SingleBase:
    if config.signal_type == SingleType.PRICE_RANGE:
        return PriceRangeSignal(config)
    if config.signal_type == SingleType.FIBONACCI_RETRACE:
        return FibonacciRetraceSignal(config)
    if config.signal_type == SingleType.PRICE_LEVEL_INTERVAL:
        return PriceLevelIntervalSignal(config)
    raise ValueError(f"不支持的信号类型: {config.signal_type}")


def validate_signal_rule_payload(
    *,
    signal_type: SingleType,
    params: Dict[str, Any],
    send_type: SendType,
    send_interval_seconds: int,
    message_template: Optional[str] = None,
) -> None:
    """校验规则能否成功实例化；不通过时抛出 ValueError。"""
    tpl_text = (message_template or "").strip() or SignalMessageTemplate().template
    cfg = SignalConfig(
        stock_code="__validate__",
        stock_name="",
        group_ids=[1],
        signal_type=signal_type,
        params=dict(params or {}),
        message_template=SignalMessageTemplate(template=tpl_text),
        send_type=send_type,
        send_interval_seconds=int(send_interval_seconds or 0),
        runtime_state={},
    )
    create_signal_instance(cfg)


class SingleManager:
    def __init__(self):
        self._signals: List[SingleBase] = []

    @staticmethod
    def get_floating_editor_schema() -> Dict[str, Any]:
        return {
            "entry": {
                "action": "open_floating_panel",
                "title": "股票信号编辑器",
                "description": "可从任意页面按钮打开，填写信号逻辑后保存到信号管理器。",
            },
            "fields": [
                {"name": "stock_code", "type": "text", "required": True},
                {"name": "stock_name", "type": "text", "required": False},
                {"name": "group_ids", "type": "list[int]", "required": True},
                {
                    "name": "signal_type",
                    "type": "enum",
                    "options": [
                        SingleType.PRICE_RANGE.value,
                        SingleType.FIBONACCI_RETRACE.value,
                        SingleType.PRICE_LEVEL_INTERVAL.value,
                    ],
                    "required": True,
                },
                {"name": "params.lower", "type": "number", "required": False},
                {"name": "params.upper", "type": "number", "required": False},
                {"name": "params.low", "type": "number", "required": False},
                {"name": "params.high", "type": "number", "required": False},
                {
                    "name": "params.target_price",
                    "type": "number",
                    "description": "到价提醒(price_level_interval) 目标价",
                    "required": False,
                },
                {
                    "name": "params.mode",
                    "type": "enum",
                    "options": ["at_or_above", "at_or_below"],
                    "description": "at_or_above: 价>=目标；at_or_below: 价<=目标",
                    "required": False,
                },
                {
                    "name": "params.templates",
                    "type": "object",
                    "description": "fibonacci_retrace 时三类条件各自消息模板键：normal_buy, strong_support, golden_pit",
                    "required": False,
                },
                {"name": "message_template", "type": "text", "required": False},
                {"name": "send_type", "type": "enum", "options": [SendType.ON_TRIGGER.value, SendType.INTERVAL.value], "required": True},
                {
                    "name": "send_interval_seconds",
                    "type": "int",
                    "description": f"到价提醒必填，且≥{PRICE_LEVEL_INTERVAL_MIN_SECONDS} 秒",
                    "required": False,
                },
            ],
        }

    def add_signal(self, config: SignalConfig) -> SingleBase:
        signal = create_signal_instance(config)
        self._signals.append(signal)
        return signal

    def update_price(self, stock_code: str, price: float, sender: Callable[[int, str], None]) -> List[str]:
        out: List[str] = []
        for signal in self._signals:
            if signal.config.stock_code != stock_code:
                continue
            messages = signal.update(price)
            for message in messages:
                signal.send_message(message, sender)
                out.append(message)
        return out

    def list_signals(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for signal in self._signals:
            rows.append(
                {
                    "stock_code": signal.config.stock_code,
                    "stock_name": signal.config.stock_name,
                    "group_ids": signal.config.group_ids,
                    "signal_type": signal.config.signal_type.value,
                    "params": signal.config.params,
                    "send_type": signal.config.send_type.value,
                    "send_interval_seconds": signal.config.send_interval_seconds,
                }
            )
        return rows
