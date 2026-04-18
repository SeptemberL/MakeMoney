import platform

if platform.system() == "Windows":
    from .win32 import *  # type: ignore
    from .lock import uilock  # type: ignore
    from . import tools  # type: ignore
else:
    __all__ = []