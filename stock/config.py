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

    def get_gemini_api_key(self):
        """
        Gemini API Key（仅服务端使用）。
        优先级：环境变量 GEMINI_API_KEY > GOOGLE_API_KEY > config.ini 的 [GEMINI] api_key（仅建议本地开发）
        """
        k = (os.getenv("GEMINI_API_KEY") or "").strip()
        if k:
            return k
        k = (os.getenv("GOOGLE_API_KEY") or "").strip()
        if k:
            return k
        try:
            k = (self._config.get("GEMINI", "api_key", fallback="") or "").strip()
        except Exception:
            k = ""
        return k or None

    def get_gemini_model(self) -> str:
        """默认 Gemini 模型标识；未配置回退为合理默认值。"""
        try:
            v = (self._config.get("GEMINI", "model", fallback="") or "").strip()
        except Exception:
            v = ""
        return v or "gemini-1.5-flash"

    def get_gemini_timeout_seconds(self) -> float:
        """Gemini 调用超时（秒），默认 60，非法则回退 60。"""
        try:
            v = (self._config.get("GEMINI", "timeout_seconds", fallback="") or "").strip()
        except Exception:
            v = ""
        if not v:
            return 60.0
        try:
            t = float(v)
        except ValueError:
            return 60.0
        return t if t > 0 else 60.0

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