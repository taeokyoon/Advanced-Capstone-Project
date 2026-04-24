"""
turtle_neck.py — 진입점 (크로스플랫폼 병합 버전)

Windows 아키텍처 베이스 + Mac UX 기능 통합:
  • AppState 단일 인스턴스로 공유 상태 관리 (Windows)
  • 마스코트 이미지 표시 (Mac)
  • 트레이 "설정 화면 열기" → SettingsWindow (Mac + Windows 통합)
  • 트레이 로그인/로그아웃 직접 지원 (Windows)
  • 구조화된 로깅 / .env 지원 (Windows)
  • 크로스플랫폼 알림: winotify(Windows) / plyer(macOS)

모드 분리:
  비로그인 → logs/anonymous/  에 저장, Firebase 업로드 없음
  로그인   → logs/{uid}/      에 저장, Firebase 업로드 활성
"""
import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import cv2
from dotenv import load_dotenv
from PIL import Image

from src.auth              import AuthManager
from src.detector          import PostureDetector
from src.log_config        import setup_logging
from src.logger            import PostureLogger
from src.tray_app          import build_tray, set_tray_state, notify
from src.utils.firebase_uploader import FirebaseUploader
from src.utils.upload_queue      import UploadQueue

# ── 경로 설정 (개발/exe 공통) ─────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_CONFIG_PATH       = os.path.join(_BASE, "config.json")
_FIREBASE_KEY_PATH = os.path.join(_BASE, "firebase_key.json")
_MASCOT_PATH       = os.path.join(_BASE, "assets", "mascot.png")

load_dotenv(os.path.join(_BASE, ".env"))

with open(_CONFIG_PATH, encoding="utf-8") as f:
    cfg = json.load(f)

SAVE_INTERVAL    = cfg["save_interval_seconds"]
APP_DATA_DIR     = os.path.join(_BASE, "logs")
NOTIFY_COOLDOWN  = 10.0   # 거북목 알림 재발송 최소 간격 (초)
POLL_INTERVAL_MS = 200    # tkinter 이벤트 큐 폴링 간격 (ms)

os.makedirs(APP_DATA_DIR, exist_ok=True)
setup_logging(APP_DATA_DIR)
log = logging.getLogger(__name__)

# ── AppState ──────────────────────────────────────────────────────────────────

class AppState:
    """앱 전체 공유 상태 — 전역 변수를 단일 인스턴스로 관리."""

    def __init__(self):
        self.auth_manager = AuthManager(
            session_path=os.path.join(APP_DATA_DIR, "session.json"),
            api_key=os.environ.get("FIREBASE_API_KEY", cfg.get("firebase_api_key", "")),
        )
        self.detector    = PostureDetector(cfg["delta_turtle"], cfg["delta_ok"])
        self.uploader    = FirebaseUploader(_FIREBASE_KEY_PATH)
        self.stop_event  = threading.Event()
        self.tray_icon   = None
        self.last_save   = time.time()
        self.tk_root:    tk.Tk | None = None
        self.tk_queue:   queue.Queue  = queue.Queue()
        self.show_visual: bool        = False
        self.frame_queue: queue.Queue = queue.Queue(maxsize=2)
        self.logger_lock  = threading.Lock()
        self.logger:       PostureLogger | None = None
        self.upload_queue: UploadQueue | None   = None

    def get_user_dir(self, uid: str | None) -> str:
        return os.path.join(APP_DATA_DIR, uid if uid else "anonymous")

    def switch_logger(self, uid: str | None) -> None:
        """로그인/로그아웃 시 logger 와 upload_queue 를 새 경로로 교체."""
        user_dir = self.get_user_dir(uid)
        with self.logger_lock:
            if self.logger is not None:
                self.logger.flush()
            self.logger = PostureLogger(user_dir)
            if uid:
                queue_path        = os.path.join(user_dir, "upload_queue.jsonl")
                self.upload_queue = UploadQueue(queue_path)
                self.upload_queue.retry_failed()
            else:
                self.upload_queue = None

# ── 통계 ──────────────────────────────────────────────────────────────────────

def _show_stats(app: AppState) -> None:
    uid = app.auth_manager.get_uid()
    if not uid:
        return

    log_path    = os.path.join(app.get_user_dir(uid), "posture_log.jsonl")
    today       = datetime.now().strftime("%Y-%m-%d")
    total_secs  = turtle_secs = count = 0

    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("timestamp", "").startswith(today):
                        total_secs  += rec.get("total_seconds", 0)
                        turtle_secs += rec.get("turtle_seconds", 0)
                        count       += 1
                except json.JSONDecodeError:
                    continue

    ratio = (turtle_secs / total_secs * 100) if total_secs > 0 else 0
    msg   = (
        f"계정: {app.auth_manager.get_email()}\n"
        f"오늘 기록: {count}건 ({total_secs // 60}분)\n"
        f"거북목 비율: {ratio:.1f}%\n"
        f"거북목 시간: {turtle_secs // 60}분"
    )
    app.tk_queue.put(
        lambda: messagebox.showinfo("오늘의 통계", msg, parent=app.tk_root)
    )

# ── 트레이 콜백 ───────────────────────────────────────────────────────────────

def _make_callbacks(app: AppState) -> dict:
    """트레이 메뉴 콜백 딕셔너리 생성. app 을 클로저로 캡처."""

    def on_open_gui(icon, item) -> None:
        """설정 화면 열기 — 마스코트 + 인증 + 캘리브레이션 창 (Mac 기능 통합)."""
        def _show():
            from src.startup_window import SettingsWindow
            SettingsWindow(
                detector=app.detector,
                auth_manager=app.auth_manager,
                live_frame_queue=app.frame_queue,
                start_visual=lambda: setattr(app, "show_visual", True),
                stop_visual=lambda: setattr(app, "show_visual", False),
                switch_logger=app.switch_logger,
                mascot_path=_MASCOT_PATH,
                on_auth_change=icon.update_menu,
                parent=app.tk_root,
            ).show_in_main_thread()
        app.tk_queue.put(_show)

    def on_login(icon, item) -> None:
        def _flow():
            done   = threading.Event()
            result = {"uid": None}

            def _show():
                from src.startup_window import AuthWindow
                def _complete(uid):
                    result["uid"] = uid
                    done.set()
                AuthWindow(app.auth_manager, parent=app.tk_root).show_in_main_thread(_complete)

            app.tk_queue.put(_show)
            done.wait(timeout=180)
            if result["uid"]:
                app.switch_logger(result["uid"])
                notify("로그인 성공", f"안녕하세요, {app.auth_manager.get_email()}")
                icon.update_menu()

        threading.Thread(target=_flow, daemon=True).start()

    def on_logout(icon, item) -> None:
        app.auth_manager.logout()
        app.switch_logger(None)
        notify("로그아웃", "비로그인 모드로 전환됩니다.")
        icon.update_menu()

    def on_stats(icon, item) -> None:
        threading.Thread(target=_show_stats, args=(app,), daemon=True).start()

    def on_quit(icon, item) -> None:
        app.stop_event.set()
        icon.stop()
        app.tk_queue.put(lambda: app.tk_root.quit() if app.tk_root else None)

    return dict(
        on_open_gui=on_open_gui,
        on_login=on_login,
        on_logout=on_logout,
        on_stats=on_stats,
        on_quit=on_quit,
    )

# ── 카메라 루프 (백그라운드 스레드 1) ─────────────────────────────────────────

def camera_loop(app: AppState) -> None:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        notify("오류", "카메라를 열 수 없습니다.")
        return

    last_notify_time = 0.0
    try:
        while not app.stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            if app.show_visual:
                score, rgb = app.detector.process_frame_visual(frame)
                try:
                    app.frame_queue.put_nowait(
                        Image.fromarray(rgb).resize((420, 315), Image.BILINEAR)
                    )
                except queue.Full:
                    pass
            else:
                score = app.detector.process_frame(frame)

            did_evaluate, changed = app.detector.update(score)

            if did_evaluate and app.detector.baseline_score is not None:
                with app.logger_lock:
                    if app.logger:
                        app.logger.tick(app.detector.is_turtle)
                if changed:
                    set_tray_state(
                        app.tray_icon,
                        app.detector.baseline_score,
                        app.detector.is_turtle,
                    )
                    if not app.detector.is_turtle:
                        last_notify_time = 0.0

                if app.detector.is_turtle and (time.time() - last_notify_time >= NOTIFY_COOLDOWN):
                    notify("거북목 감지!", "자세를 바로잡아 주세요.")
                    last_notify_time = time.time()

            now = time.time()
            if app.detector.baseline_score is not None and now - app.last_save >= SAVE_INTERVAL:
                app.last_save = now
                with app.logger_lock:
                    record = app.logger.flush_with_record() if app.logger else None
                if record and app.upload_queue is not None:
                    app.upload_queue.enqueue(record)
    finally:
        app.detector.close()
        cap.release()

# ── 업로드 루프 (백그라운드 스레드 2) ─────────────────────────────────────────

def upload_loop(app: AppState) -> None:
    while not app.stop_event.wait(60):
        uid = app.auth_manager.get_uid()
        if not uid or app.upload_queue is None:
            continue

        app.upload_queue.retry_failed()
        pending = app.upload_queue.get_pending()
        if not pending:
            continue

        user_dir    = app.get_user_dir(uid)
        doc_name    = datetime.now().strftime("%Y-%m-%d_%H")
        tmp_path    = os.path.join(user_dir, f"{doc_name}.jsonl")
        all_entries = app.upload_queue.get_all_records(hour_prefix=doc_name)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for record in all_entries:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            if app.uploader.upload_log_file(tmp_path, uid):
                app.upload_queue.mark_done([e["id"] for e in pending])
            else:
                app.upload_queue.mark_failed([e["id"] for e in pending])
        except Exception as e:
            log.error("upload_loop 오류: %s", e)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# ── 진입점 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from src.startup_window import StartupWindow

    app = AppState()
    app.auth_manager.load_session()
    app.switch_logger(app.auth_manager.get_uid())

    # Phase 1: 시작 창 (마스코트 + 카메라 피드 + 로그인/캘리브레이션)
    startup_done = threading.Event()
    StartupWindow(
        detector=app.detector,
        auth_manager=app.auth_manager,
        on_done=startup_done.set,
        switch_logger=app.switch_logger,
        mascot_path=_MASCOT_PATH,
    ).run()

    if not startup_done.is_set():
        raise SystemExit(0)

    # Phase 2: 트레이 모드
    callbacks     = _make_callbacks(app)
    app.tray_icon = build_tray(**callbacks, auth_manager=app.auth_manager)

    if app.detector.baseline_score is not None:
        set_tray_state(app.tray_icon, app.detector.baseline_score, app.detector.is_turtle)

    threading.Thread(target=camera_loop, args=(app,), daemon=True).start()
    threading.Thread(target=upload_loop, args=(app,), daemon=True).start()
    threading.Thread(target=app.tray_icon.run, daemon=True).start()

    notify("백그라운드 모드", "트레이 아이콘 → '설정 화면 열기'에서 언제든 재설정할 수 있습니다.")

    # 메인 스레드: 팝업 전용 tkinter 이벤트 루프
    app.tk_root = tk.Tk()
    app.tk_root.withdraw()

    def _poll() -> None:
        try:
            while True:
                app.tk_queue.get_nowait()()
        except queue.Empty:
            pass
        if not app.stop_event.is_set():
            app.tk_root.after(POLL_INTERVAL_MS, _poll)
        else:
            app.tk_root.quit()

    app.tk_root.after(POLL_INTERVAL_MS, _poll)
    app.tk_root.mainloop()
