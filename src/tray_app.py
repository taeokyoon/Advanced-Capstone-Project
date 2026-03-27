"""
tray_app.py — pystray 트레이 아이콘 관리
(알림 로직은 src.utils.notifier로 위임)
"""
from PIL import Image, ImageDraw
import pystray
# winotify 임포트를 삭제하고, 우리가 만든 공통 알림 함수를 가져옵니다.
from src.utils.notifier import send_notify

APP_ID = "거북목 감지기"

# 아이콘 이미지 생성 로직 (기존과 동일)
def _make_icon(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([4, 4, 60, 60], fill=color)
    return img

ICON_GRAY  = _make_icon("gray")
ICON_GREEN = _make_icon("green")
ICON_RED   = _make_icon("red")

def notify(title: str, msg: str):
    """
    이제 직접 알림을 쏘지 않고, notifier 모듈에 부탁합니다.
    여기서 호출하면 notifier.py 내부에서 OS를 체크해 알아서 실행됩니다.
    """
    send_notify(title, msg)

def build_tray(on_calibrate, on_quit) -> pystray.Icon:
    """트레이 아이콘 객체 생성."""
    return pystray.Icon(
        "turtle_neck", # 첫 번째 인자는 name입니다.
        icon=ICON_GRAY,
        title=f"{APP_ID} — 캘리브레이션 필요",
        menu=pystray.Menu(
            pystray.MenuItem("캘리브레이션", on_calibrate, default=True),
            pystray.MenuItem("종료", on_quit),
        ),
    )

def set_tray_state(icon: pystray.Icon, baseline: float | None, is_turtle: bool):
    """상태에 따른 아이콘 및 툴팁 업데이트 (기존과 동일)"""
    if icon is None: return
    
    if baseline is None:
        icon.icon  = ICON_GRAY
        icon.title = f"{APP_ID} — 캘리브레이션 필요"
    elif is_turtle:
        icon.icon  = ICON_RED
        icon.title = "거북목 감지됨!"
    else:
        icon.icon  = ICON_GREEN
        icon.title = "자세 정상"