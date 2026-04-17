"""
startup_window.py — 앱 시작 창 + 트레이 로그인 창

크로스플랫폼: tkinter + PIL.ImageTk (Windows / macOS 공통)

StartupWindow : 앱 시작 시 (카메라 피드 + 로그인 + 캘리브레이션)
AuthWindow    : 트레이 메뉴에서 로그인/회원가입 클릭 시 (컴팩트 폼)
"""
import platform
import queue
import threading
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk


# ── 공유: 회원가입 Toplevel 다이얼로그 ────────────────────────────────────────

def _open_signup_dialog(parent, auth_manager, on_success):
    """
    회원가입 Toplevel 다이얼로그.
    on_success(uid) — 가입 성공 시 호출 (tkinter after 스케줄로 안전하게 처리).
    StartupWindow / AuthWindow 양쪽에서 공용으로 사용한다.
    """
    dlg = tk.Toplevel(parent)
    dlg.title("회원가입")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.grab_set()

    tk.Label(dlg, text="이메일:").grid(row=0, column=0, padx=10, pady=10, sticky="e")
    email_var = tk.StringVar()
    tk.Entry(dlg, textvariable=email_var, width=22).grid(row=0, column=1, padx=4, pady=10)

    email_ok   = {"value": False}
    status_lbl = tk.Label(dlg, text="", width=30, anchor="w")
    status_lbl.grid(row=1, column=0, columnspan=3, padx=10)

    def on_check():
        email = email_var.get().strip()
        if not email:
            status_lbl.config(text="이메일을 입력해주세요.", fg="red")
            return
        status_lbl.config(text="확인 중...", fg="gray")
        dlg.update()

        def _chk():
            exists = auth_manager.check_email_exists(email)
            if exists is None:
                err = auth_manager.last_error or "UNKNOWN"
                dlg.after(0, lambda: status_lbl.config(text=f"오류: {err}", fg="orange"))
                email_ok["value"] = True
            elif exists:
                dlg.after(0, lambda: status_lbl.config(
                    text="이미 사용 중인 이메일입니다.", fg="red"
                ))
                email_ok["value"] = False
            else:
                dlg.after(0, lambda: status_lbl.config(
                    text="사용 가능한 이메일입니다.", fg="green"
                ))
                email_ok["value"] = True
            dlg.after(
                0,
                lambda: submit_btn.config(
                    state="normal" if email_ok["value"] else "disabled"
                ),
            )

        threading.Thread(target=_chk, daemon=True).start()

    tk.Button(dlg, text="중복확인", command=on_check).grid(row=0, column=2, padx=6, pady=10)

    tk.Label(dlg, text="비밀번호:").grid(row=2, column=0, padx=10, pady=6, sticky="e")
    pw_var = tk.StringVar()
    tk.Entry(dlg, textvariable=pw_var, show="*", width=22).grid(row=2, column=1, padx=4)

    tk.Label(dlg, text="비밀번호 확인:").grid(row=3, column=0, padx=10, pady=6, sticky="e")
    pw2_var = tk.StringVar()
    tk.Entry(dlg, textvariable=pw2_var, show="*", width=22).grid(row=3, column=1, padx=4)

    pw_status_lbl = tk.Label(dlg, text="", fg="red", width=30, anchor="w")
    pw_status_lbl.grid(row=4, column=0, columnspan=3, padx=10)

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

        def _sg():
            uid = auth_manager.signup(email_var.get().strip(), pw)
            if uid:
                dlg.after(0, dlg.destroy)
                dlg.after(0, lambda: on_success(uid))
            else:
                err = auth_manager.last_error or "알 수 없는 오류"
                dlg.after(0, lambda: pw_status_lbl.config(text=f"실패: {err}"))

        threading.Thread(target=_sg, daemon=True).start()

    submit_btn = tk.Button(dlg, text="가입", command=on_submit, state="disabled")
    submit_btn.grid(row=5, column=1, pady=10, sticky="e")
    tk.Button(dlg, text="취소", command=dlg.destroy).grid(row=5, column=2, padx=6, pady=10)
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)


# ── StartupWindow ─────────────────────────────────────────────────────────────

class StartupWindow:
    """
    앱 시작 시 표시되는 창.
    좌측: MediaPipe 랜드마크 오버레이 카메라 피드
    우측: 로그인/회원가입 폼 + 캘리브레이션 버튼

    on_done()      : 캘리브레이션 완료 또는 비로그인 시작 시 호출 → 트레이 모드 전환
    switch_logger  : 로그인/로그아웃 시 호출 (uid | None)
    """

    _FRAME_W = 420
    _FRAME_H = 315
    _POLL_MS = 33

    def __init__(self, detector, auth_manager, on_done, switch_logger):
        self.detector      = detector
        self.auth_manager  = auth_manager
        self.on_done       = on_done
        self.switch_logger = switch_logger

        self._frame_queue: queue.Queue = queue.Queue(maxsize=2)
        self._stop_cam = threading.Event()
        self._photo    = None

    # ── 카메라 스레드 ──────────────────────────────────────────────────────────

    def _cam_thread(self):
        cap = cv2.VideoCapture(0)
        while not self._stop_cam.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            score, rgb = self.detector.process_frame_visual(frame)
            if score is not None:
                self.detector.update(score)
            img = Image.fromarray(rgb).resize(
                (self._FRAME_W, self._FRAME_H), Image.BILINEAR
            )
            try:
                self._frame_queue.put_nowait(img)
            except queue.Full:
                pass
        cap.release()

    # ── tkinter 프레임 폴링 ───────────────────────────────────────────────────

    def _poll_frame(self):
        try:
            img = self._frame_queue.get_nowait()
            self._photo = ImageTk.PhotoImage(img)
            self._cam_label.configure(image=self._photo)
        except queue.Empty:
            pass
        if not self._stop_cam.is_set():
            self._root.after(self._POLL_MS, self._poll_frame)

    # ── 캘리브레이션 ──────────────────────────────────────────────────────────

    def _on_calibrate(self):
        baseline = self.detector.calibrate()
        if baseline is None:
            self._status_var.set("자세가 감지되지 않았습니다. 잠시 후 다시 시도하세요.")
            return
        self._status_var.set(f"캘리브레이션 완료!  기준값: {baseline:.3f}")
        self._root.after(800, self._finish)

    def _finish(self):
        self.on_done()
        self._root.destroy()

    # ── 로그인 / 로그아웃 ─────────────────────────────────────────────────────

    def _on_login(self):
        email = self._email_var.get().strip()
        pw    = self._pw_var.get()
        if not email or not pw:
            self._auth_msg.set("이메일과 비밀번호를 입력하세요.")
            return
        self._auth_msg.set("로그인 중...")
        self._root.update()

        def _do():
            uid = self.auth_manager.login(email, pw)
            if uid:
                self.switch_logger(uid)
                self._root.after(0, lambda: self._auth_msg.set("로그인 성공"))
                self._root.after(0, self._update_auth_ui)
            else:
                self._root.after(0, lambda: self._auth_msg.set(
                    "로그인 실패. 이메일/비밀번호를 확인하세요."
                ))

        threading.Thread(target=_do, daemon=True).start()

    def _on_logout(self):
        self.auth_manager.logout()
        self.switch_logger(None)
        self._auth_msg.set("로그아웃되었습니다.")
        self._update_auth_ui()

    # ── 회원가입 ──────────────────────────────────────────────────────────────

    def _on_signup(self):
        def _success(uid):
            self.switch_logger(uid)
            self._auth_msg.set(f"회원가입 성공: {self.auth_manager.get_email()}")
            self._update_auth_ui()

        _open_signup_dialog(self._root, self.auth_manager, _success)

    # ── 인증 상태 UI 전환 ─────────────────────────────────────────────────────

    def _update_auth_ui(self):
        if self.auth_manager.is_logged_in():
            self._login_frame.pack_forget()
            self._logged_frame.pack(fill="x", pady=4)
            self._logged_lbl.set(f"로그인: {self.auth_manager.get_email()}")
        else:
            self._logged_frame.pack_forget()
            self._login_frame.pack(fill="x", pady=4)

    # ── UI 빌드 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._root = tk.Tk()
        self._root.title("TurtleNeckDetector — 시작")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        if platform.system() == "Darwin":
            try:
                self._root.createcommand("tk::mac::Quit", self._on_close)
            except Exception:
                pass

        # 좌측: 카메라 피드
        left = tk.Frame(self._root, bg="black")
        left.pack(side="left")

        self._cam_label = tk.Label(left, bg="black",
                                   width=self._FRAME_W, height=self._FRAME_H)
        self._cam_label.pack()

        tk.Label(left, text="● MediaPipe 자세 감지 중",
                 bg="black", fg="#00e676", font=("Arial", 11)).pack(pady=6)

        # 우측: 인증 + 캘리브레이션
        right = tk.Frame(self._root, padx=20, pady=18)
        right.pack(side="right", fill="both", expand=True)

        tk.Label(right, text="TurtleNeckDetector",
                 font=("Arial", 14, "bold")).pack(pady=(0, 6))

        self._auth_msg = tk.StringVar(value="")
        tk.Label(right, textvariable=self._auth_msg,
                 fg="gray", wraplength=230).pack()

        # 비로그인 폼
        self._login_frame = tk.Frame(right)
        tk.Label(self._login_frame, text="이메일").grid(row=0, column=0, sticky="e", pady=5)
        self._email_var = tk.StringVar()
        tk.Entry(self._login_frame, textvariable=self._email_var, width=20).grid(
            row=0, column=1, padx=8)
        tk.Label(self._login_frame, text="비밀번호").grid(row=1, column=0, sticky="e", pady=5)
        self._pw_var = tk.StringVar()
        tk.Entry(self._login_frame, textvariable=self._pw_var, show="*", width=20).grid(
            row=1, column=1, padx=8)
        btn_row = tk.Frame(self._login_frame)
        btn_row.grid(row=2, column=0, columnspan=2, pady=8)
        tk.Button(btn_row, text="로그인",  width=9, command=self._on_login).pack(side="left", padx=4)
        tk.Button(btn_row, text="회원가입", width=9, command=self._on_signup).pack(side="left", padx=4)

        # 로그인 완료 상태
        self._logged_frame = tk.Frame(right)
        self._logged_lbl   = tk.StringVar()
        tk.Label(self._logged_frame, textvariable=self._logged_lbl, fg="green").pack(pady=6)
        tk.Button(self._logged_frame, text="로그아웃", command=self._on_logout).pack()

        self._update_auth_ui()

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=12)

        tk.Label(right, text="바른 자세로 앉은 후\n캘리브레이션을 시작하세요.",
                 justify="center").pack()

        self._status_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self._status_var,
                 fg="#1565c0", wraplength=230).pack(pady=4)

        tk.Button(right, text="캘리브레이션 시작",
                  font=("Arial", 11, "bold"), width=18,
                  command=self._on_calibrate).pack(pady=4)

        tk.Button(right, text="비로그인으로 시작",
                  fg="gray", command=self._finish).pack(pady=2)

    def _on_close(self):
        self._stop_cam.set()
        self._root.destroy()

    def run(self):
        self._build_ui()
        self._cam_ref = threading.Thread(target=self._cam_thread, daemon=True)
        self._cam_ref.start()
        self._root.after(self._POLL_MS, self._poll_frame)
        self._root.mainloop()
        self._stop_cam.set()
        self._cam_ref.join(timeout=2.0)


# ── CalibrationWindow ─────────────────────────────────────────────────────────

class CalibrationWindow:
    """
    트레이 '캘리브레이션' 클릭 시 표시되는 창.
    좌측: _live_frame_queue 에서 MediaPipe 프레임 수신
    우측: 캘리브레이션 재설정 UI

    show_in_main_thread() 를 메인 tkinter 스레드에서 직접 호출.
    """

    _FRAME_W = 420
    _FRAME_H = 315
    _POLL_MS  = 33

    def __init__(self, detector, live_frame_queue, start_visual, stop_visual, parent=None):
        self.detector          = detector
        self._live_frame_queue = live_frame_queue
        self._start_visual     = start_visual
        self._stop_visual      = stop_visual
        self._parent           = parent
        self._root             = None
        self._photo            = None

    def show_in_main_thread(self):
        """메인 tkinter 스레드에서 직접 호출. 비주얼 모드 활성 후 Toplevel 열기."""
        self._start_visual()
        self._build_ui()

    def _close(self):
        self._stop_visual()
        if self._root and self._root.winfo_exists():
            self._root.destroy()

    def _on_calibrate(self):
        baseline = self.detector.calibrate()
        if baseline is None:
            self._status_var.set("자세가 감지되지 않았습니다. 잠시 후 다시 시도하세요.")
        else:
            self._status_var.set(f"캘리브레이션 완료!  기준값: {baseline:.3f}")

    def _poll_frame(self):
        try:
            img = self._live_frame_queue.get_nowait()
            self._photo = ImageTk.PhotoImage(img)
            self._cam_label.configure(image=self._photo)
        except queue.Empty:
            pass
        if self._root and self._root.winfo_exists():
            self._root.after(self._POLL_MS, self._poll_frame)

    def _build_ui(self):
        if self._parent is not None:
            self._root = tk.Toplevel(self._parent)
            self._root.grab_set()
        else:
            self._root = tk.Tk()

        self._root.title("캘리브레이션 재설정")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)
        self._root.protocol("WM_DELETE_WINDOW", self._close)

        # 좌측: 카메라 피드
        left = tk.Frame(self._root, bg="black")
        left.pack(side="left")

        self._cam_label = tk.Label(left, bg="black",
                                   width=self._FRAME_W, height=self._FRAME_H)
        self._cam_label.pack()

        tk.Label(left, text="● MediaPipe 자세 감지 중",
                 bg="black", fg="#00e676", font=("Arial", 11)).pack(pady=6)

        # 우측: 캘리브레이션 UI
        right = tk.Frame(self._root, padx=20, pady=18)
        right.pack(side="right", fill="both", expand=True)

        tk.Label(right, text="캘리브레이션 재설정",
                 font=("Arial", 14, "bold")).pack(pady=(0, 12))

        tk.Label(right, text="바른 자세로 앉은 후\n캘리브레이션을 시작하세요.",
                 justify="center").pack()

        self._status_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self._status_var,
                 fg="#1565c0", wraplength=230).pack(pady=8)

        tk.Button(right, text="캘리브레이션 시작",
                  font=("Arial", 11, "bold"), width=18,
                  command=self._on_calibrate).pack(pady=8)

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=12)

        tk.Button(right, text="창 닫기",
                  fg="gray", command=self._close).pack(pady=4)

        self._root.after(self._POLL_MS, self._poll_frame)


# ── AuthWindow ────────────────────────────────────────────────────────────────

class AuthWindow:
    """
    트레이 메뉴의 '로그인' / '회원가입' 클릭 시 표시되는 컴팩트 창.

    show_in_main_thread(on_complete) 를 메인 tkinter 스레드에서 직접 호출.
    on_complete(uid | None) 은 창이 닫힐 때 호출됨.
    Toplevel 을 사용하므로 별도 mainloop() 불필요 — 부모 루프가 처리.
    """

    def __init__(self, auth_manager, parent=None):
        self.auth_manager = auth_manager
        self._parent      = parent
        self._root        = None
        self._on_complete = None

    def show_in_main_thread(self, on_complete):
        """메인 tkinter 스레드에서 직접 호출. Toplevel 을 열고 즉시 반환."""
        self._on_complete = on_complete
        self._build_ui()

    # ── 내부 종료 헬퍼 ────────────────────────────────────────────────────────

    def _close(self, uid=None):
        self._root.destroy()
        if self._on_complete:
            self._on_complete(uid)

    # ── 인증 동작 ─────────────────────────────────────────────────────────────

    def _on_login(self):
        email = self._email_var.get().strip()
        pw    = self._pw_var.get()
        if not email or not pw:
            self._msg.set("이메일과 비밀번호를 입력하세요.")
            return
        self._msg.set("로그인 중...")
        self._root.update()

        def _do():
            uid = self.auth_manager.login(email, pw)
            if uid:
                self._root.after(0, lambda: self._close(uid))
            else:
                self._root.after(0, lambda: self._msg.set(
                    "로그인 실패. 이메일/비밀번호를 확인하세요."
                ))

        threading.Thread(target=_do, daemon=True).start()

    def _on_signup(self):
        def _success(uid):
            self._close(uid)
        _open_signup_dialog(self._root, self.auth_manager, _success)

    # ── UI 빌드 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        if self._parent is not None:
            self._root = tk.Toplevel(self._parent)
            self._root.grab_set()
        else:
            self._root = tk.Tk()

        self._root.title("로그인 / 회원가입")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)
        self._root.protocol("WM_DELETE_WINDOW", lambda: self._close(None))

        if platform.system() == "Darwin":
            try:
                self._root.createcommand("tk::mac::Quit", lambda: self._close(None))
            except Exception:
                pass

        frame = tk.Frame(self._root, padx=24, pady=20)
        frame.pack()

        tk.Label(frame, text="TurtleNeckDetector",
                 font=("Arial", 13, "bold")).pack(pady=(0, 10))

        self._msg = tk.StringVar(value="")
        tk.Label(frame, textvariable=self._msg,
                 fg="gray", wraplength=250).pack()

        form = tk.Frame(frame)
        form.pack(pady=10)

        tk.Label(form, text="이메일").grid(row=0, column=0, sticky="e", pady=6)
        self._email_var = tk.StringVar()
        tk.Entry(form, textvariable=self._email_var, width=22).grid(
            row=0, column=1, padx=10)

        tk.Label(form, text="비밀번호").grid(row=1, column=0, sticky="e", pady=6)
        self._pw_var = tk.StringVar()
        tk.Entry(form, textvariable=self._pw_var, show="*", width=22).grid(
            row=1, column=1, padx=10)

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=10)

        btn_row = tk.Frame(frame)
        btn_row.pack()
        tk.Button(btn_row, text="로그인",  width=11, command=self._on_login).pack(
            side="left", padx=6)
        tk.Button(btn_row, text="회원가입", width=11, command=self._on_signup).pack(
            side="left", padx=6)

        tk.Button(frame, text="취소", fg="gray",
                  command=lambda: self._close(None)).pack(pady=(10, 0))
