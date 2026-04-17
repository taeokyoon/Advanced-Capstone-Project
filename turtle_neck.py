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
from datetime import datetime
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


def _ask_signup_credentials() -> tuple[str | None, str | None]:
    """이메일 중복확인 버튼이 포함된 회원가입 폼 (단일 창)."""
    result = {"email": None, "pw": None}
    done   = threading.Event()

    def _run():
        root = tk.Tk()
        root.title("회원가입")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        # ── 이메일 행 ──────────────────────────────────────────────
        tk.Label(root, text="이메일:").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        email_var = tk.StringVar()
        email_entry = tk.Entry(root, textvariable=email_var, width=24)
        email_entry.grid(row=0, column=1, padx=4, pady=10)

        email_ok = {"value": False}
        status_lbl = tk.Label(root, text="", width=28, anchor="w")
        status_lbl.grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 4))

        def on_check():
            email = email_var.get().strip()
            if not email:
                status_lbl.config(text="이메일을 입력해주세요.", fg="red")
                return
            status_lbl.config(text="확인 중...", fg="gray")
            root.update()
            exists = auth_manager.check_email_exists(email)
            if exists is None:
                err = auth_manager.last_error or "UNKNOWN"
                status_lbl.config(text=f"오류: {err}", fg="orange")
                email_ok["value"] = True
            elif exists:
                status_lbl.config(text="이미 사용 중인 이메일입니다.", fg="red")
                email_ok["value"] = False
            else:
                status_lbl.config(text="사용 가능한 이메일입니다.", fg="green")
                email_ok["value"] = True
            submit_btn.config(state="normal" if email_ok["value"] else "disabled")

        tk.Button(root, text="중복확인", command=on_check).grid(
            row=0, column=2, padx=6, pady=10
        )

        # ── 비밀번호 행 ────────────────────────────────────────────
        tk.Label(root, text="비밀번호:").grid(row=2, column=0, padx=10, pady=6, sticky="e")
        pw_var = tk.StringVar()
        tk.Entry(root, textvariable=pw_var, show="*", width=24).grid(row=2, column=1, padx=4)

        tk.Label(root, text="비밀번호 확인:").grid(row=3, column=0, padx=10, pady=6, sticky="e")
        pw2_var = tk.StringVar()
        tk.Entry(root, textvariable=pw2_var, show="*", width=24).grid(row=3, column=1, padx=4)

        pw_status_lbl = tk.Label(root, text="", fg="red", width=28, anchor="w")
        pw_status_lbl.grid(row=4, column=0, columnspan=3, padx=10, pady=(0, 4))

        # ── 버튼 행 ────────────────────────────────────────────────
        def on_submit():
            if not email_ok["value"]:
                status_lbl.config(text="이메일 중복확인을 먼저 해주세요.", fg="red")
                return
            pw  = pw_var.get()
            pw2 = pw2_var.get()
            if not pw:
                pw_status_lbl.config(text="비밀번호를 입력해주세요.")
                return
            if pw != pw2:
                pw_status_lbl.config(text="비밀번호가 일치하지 않습니다.")
                return
            result["email"] = email_var.get().strip()
            result["pw"]    = pw
            root.destroy()

        def on_cancel():
            root.destroy()

        submit_btn = tk.Button(root, text="가입", command=on_submit, state="disabled")
        submit_btn.grid(row=5, column=1, pady=10, sticky="e")
        tk.Button(root, text="취소", command=on_cancel).grid(row=5, column=2, padx=6, pady=10)

        root.protocol("WM_DELETE_WINDOW", on_cancel)
        root.mainloop()
        done.set()

    threading.Thread(target=_run, daemon=True).start()
    done.wait(timeout=120)
    return result["email"], result["pw"]


def _show_stats():
    """통계 팝업"""
    uid = auth_manager.get_uid()
    if not uid:
        def _show_login_warn():
            root = tk.Tk(); root.withdraw()
            root.attributes("-topmost", True)
            messagebox.showwarning("알림", "로그인이 필요한 서비스입니다.", parent=root)
            root.destroy()
        threading.Thread(target=_show_login_warn, daemon=True).start()
        return

    # 연결 상태 정밀 진단
    db_status = ""
    stats = None
    
    # FirebaseUploader가 정상적으로 초기화되었는지 확인
    if not uploader._available:
        db_status = "DB 연결 실패 (firebase_key.json 파일 없음!)"
    else:
        try:
            doc_ref = uploader.db.collection("day").document(uid)
            doc = doc_ref.get()
            if doc.exists:
                stats = doc.to_dict()
                db_status = "DB 연결 및 데이터 조회 성공!"
            else:
                db_status = "연결 성공 (하지만 day 컬렉션에 데이터가 없음)"
        except Exception as e:
            db_status = f"에러 발생: {e}"

    if stats:
        total_secs = stats.get("total_seconds", 0)
        turtle_secs = stats.get("turtle_seconds", 0)
    else:
        total_secs = 0
        turtle_secs = 0

    count = total_secs // 60 
    ratio = (turtle_secs / total_secs * 100) if total_secs > 0 else 0
    
    msg = (
        f"계정: {auth_manager.get_email()}\n"
        f"UID: {uid}\n"
        f"상태: {db_status}\n"
        f"---------------------------\n"
        f"누적 기록: 약 {count}건(분)\n"
        f"총 측정: {total_secs // 60}분\n"
        f"거북목 비율: {ratio:.1f}%\n"
        f"*(서버 동기화 데이터 기준)*"
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


_SIGNUP_ERROR_MAP = {
    "EMAIL_EXISTS":    "이미 사용 중인 이메일입니다.",
    "WEAK_PASSWORD":   "비밀번호는 6자 이상이어야 합니다.",
    "INVALID_EMAIL":   "올바른 이메일 형식이 아닙니다.",
    "NETWORK_ERROR":   "네트워크 오류가 발생했습니다. 인터넷 연결을 확인하세요.",
}

def _show_signup_error(msg: str):
    def _run():
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("회원가입 실패", msg, parent=root)
        root.destroy()
    threading.Thread(target=_run, daemon=True).start()


def on_signup(icon, item):
    def _flow():
        email, pw = _ask_signup_credentials()
        if not email or not pw:
            return
        uid = auth_manager.signup(email, pw)
        if uid:
            _switch_logger(uid)
            notify("회원가입 성공", f"환영합니다, {auth_manager.get_email()}")
        else:
            error = auth_manager.last_error or ""
            msg = next(
                (v for k, v in _SIGNUP_ERROR_MAP.items() if k in error),
                "회원가입에 실패했습니다. 다시 시도해주세요.",
            )
            _show_signup_error(msg)
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
    
    last_notify_time = 0.0 # 마지막 알림 발송시각

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
    tray_icon = build_tray(
        on_calibrate=on_calibrate,
        on_login=on_login,
        on_signup=on_signup,
        on_logout=on_logout,
        on_stats=on_stats,
        on_quit=on_quit,
        auth_manager=auth_manager,
    )

    threading.Thread(target=camera_loop, daemon=True).start()
    threading.Thread(target=upload_loop, daemon=True).start()

    tray_icon.run()

