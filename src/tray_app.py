"""
tray_app.py — pystray 트레이 아이콘 관리

변경 사항 (2차):
  • build_tray() 에 auth_manager 추가 → 메뉴 항목 visible 람다로 동적 전환
  • 로그인/로그아웃/통계보기 콜백을 외부(turtle_neck.py)에서 주입
  • 알림은 src.utils.notifier 위임 유지
"""
from PIL import Image, ImageDraw
import pystray
from src.utils.notifier import send_notify

APP_ID = "거북목 감지기"

# ── 아이콘 이미지 ─────────────────────────────────────────────────────────────

def _make_icon(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([4, 4, 60, 60], fill=color)
    return img

ICON_GRAY  = _make_icon("gray")
ICON_GREEN = _make_icon("green")
ICON_RED   = _make_icon("red")

# ── 알림 ─────────────────────────────────────────────────────────────────────

def notify(title: str, msg: str):
    send_notify(title, msg)

# ── 트레이 아이콘 빌드 ────────────────────────────────────────────────────────

def build_tray(
    on_calibrate,
    on_stats,
    on_quit,
    on_open_gui, # 설정 화면 열기
    auth_manager,
    ) -> "pystray.Icon":
    """
    트레이 아이콘 빌드 (로그인/로그아웃/회원가입 제거 버전)
    """
    return pystray.Icon(
        "turtle_neck",
        icon=ICON_GRAY,
        title=f"{APP_ID}",
        menu=pystray.Menu(
            pystray.MenuItem("설정 화면 열기", on_open_gui, default=True),
            pystray.MenuItem("자세 기준 재설정(P)", on_calibrate),
            
            pystray.Menu.SEPARATOR,
            
            # 통계는 로그인이 필요한 기능이므로 visible 유지
            pystray.MenuItem("통계 보기", on_stats, visible=lambda item: auth_manager.is_logged_in()),
            pystray.MenuItem("종료", on_quit),
        ),
    )
# ── 트레이 상태 갱신 ──────────────────────────────────────────────────────────

def set_tray_state(icon: "pystray.Icon", baseline: float | None, is_turtle: bool):  # type: ignore[reportInvalidTypeForm]
    """상태에 따른 아이콘 및 툴팁 업데이트."""
    if icon is None:
        return

    if baseline is None:
        icon.icon  = ICON_GRAY
        icon.title = f"{APP_ID} — 캘리브레이션 필요"
    elif is_turtle:
        icon.icon  = ICON_RED
        icon.title = "거북목 감지됨!"
    else:
        icon.icon  = ICON_GREEN
        icon.title = "자세 정상"
