import configparser
import os

class Config:
    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        self._config = configparser.ConfigParser()
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        self._config.read(config_path, encoding='utf-8')

    def get(self, section, key):
        """获取配置值"""
        try:
            return self._config.get(section, key)
        except:
            return None

    def get_boolean(self, section, key):
        """获取布尔类型的配置值"""
        try:
            return self._config.getboolean(section, key)
        except:
            return None

    def get_int(self, section, key):
        """获取整数类型的配置值"""
        try:
            return self._config.getint(section, key)
        except:
            return None

    def get_notify_channel(self) -> str:
        """信号等通知通道：wechat（默认）或 feishu。非法值回退 wechat。"""
        try:
            v = (self._config.get("NOTIFY", "channel", fallback="wechat") or "wechat").strip().lower()
        except Exception:
            v = "wechat"
        return v if v in ("wechat", "feishu") else "wechat"

    def get_feishu_webhook_url(self):
        """飞书机器人 Webhook 完整 URL；未配置返回 None。"""
        try:
            u = self._config.get("FEISHU", "webhook_url", fallback="") or ""
        except Exception:
            return None
        u = u.strip()
        return u or None

    def get_feishu_timeout_seconds(self) -> float:
        """飞书 POST 超时（秒），默认 10，非法则 10。"""
        t = self.get_int("FEISHU", "timeout_seconds")
        if t is None or t <= 0:
            return 10.0
        return float(t)

    def get_feishu_sign_secret(self):
        """
        飞书机器人「签名校验」密钥（与控制台加签密钥一致）。
        配置项名为 sign；为空则不向 payload 添加 timestamp/sign。
        """
        try:
            s = self._config.get("FEISHU", "sign", fallback="") or ""
        except Exception:
            return None
        s = s.strip()
        return s or None

    def get_notify_fallback_group_id(self):
        """
        无 group_id 的汇总类通知（如批量更新）在微信通道下使用的群组 ID。
        未配置则回退为 [WX] TestImageSendTo 单聊名。
        """
        try:
            v = (self._config.get("NOTIFY", "fallback_group_id", fallback="") or "").strip()
        except Exception:
            return None
        if not v:
            return None
        try:
            return int(v)
        except ValueError:
            return None