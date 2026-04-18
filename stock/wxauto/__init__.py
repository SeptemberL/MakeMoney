import platform

if platform.system() == "Windows":
    from .wx import (  # type: ignore
        WeChat,
        Chat,
        LoginWnd,
        get_wx_clients,
        get_wx_logins,
    )
    from .param import WxParam  # type: ignore

    # pyinstaller
    from . import (  # type: ignore
        exceptions,
        languages,
        logger,
        param,
        msgs,
        ui,
        uia,
        utils,
    )

    import pythoncom  # type: ignore

    pythoncom.CoInitialize()
else:
    class _WxAutoUnavailable(RuntimeError):
        pass

    class WeChat:  # pragma: no cover
        def __init__(self, *args, **kwargs):
            raise _WxAutoUnavailable("wxauto 仅支持 Windows（当前系统不可用）")

    class Chat(WeChat):  # pragma: no cover
        pass

    class LoginWnd(WeChat):  # pragma: no cover
        pass

    class WxParam:  # pragma: no cover
        pass

    def get_wx_clients(*args, **kwargs):  # pragma: no cover
        return []

    def get_wx_logins(*args, **kwargs):  # pragma: no cover
        return []

__all__ = ["WeChat", "Chat", "WxParam", "get_wx_clients", "LoginWnd", "get_wx_logins"]