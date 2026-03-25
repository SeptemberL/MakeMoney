import configparser
import os

class ConfigManager:
    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        self._config = configparser.ConfigParser()
        # 与项目根目录 config.Config 一致，读取仓库根 config.ini
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(root, 'config.ini')
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
        try:
            v = (self._config.get("NOTIFY", "channel", fallback="wechat") or "wechat").strip().lower()
        except Exception:
            v = "wechat"
        return v if v in ("wechat", "feishu") else "wechat"

    def get_feishu_webhook_url(self):
        try:
            u = self._config.get("FEISHU", "webhook_url", fallback="") or ""
        except Exception:
            return None
        u = u.strip()
        return u or None

    def get_feishu_timeout_seconds(self) -> float:
        t = self.get_int("FEISHU", "timeout_seconds")
        if t is None or t <= 0:
            return 10.0
        return float(t)

    def get_feishu_sign_secret(self):
        try:
            s = self._config.get("FEISHU", "sign", fallback="") or ""
        except Exception:
            return None
        s = s.strip()
        return s or None

    def get_notify_fallback_group_id(self):
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