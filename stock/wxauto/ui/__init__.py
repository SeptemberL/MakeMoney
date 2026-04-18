import platform

if platform.system() == "Windows":
    from .base import BaseUIWnd, BaseUISubWnd  # type: ignore
    from .component import WeChatDialog  # type: ignore
    from . import (  # type: ignore
        browser,
        chatbox,
        component,
        main,
        moment,
        navigationbox,
        sessionbox,
    )
else:
    __all__ = []