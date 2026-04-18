import platform

if platform.system() == "Windows":
    from .uiplug import *  # type: ignore
    from .uiautomation import *  # type: ignore
else:
    __all__ = []