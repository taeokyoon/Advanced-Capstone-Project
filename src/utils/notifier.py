import logging
import platform

log = logging.getLogger(__name__)

_APP_ID = "거북목 감지기"


def send_notify(title: str, msg: str) -> None:
    os_type = platform.system()
    if os_type == "Windows":
        from winotify import Notification, audio
        toast = Notification(app_id=_APP_ID, title=title, msg=msg)
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    elif os_type == "Darwin":
        from plyer import notification
        notification.notify(title=title, message=msg, app_name=_APP_ID)
    else:
        log.warning("알림 미지원 플랫폼 (%s) — %s: %s", os_type, title, msg)
