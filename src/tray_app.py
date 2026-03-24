"""
tray_app.py — pystray 트레이 아이콘 및 winotify 알림
"""
from PIL import Image, ImageDraw
import pystray
from winotify import Notification, audio

APP_ID = "거북목 감지기"

# 아이콘 이미지 (프로세스 시작 시 1회 생성)
def _make_icon(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([4, 4, 60, 60], fill=color)
    return img

ICON_GRAY  = _make_icon("gray")
ICON_GREEN = _make_icon("green")
ICON_RED   = _make_icon("red")


def notify(title: str, msg: str):
    """Windows 토스트 알림 발송."""
    toast = Notification(app_id=APP_ID, title=title, msg=msg)
    toast.set_audio(audio.Default, loop=False)
    toast.show()


def build_tray(on_calibrate, on_quit) -> pystray.Icon:
    """트레이 아이콘 객체 생성. 메인 스레드에서 .run() 으로 시작해야 함."""
    return pystray.Icon(
        name="turtle_neck",
        icon=ICON_GRAY,
        title=f"{APP_ID} — 캘리브레이션 필요",
        menu=pystray.Menu(
            pystray.MenuItem("캘리브레이션", on_calibrate, default=True),
            pystray.MenuItem("종료", on_quit),
        ),
    )


def set_tray_state(icon: pystray.Icon, baseline: float | None, is_turtle: bool):
    """현재 상태에 따라 트레이 아이콘과 툴팁 갱신."""
    if baseline is None:
        icon.icon  = ICON_GRAY
        icon.title = f"{APP_ID} — 캘리브레이션 필요"
    elif is_turtle:
        icon.icon  = ICON_RED
        icon.title = "거북목 감지됨!"
    else:
        icon.icon  = ICON_GREEN
        icon.title = "자세 정상"
