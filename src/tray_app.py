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
    on_login,
    on_logout,
    on_stats,
    on_quit,
    auth_manager,
) -> "pystray.Icon":  # type: ignore[reportInvalidTypeForm]
    """
    트레이 아이콘 객체 생성.

    메뉴 항목 가시성은 auth_manager.is_logged_in() 으로 런타임에 결정:
      비로그인: 캘리브레이션 | 로그인 | 종료
      로그인:   캘리브레이션 | 통계 보기 | 로그아웃 | 종료
    """
    return pystray.Icon(
        "turtle_neck",
        icon=ICON_GRAY,
        title=f"{APP_ID} — 캘리브레이션 필요",
        menu=pystray.Menu(
            pystray.MenuItem("캘리브레이션", on_calibrate, default=True),
            pystray.MenuItem(
                "통계 보기",
                on_stats,
                visible=lambda item: auth_manager.is_logged_in(),
            ),
            pystray.MenuItem(
                "로그인",
                on_login,
                visible=lambda item: not auth_manager.is_logged_in(),
            ),
            pystray.MenuItem(
                "로그아웃",
                on_logout,
                visible=lambda item: auth_manager.is_logged_in(),
            ),
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
