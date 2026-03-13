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
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        self._config.read(config_path)

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