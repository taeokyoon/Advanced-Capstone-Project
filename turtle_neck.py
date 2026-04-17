"""
turtle_neck.py — 진입점 (Entry Point)

설정 로드 → AuthManager 세션 복원 → 카메라 스레드 → 업로드 스레드 → 트레이 실행

모드 분리:
  비로그인 → logs/anonymous/  에 저장, Firebase 업로드 없음
  로그인   → logs/{uid}/      에 저장, Firebase 업로드 활성
"""
import cv2
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox
from PIL import Image

from src.auth              import AuthManager
from src.detector          import PostureDetector
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

with open(_CONFIG_PATH, encoding="utf-8") as f:
    cfg = json.load(f)

SAVE_INTERVAL = cfg["save_interval_seconds"]
APP_DATA_DIR  = os.path.join(_BASE, "logs")
os.makedirs(APP_DATA_DIR, exist_ok=True)

# ── 전역 객체 ─────────────────────────────────────────────────────────────────

auth_manager = AuthManager(
    session_path=os.path.join(APP_DATA_DIR, "session.json"),
    api_key=cfg.get("firebase_api_key", ""),
)

detector   = PostureDetector(cfg["delta_turtle"], cfg["delta_ok"])
uploader   = FirebaseUploader(_FIREBASE_KEY_PATH)
stop_event        = threading.Event()
tray_icon         = None
last_save         = time.time()
_tk_root:         tk.Tk | None  = None
_tk_auth_queue:   queue.Queue   = queue.Queue()
_show_visual:     bool          = False
_live_frame_queue: queue.Queue  = queue.Queue(maxsize=2)

# logger / upload_queue 는 로그인 상태에 따라 교체 가능 → 전역 참조
_logger_lock = threading.Lock()
logger: PostureLogger = None
upload_queue: UploadQueue | None = None


def _get_user_dir(uid: str | None) -> str:
    """uid 유무에 따라 logs 하위 폴더 경로 반환."""
    folder = uid if uid else "anonymous"
    return os.path.join(APP_DATA_DIR, folder)


def _switch_logger(uid: str | None):
    """로그인/로그아웃 시 logger 와 upload_queue 를 새 경로로 교체."""
    global logger, upload_queue
    user_dir = _get_user_dir(uid)
    with _logger_lock:
        if logger is not None:
            logger.flush()           # 기존 미전송 데이터 저장
        logger = PostureLogger(user_dir)
        if uid:
            queue_path = os.path.join(user_dir, "upload_queue.jsonl")
            upload_queue = UploadQueue(queue_path)
            # 앱 재시작 후 미전송 failed 항목을 pending 으로 복원
            upload_queue.retry_failed()
        else:
            upload_queue = None


# 앱 시작 시 초기화
auth_manager.load_session()
_switch_logger(auth_manager.get_uid())


def _start_visual():
    global _show_visual
    _show_visual = True


def _stop_visual():
    global _show_visual
    _show_visual = False

def _show_stats():
    """통계 팝업 — 로컬 posture_log.jsonl 에서 오늘 데이터 집계."""
    uid = auth_manager.get_uid()
    if not uid:
        return

    user_dir = _get_user_dir(uid)
    log_path = os.path.join(user_dir, "posture_log.jsonl")
    today    = datetime.now().strftime("%Y-%m-%d")

    total_secs  = 0
    turtle_secs = 0
    count       = 0

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
        f"계정: {auth_manager.get_email()}\n"
        f"오늘 기록: {count}건 ({total_secs // 60}분)\n"
        f"거북목 비율: {ratio:.1f}%\n"
        f"거북목 시간: {turtle_secs // 60}분"
    )

    def _show():
        messagebox.showinfo("오늘의 통계", msg, parent=_tk_root)

    _tk_auth_queue.put(_show)

# ── 트레이 메뉴 콜백 ──────────────────────────────────────────────────────────

def on_calibrate(icon, item):
    def _show():
        from src.startup_window import CalibrationWindow
        CalibrationWindow(
            detector=detector,
            live_frame_queue=_live_frame_queue,
            start_visual=_start_visual,
            stop_visual=_stop_visual,
            parent=_tk_root,
        ).show_in_main_thread()
    _tk_auth_queue.put(_show)


def on_login(icon, item):
    def _flow():
        done   = threading.Event()
        result = {"uid": None}

        def _show():
            from src.startup_window import AuthWindow
            def _complete(uid):
                result["uid"] = uid
                done.set()
            AuthWindow(auth_manager, parent=_tk_root).show_in_main_thread(_complete)

        _tk_auth_queue.put(_show)
        done.wait(timeout=180)
        if result["uid"]:
            _switch_logger(result["uid"])
            notify("로그인 성공", f"안녕하세요, {auth_manager.get_email()}")
            icon.update_menu()

    threading.Thread(target=_flow, daemon=True).start()


def on_logout(icon, item):
    auth_manager.logout()
    _switch_logger(None)
    notify("로그아웃", "비로그인 모드로 전환됩니다.")
    icon.update_menu()


def on_stats(icon, item):
    threading.Thread(target=_show_stats, daemon=True).start()


def on_quit(icon, item):
    stop_event.set()
    icon.stop()
    _tk_auth_queue.put(lambda: _tk_root.quit() if _tk_root else None)

# ── 카메라 루프 (백그라운드 스레드 1) ─────────────────────────────────────────

def camera_loop():
    global last_save

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        notify("오류", "카메라를 열 수 없습니다.")
        return 
    
    last_notify_time = 0.0 # 마지막 알림 발송시각

    while not stop_event.is_set():
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        if _show_visual:
            score, rgb = detector.process_frame_visual(frame)
            try:
                _live_frame_queue.put_nowait(
                    Image.fromarray(rgb).resize((420, 315), Image.BILINEAR)
                )
            except queue.Full:
                pass
        else:
            score = detector.process_frame(frame)

        evaluated, changed = detector.update(score)

        if evaluated and detector.baseline_score is not None:
            with _logger_lock:
                logger.tick(detector.is_turtle)
            if changed:
                set_tray_state(tray_icon, detector.baseline_score, detector.is_turtle)
                if not detector.is_turtle:
                    last_notify_time = 0.0  # 정상 복귀 시 타이머 리셋

            if detector.is_turtle and (time.time() - last_notify_time >= 10):
                notify("거북목 감지!", "자세를 바로잡아 주세요.")
                last_notify_time = time.time()

        now = time.time()
        if detector.baseline_score is not None and now - last_save >= SAVE_INTERVAL:
            last_save = now
            with _logger_lock:
                record = logger.flush_with_record()  # 레코드 반환 버전

            # 로그인 상태이면 업로드 큐에 추가
            if record and upload_queue is not None:
                upload_queue.enqueue(record)

    detector.close()
    cap.release()

# ── 업로드 루프 (백그라운드 스레드 2) ─────────────────────────────────────────

def upload_loop():
    upload_interval = 60

    while not stop_event.wait(upload_interval):
        uid = auth_manager.get_uid()
        if not uid or upload_queue is None:
            continue

        # 실패 항목 재시도
        upload_queue.retry_failed()

        pending = upload_queue.get_pending()
        if not pending:
            continue

        # 누적 데이터 전체를 Firestore에 반영 (덮어쓰기 방식이므로 done+pending 모두 포함)
        user_dir   = _get_user_dir(uid)
        doc_name   = datetime.now().strftime("%Y-%m-%d_%H")
        tmp_path   = os.path.join(user_dir, f"{doc_name}.jsonl")
        all_entries = upload_queue.get_all_records(hour_prefix=doc_name)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for record in all_entries:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            if uploader.upload_log_file(tmp_path, uid):
                done_ids = [e["id"] for e in pending]
                upload_queue.mark_done(done_ids)
            else:
                failed_ids = [e["id"] for e in pending]
                upload_queue.mark_failed(failed_ids)
        except Exception as e:
            print(f"[upload_loop] 오류: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# ── 진입점 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from src.startup_window import StartupWindow

    # ── Phase 1: 시작 창 (카메라 피드 + 로그인/캘리브레이션) ──────────────────
    _startup_done = threading.Event()

    StartupWindow(
        detector=detector,
        auth_manager=auth_manager,
        on_done=_startup_done.set,
        switch_logger=_switch_logger,
    ).run()

    # 창을 X 버튼으로 닫으면 _startup_done 미설정 → 앱 종료
    if not _startup_done.is_set():
        raise SystemExit(0)

    # ── Phase 2: 트레이 모드 ──────────────────────────────────────────────────
    tray_icon = build_tray(
        on_calibrate=on_calibrate,
        on_login=on_login,
        on_logout=on_logout,
        on_stats=on_stats,
        on_quit=on_quit,
        auth_manager=auth_manager,
    )

    # 시작 창에서 이미 캘리브레이션 완료된 경우 트레이 아이콘 즉시 갱신
    if detector.baseline_score is not None:
        set_tray_state(tray_icon, detector.baseline_score, detector.is_turtle)

    threading.Thread(target=camera_loop, daemon=True).start()
    threading.Thread(target=upload_loop, daemon=True).start()
    threading.Thread(target=tray_icon.run, daemon=True).start()

    # 메인 스레드: 인증·알림 팝업 전용 tkinter 이벤트 루프
    _tk_root = tk.Tk()
    _tk_root.withdraw()

    def _poll_auth():
        try:
            while True:
                fn = _tk_auth_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        if not stop_event.is_set():
            _tk_root.after(200, _poll_auth)
        else:
            _tk_root.quit()

    _tk_root.after(200, _poll_auth)
    _tk_root.mainloop()
