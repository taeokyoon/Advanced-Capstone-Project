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
import queue

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

image_queue = queue.Queue(maxsize=1)  # 카메라 스레드 -> 메인 스레드 이미지 전달용
calibration_done_event = threading.Event()  # 캘리브레이션 완료 신호
initial_calibration_complete = False  # 초기 캘리브레이션 완료 여부


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

def on_open_gui(icon, item):
    """트레이에서 '설정 화면 열기'를 눌렀을 때 호출됩니다."""
    # 1. 카메라 루프가 다시 UI(런처)로 이미지를 쏘도록 신호를 끕니다.
    calibration_done_event.clear() 
    
    # 2. 트레이 아이콘을 멈춥니다. 
    # 이렇게 하면 메인 스레드의 tray_icon.run()이 종료되면서 
    # while 루프의 처음(show_launcher_window)으로 돌아갑니다.
    icon.stop()

def show_calibration_window():
    global initial_calibration_complete
    root = tk.Tk()
    root.title("초기 캘리브레이션 - 자세를 바로 잡아주세요")
    
    # 너비를 800 -> 900으로 늘리고 높이를 550 -> 600으로 넉넉하게 조정
    root.geometry("950x600") 
    root.eval('tk::PlaceWindow . center')

    # 왼쪽 비디오 프레임
    video_frame = tk.Frame(root, width=640, height=480, bg="black")
    video_frame.pack(side="left", padx=20, pady=20)
    img_label = tk.Label(video_frame)
    img_label.pack()

    # 오른쪽 컨트롤 프레임 (너비 고정)
    control_frame = tk.Frame(root, width=250)
    control_frame.pack(side="right", fill="both", expand=True, padx=20, pady=20)

    tk.Label(control_frame, text="거북목 요정 AI", font=("Apple SD Gothic Neo", 20, "bold")).pack(pady=10)
    
    try:
        img = Image.open(_MASCOT_PATH)
        img = img.resize((150, 150), Image.Resampling.LANCZOS)
        mascot_photo = ImageTk.PhotoImage(img)
        mascot_label = tk.Label(control_frame, image=mascot_photo)
        mascot_label.image = mascot_photo 
        mascot_label.pack(pady=10)   
    except: pass

    tk.Label(control_frame, text="[단계 1]", fg="gray").pack()
    
    # 💡 ⭐️ wraplength를 추가하여 글자가 짤리지 않고 자동으로 줄바꿈되게 합니다.
    instruction_lbl = tk.Label(control_frame, 
                               text="정상 자세를 취한 뒤\n'자세 잡기 완료(P)'를 눌러주세요.", 
                               font=("Apple SD Gothic Neo", 12), 
                               fg="#333333", 
                               justify="center",
                               wraplength=220) # 프레임 너비에 맞춰 줄바꿈
    instruction_lbl.pack(pady=20)

    def do_calibration(event=None):
        baseline = detector.calibrate() 
        if baseline is not None:
            instruction_lbl.config(text="설정 완료!\n이제 백그라운드 실행을 눌러주세요.", fg="#007aff")
            p_btn.pack_forget()
            start_btn.pack(pady=20, fill="x")
            notify("성공", "기준값이 저장되었습니다.")
        else:
            # 💡 팁: 데이터가 쌓일 시간을 주어야 합니다. (최소 1초 이상 노출 후 클릭)
            notify("잠시만요!", "데이터를 수집 중입니다. 1초 뒤에 다시 눌러주세요.")

    p_btn = tk.Button(control_frame, 
                  text="자세 잡기 완료 (P)", 
                  font=("Apple SD Gothic Neo", 13, "bold"),
                  fg="black", 
                  bg="#007aff",        # 토스 블루 색상
                  activebackground="#005bb5", 
                  activeforeground="white",
                  relief="flat", 
                  cursor="hand2",
                  height=2,
                  command=do_calibration)
    p_btn.pack(pady=10, fill="x")
    
    start_btn = tk.Button(control_frame, text="백그라운드 실행", height=2,
                          command=lambda: [calibration_done_event.set(), root.destroy()], 
                          fg="red", font=("Apple SD Gothic Neo", 13, "bold"))

    root.bind('<p>', do_calibration)
    root.bind('<P>', do_calibration)

    def update_video_stream():
        # 💡 ⭐️ [수정] 창이 닫히는 중이거나 이미 닫혔다면 더 이상 타이머를 돌리지 않습니다.
        if not calibration_done_event.is_set():
            try:
                # 창이 존재하는지 확인
                if not root.winfo_exists():
                    return

                frame = image_queue.get_nowait()
                img = Image.fromarray(frame)
                imgtk = ImageTk.PhotoImage(image=img)
                
                # 라벨이 살아있는지도 확인
                if img_label.winfo_exists():
                    img_label.imgtk = imgtk
                    img_label.config(image=imgtk)
                
                # 15ms 후에 다시 실행 (창이 살아있을 때만)
                root.after(15, update_video_stream)
            except (queue.Empty, tk.TclError):
                # 데이터가 없거나 창이 닫히는 찰나에 호출되면 타이머를 멈춥니다.
                if root.winfo_exists():
                    root.after(15, update_video_stream)
            except Exception:
                pass

    root.after(10, update_video_stream)
    root.mainloop()
    
# ── 카메라 루프 (백그라운드 스레드 1) ─────────────────────────────────────────

def camera_loop():
    global last_save
    cap = cv2.VideoCapture(0)
    
    import mediapipe as mp
    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    drawing_spec = mp_drawing.DrawingSpec(thickness=1, circle_radius=1, color=(0, 255, 0))
    pose_instance = getattr(detector, '_pose', None)

    while not stop_event.is_set():
        ok, frame = cap.read()
        if not ok or frame is None: continue

        if not calibration_done_event.is_set():
            # 💡 ⭐️ [수정] 캘리브레이션 중에도 점수를 계산해서 detector에 넣어줘야 합니다!
            score = detector.process_frame(frame)
            detector.update(score) # scores 데크에 데이터가 쌓임

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if pose_instance:
                results = pose_instance.process(rgb_frame)
                if results.pose_landmarks:
                    mp_drawing.draw_landmarks(
                        rgb_frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS,
                        landmark_drawing_spec=drawing_spec, connection_drawing_spec=drawing_spec)
            
            rgb_frame = cv2.flip(rgb_frame, 1)
            rgb_frame = cv2.resize(rgb_frame, (640, 480))
            
            try:
                image_queue.put_nowait(rgb_frame)
            except queue.Full:
                try: image_queue.get_nowait()
                except: pass
                image_queue.put_nowait(rgb_frame)
        
        # [단계 2: 백그라운드 거북목 감지 모드]
        else:
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
                with _logger_lock: record = logger.flush_with_record()
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
    root = tk.Tk()
    root.title("거북목 교정기 - 로그인")
    root.geometry("350x550") # 로그아웃 버튼 공간을 위해 높이를 살짝 키웠습니다.
    root.configure(bg="#ffffff")
    root.eval('tk::PlaceWindow . center')

    # 🐢 마스코트
    try:
        img = Image.open(_MASCOT_PATH)
        img = img.resize((150, 150), Image.Resampling.LANCZOS)
        mascot_photo = ImageTk.PhotoImage(img)
        tk.Label(root, image=mascot_photo, bg="white").pack(pady=(30, 10))
    except: pass

    tk.Label(root, text="거북목 요정 AI", font=("Apple SD Gothic Neo", 22, "bold"), bg="white").pack()
    
    status_var = tk.StringVar()
    
    # 💡 UI 요소들을 미리 선언 (나중에 숨기기/보이기를 위해)
    login_frame = tk.Frame(root, bg="white")
    start_btn = tk.Button(root, text="자세 설정 시작하기", width=25, height=2, 
                          bg="#007aff", fg="black", font=("Apple SD Gothic Neo", 13, "bold"),
                          command=root.destroy)
    
    # 💡 [추가] 로그아웃 버튼 (텍스트 스타일로 깔끔하게)
    logout_btn = tk.Button(root, text="로그아웃", width=25, height=2, 
                          bg="#007aff", fg="black", font=("Apple SD Gothic Neo", 13, "bold"),
                           command=lambda: handle_logout())

    def update_ui_state():
        """로그인 상태에 따라 버튼 구성을 바꿉니다."""
        is_logged_in = auth_manager.get_uid() is not None
        if is_logged_in:
            status_var.set(f"환영합니다!\n{auth_manager.get_email()}님")
            login_frame.pack_forget()
            start_btn.pack(pady=(30, 5))
            logout_btn.pack(pady=5) # 로그인 됐을 때만 로그아웃 버튼 노출
        else:
            status_var.set("반가워요!\n로그인이 필요해요")
            start_btn.pack_forget()
            logout_btn.pack_forget()
            login_frame.pack(pady=20)

    # 💡 [추가] 로그아웃 로직
    def handle_logout():
        auth_manager.logout()
        _switch_logger(None)
        update_ui_state() # UI 새로고침

    # 로그인/회원가입 콜백
    def handle_login():
        email, pw = _ask_credentials()
        if email and pw and auth_manager.login(email, pw):
            _switch_logger(auth_manager.get_uid())
            update_ui_state()
            
    def handle_signup():
        email, pw = _ask_signup_credentials()
        if email and pw and auth_manager.signup(email, pw):
            _switch_logger(auth_manager.get_uid())
            update_ui_state()

    tk.Label(root, textvariable=status_var, font=("Apple SD Gothic Neo", 12), 
             fg="#6b7684", bg="white", justify="center").pack(pady=10)

    # 로그인 프레임 내부 버튼
    tk.Button(login_frame, text="로그인", width=20, height=2, command=handle_login).pack(pady=5)
    tk.Button(login_frame, text="회원가입", width=20, height=2, command=handle_signup).pack(pady=5)

    # 초기 상태 설정
    update_ui_state()

    def on_closing():
        root.destroy()
        sys.exit() 
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

# ── 진입점 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 1. 초기 세션 로드
    auth_manager.load_session()
    _switch_logger(auth_manager.get_uid())

    # 💡 [추가] 카메라와 업로드 스레드가 이미 시작되었는지 확인하는 깃발
    threads_started = False

    while not stop_event.is_set():
        
        # [단계 1] 로그인/런처 창 띄우기 (카메라 아직 안 켜짐 ❌)
        show_launcher_window()
        
        if stop_event.is_set(): 
            break

        # 💡 [수정] 로그인 성공 후 '자세 설정 시작하기'를 눌러 런처가 닫히면
        # 이때 비로소 카메라와 업로드 스레드를 실행합니다.
        if not threads_started:
            threading.Thread(target=camera_loop, daemon=True).start()
            threading.Thread(target=upload_loop, daemon=True).start()
            threads_started = True # 다시는 실행되지 않도록 깃발을 올림

        # [단계 2] 캘리브레이션 창 띄우기 (카메라 화면 나옴 ✅)
        calibration_done_event.clear() 
        show_calibration_window()
        
        if stop_event.is_set(): 
            break

        # [단계 3] 트레이 실행
        tray_icon = build_tray(
            on_calibrate=on_calibrate,
            on_stats=on_stats,
            on_quit=on_quit,
            on_open_gui=on_open_gui, # 이 함수가 로그인/로그아웃 창으로 보내주는 역할
            auth_manager=auth_manager,
        )
        
        # 아이콘 색상 즉시 업데이트
        set_tray_state(tray_icon, detector.baseline_score, detector.is_turtle)
        
        notify("백그라운드 모드", "트레이 메뉴에서 언제든 설정 화면을 다시 열 수 있습니다.")
        tray_icon.run()