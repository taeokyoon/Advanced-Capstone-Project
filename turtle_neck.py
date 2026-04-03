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
import sys
import threading
import time
import tkinter as tk
from tkinter import simpledialog, messagebox

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
stop_event = threading.Event()
tray_icon  = None
last_save  = time.time()

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

# ── 로그인 다이얼로그 (별도 스레드에서 tkinter 실행) ──────────────────────────

def _ask_credentials() -> tuple[str | None, str | None]:
    """tkinter 다이얼로그로 이메일/비밀번호 입력 받기 (blocking)."""
    result = {"email": None, "pw": None}
    done   = threading.Event()

    def _run():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        email = simpledialog.askstring("로그인", "이메일:", parent=root)
        if email:
            pw = simpledialog.askstring("로그인", "비밀번호:", show="*", parent=root)
            result["email"] = email
            result["pw"]    = pw
        root.destroy()
        done.set()

    threading.Thread(target=_run, daemon=True).start()
    done.wait(timeout=120)
    return result["email"], result["pw"]


def _show_stats():
    """통계 팝업 (로그인 사용자 전용, 현재 로컬 데이터 기반 간단 요약)."""
    uid = auth_manager.get_uid()
    if not uid:
        return

    user_dir  = _get_user_dir(uid)
    log_path  = os.path.join(user_dir, "posture_log.jsonl")

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
                    total_secs  += rec.get("total_seconds", 0)
                    turtle_secs += rec.get("turtle_seconds", 0)
                    count       += 1
                except json.JSONDecodeError:
                    continue

    ratio = (turtle_secs / total_secs * 100) if total_secs > 0 else 0
    msg   = (
        f"계정: {auth_manager.get_email()}\n"
        f"기록 수: {count}건\n"
        f"총 측정: {total_secs // 60}분\n"
        f"거북목 비율: {ratio:.1f}%"
    )

    def _show():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo("통계 요약", msg, parent=root)
        root.destroy()

    threading.Thread(target=_show, daemon=True).start()

# ── 트레이 메뉴 콜백 ──────────────────────────────────────────────────────────

def on_calibrate(icon, item):
    baseline = detector.calibrate()
    if baseline is not None:
        set_tray_state(icon, baseline, detector.is_turtle)
        notify("캘리브레이션 완료", f"기준값: {baseline:.3f}")
    else:
        notify("캘리브레이션 실패", "자세가 감지되지 않습니다. 잠시 후 재시도하세요.")


def on_login(icon, item):
    def _flow():
        email, pw = _ask_credentials()
        if not email or not pw:
            return
        uid = auth_manager.login(email, pw)
        if uid:
            _switch_logger(uid)
            notify("로그인 성공", f"안녕하세요, {auth_manager.get_email()}")
        else:
            notify("로그인 실패", "이메일/비밀번호를 확인하세요.")
    threading.Thread(target=_flow, daemon=True).start()


def on_logout(icon, item):
    auth_manager.logout()
    _switch_logger(None)
    notify("로그아웃", "비로그인 모드로 전환됩니다.")


def on_stats(icon, item):
    threading.Thread(target=_show_stats, daemon=True).start()


def on_quit(icon, item):
    stop_event.set()
    icon.stop()

# ── 카메라 루프 (백그라운드 스레드 1) ─────────────────────────────────────────

def camera_loop():
    global last_save

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        notify("오류", "카메라를 열 수 없습니다.")
        return

    while not stop_event.is_set():
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        score              = detector.process_frame(frame)
        evaluated, changed = detector.update(score)

        if evaluated and detector.baseline_score is not None:
            with _logger_lock:
                logger.tick(detector.is_turtle)
            if changed:
                set_tray_state(tray_icon, detector.baseline_score, detector.is_turtle)
                if detector.is_turtle:
                    notify("거북목 감지!", "자세를 바로잡아 주세요.")

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

        # 임시 파일에 pending 레코드를 모아 업로드
        user_dir  = _get_user_dir(uid)
        tmp_path  = os.path.join(user_dir, "_upload_tmp.jsonl")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for entry in pending:
                    f.write(json.dumps(entry["record"], ensure_ascii=False) + "\n")

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
    tray_icon = build_tray(
        on_calibrate=on_calibrate,
        on_login=on_login,
        on_logout=on_logout,
        on_stats=on_stats,
        on_quit=on_quit,
        auth_manager=auth_manager,
    )

    threading.Thread(target=camera_loop, daemon=True).start()
    threading.Thread(target=upload_loop, daemon=True).start()

    tray_icon.run()
