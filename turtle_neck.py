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

import platform
import subprocess

import tkinter as tk
from tkinter import simpledialog, messagebox

from src.auth              import AuthManager
from src.detector          import PostureDetector
from src.logger            import PostureLogger
from src.tray_app          import build_tray, set_tray_state, notify
from src.utils.firebase_uploader import FirebaseUploader
from src.utils.upload_queue      import UploadQueue

from PIL import Image, ImageTk

# ── 경로 설정 (개발/exe 공통) ─────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_CONFIG_PATH       = os.path.join(_BASE, "config.json")
_FIREBASE_KEY_PATH = os.path.join(_BASE, "firebase_key.json")
_MASCOT_PATH       = os.path.join(_BASE, "assets", "mascot.png")

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

def _os_ask_string(title, prompt, password=False):
    """OS에 따라 적절한 입력창을 띄움"""
    if platform.system() == "Darwin":  # macOS
        hiding = "with hidden answer" if password else ""
        # AppleScript를 사용하여 시스템 다이얼로그 호출 (스레드 안전)
        ascript = f'display dialog "{prompt}" default answer "" {hiding} with title "{title}"'
        try:
            result = subprocess.check_output(['osascript', '-e', ascript]).decode('utf-8')
            if "text returned:" in result:
                return result.split("text returned:")[1].split(",")[0].strip()
        except str:
            return None
    else:  # Windows
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        res = simpledialog.askstring(title, prompt, show="*" if password else None)
        root.destroy()
        return res

def _os_messagebox(title, msg, type="info"):
    """OS에 따라 알림창 표시"""
    if platform.system() == "Darwin":
        ascript = f'display dialog "{msg}" with title "{title}" buttons {{"확인"}} default button "확인"'
        os.system(f"osascript -e '{ascript}'")
    else:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        if type == "error": messagebox.showerror(title, msg)
        else: messagebox.showinfo(title, msg)
        root.destroy()
        
# ── 로그인 다이얼로그 (별도 스레드에서 tkinter 실행) ──────────────────────────

def _ask_credentials() -> tuple[str | None, str | None]:
    """OS에 맞는 입력창으로 이메일/비밀번호 입력 받기"""
    email = _os_ask_string("로그인", "이메일:")
    if not email:
        return None, None
        
    pw = _os_ask_string("로그인", "비밀번호:", password=True)
    if not pw:
        return None, None
        
    return email, pw


def _ask_signup_credentials() -> tuple[str | None, str | None]:
    """OS에 따라 안전한 방식으로 회원가입 폼 제공"""
    
    # ── macOS (M1) 환경: 스레드 충돌 방지를 위해 osascript 순차 입력 사용 ──
    if platform.system() == "Darwin":
        email = _os_ask_string("회원가입", "사용할 이메일을 입력하세요:")
        if not email: return None, None

        # 중복 확인
        exists = auth_manager.check_email_exists(email)
        if exists is None:
            err = auth_manager.last_error or "UNKNOWN"
            _os_messagebox("오류", f"중복 확인 실패: {err}", type="error")
            return None, None
        elif exists:
            _os_messagebox("회원가입 실패", "이미 사용 중인 이메일입니다.", type="error")
            return None, None
            
        pw = _os_ask_string("회원가입", "비밀번호를 입력하세요:", password=True)
        if not pw: return None, None
        
        pw2 = _os_ask_string("회원가입", "비밀번호를 다시 한번 입력하세요:", password=True)
        if pw != pw2:
            _os_messagebox("회원가입 실패", "비밀번호가 일치하지 않습니다.", type="error")
            return None, None
            
        return email, pw

    # ── Windows 환경: 기존 작성하신 Tkinter 폼 사용 ──
    else:
        result = {"email": None, "pw": None}
        done   = threading.Event()

        def _run():
            # 윈도우 환경을 위해 Tkinter 임포트 추가 (NameError 해결)
            import tkinter as tk
            
            root = tk.Tk()
            root.title("회원가입")
            root.resizable(False, False)
            root.attributes("-topmost", True)

            # ── 이메일 행 ──
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

            tk.Button(root, text="중복확인", command=on_check).grid(row=0, column=2, padx=6, pady=10)

            # ── 비밀번호 행 ──
            tk.Label(root, text="비밀번호:").grid(row=2, column=0, padx=10, pady=6, sticky="e")
            pw_var = tk.StringVar()
            tk.Entry(root, textvariable=pw_var, show="*", width=24).grid(row=2, column=1, padx=4)

            tk.Label(root, text="비밀번호 확인:").grid(row=3, column=0, padx=10, pady=6, sticky="e")
            pw2_var = tk.StringVar()
            tk.Entry(root, textvariable=pw2_var, show="*", width=24).grid(row=3, column=1, padx=4)

            pw_status_lbl = tk.Label(root, text="", fg="red", width=28, anchor="w")
            pw_status_lbl.grid(row=4, column=0, columnspan=3, padx=10, pady=(0, 4))

            # ── 버튼 행 ──
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
    """통계 팝업 (로그인 사용자 전용)"""
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

    # ❌ 기존의 threading.Thread나 tk.Tk() 생성 코드를 모두 지우세요.
    # ✅ 대신 우리가 만든 안전한 OS 알림창 함수 딱 하나만 호출합니다.
    _os_messagebox("통계 요약", msg, type="info")

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
            icon.update_menu()  # 👈 추가: 메뉴 새로고침
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
            icon.update_menu()  # 👈 추가: 메뉴 새로고침
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
    icon.update_menu()  # 👈 추가: 메뉴 새로고침


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

# ── 1. 초기 런처(시작 화면) GUI 함수 추가 ────────────────────────────────────

def show_launcher_window():
    """앱 실행 시 가장 먼저 뜨는 메인 화면. 메인 스레드에서 실행됨."""
    root = tk.Tk()
    root.title("거북목 교정기 시작")
    root.geometry("300x500") 
    root.eval('tk::PlaceWindow . center')

    # 마스코트 이미지 처리
    try:
        img = Image.open(_MASCOT_PATH)
        img = img.resize((200, 200), Image.Resampling.LANCZOS)
        mascot_photo = ImageTk.PhotoImage(img)
        img_label = tk.Label(root, image=mascot_photo)
        img_label.image = mascot_photo 
        img_label.pack(anchor="w", pady=(20, 10), padx=20)   
    except Exception as e:
        print(f"이미지를 불러올 수 없습니다: {e}")
        tk.Label(root, text="🐢", font=("Helvetica", 60)).pack(pady=20)

    tk.Label(root, text="거북목 교정 프로그램", font=("Helvetica", 16, "bold")).pack(pady=5)

    # 상태 표시 라벨 설정
    status_var = tk.StringVar()
    is_logged_in = auth_manager.get_uid() is not None

    if is_logged_in:
        status_var.set(f"환영합니다, {auth_manager.get_email()}님!")
    else:
        status_var.set("비로그인 상태입니다. 로그인해주세요.")
    
    tk.Label(root, textvariable=status_var, fg="blue").pack(pady=5)

    # 💡 1. 나중에 보여줄 버튼과 숨길 프레임을 미리 선언합니다.
    def on_start_btn():
        root.destroy()
        
    start_btn = tk.Button(root, text="백그라운드 실행 (카메라 켜기)", width=25, command=on_start_btn, fg="red")
    login_frame = tk.Frame(root) # 로그인, 회원가입 버튼을 묶어둘 상자

    def show_start_button():
        """UI 전환: 로그인 프레임을 숨기고 시작 버튼을 나타냅니다."""
        login_frame.pack_forget() # 버튼 상자 숨기기
        start_btn.pack(pady=20)   # 시작 버튼 보이기

    # 💡 2. 로그인/회원가입 로직
    def on_login_btn():
        email, pw = _ask_credentials()
        if email and pw:
            uid = auth_manager.login(email, pw)
            if uid:
                _switch_logger(uid)
                status_var.set(f"환영합니다, {auth_manager.get_email()}님!")
                show_start_button() # 로그인 성공 시 버튼 전환!
            else:
                _os_messagebox("실패", "로그인에 실패했습니다.", type="error")

    def on_signup_btn():
        email, pw = _ask_signup_credentials()
        if email and pw:
            uid = auth_manager.signup(email, pw)
            if uid:
                _switch_logger(uid)
                status_var.set(f"환영합니다, {auth_manager.get_email()}님!")
                _os_messagebox("가입 성공", f"환영합니다!", type="info")
                show_start_button() # 회원가입 성공 시 버튼 전환!
            else:
                error = auth_manager.last_error or ""
                msg = next(
                    (v for k, v in _SIGNUP_ERROR_MAP.items() if k in error),
                    "회원가입에 실패했습니다. 다시 시도해주세요.",
                )
                _os_messagebox("회원가입 실패", msg, type="error")

    # 프레임(상자) 안에 로그인/회원가입 버튼 넣기
    tk.Button(login_frame, text="로그인", width=15, command=on_login_btn).pack(pady=5)
    tk.Button(login_frame, text="회원가입", width=15, command=on_signup_btn).pack(pady=5) 
    
    # 💡 3. 초기 상태 분기 처리
    # 앱을 처음 켰을 때, 이미 세션이 있어서 로그인된 상태라면 바로 '시작'을 보여주고,
    # 아니라면 '로그인' 프레임을 보여줍니다.
    if is_logged_in:
        start_btn.pack(pady=20)
    else:
        login_frame.pack(pady=10)

    # x 버튼을 눌러 창을 닫았을 때 앱이 완전히 종료되도록 처리
    def on_closing():
        import sys
        root.destroy()
        sys.exit() 
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

# ── 진입점 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 1. 앱 시작 시 인증 정보(세션) 먼저 로드
    auth_manager.load_session()
    _switch_logger(auth_manager.get_uid())

    # 2. 초기 런처 화면 띄우기 (카메라 켜기 전)
    # 이 함수가 끝날 때까지(시작 버튼을 누를 때까지) 아래 코드는 실행되지 않음.
    show_launcher_window()

    # --- 여기서부터는 '시작' 버튼을 누른 후의 동작 (백그라운드 진입) ---

    # 3. 백그라운드 스레드 가동
    threading.Thread(target=camera_loop, daemon=True).start()
    threading.Thread(target=upload_loop, daemon=True).start()

    # 4. 시스템 트레이 실행 (메인 스레드 점유)
    tray_icon = build_tray(
        on_calibrate=on_calibrate,
        on_login=on_login, # 트레이에서도 로그인할 수 있게 유지
        on_signup=on_signup,
        on_logout=on_logout,
        on_stats=on_stats,
        on_quit=on_quit,
        auth_manager=auth_manager,
    )
    
    notify("실행됨", "거북목 교정기가 백그라운드에서 실행됩니다.")
    tray_icon.run()
