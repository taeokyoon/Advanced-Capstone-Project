"""
startup_window.py — 앱 시작 창 + 트레이 로그인 창 + 설정 창 (크로스플랫폼 병합 버전)

크로스플랫폼: customtkinter + CTkImage (Windows / macOS 공통)

StartupWindow  : 앱 시작 시 (마스코트 + 카메라 피드 + 로그인 + 캘리브레이션)
SettingsWindow : 트레이 "설정 화면 열기" 클릭 시 (마스코트 + 인증 + 캘리브레이션 + 카메라)
AuthWindow     : 트레이 "로그인" 클릭 시 (컴팩트 폼)
"""
import platform
import queue
import threading
import tkinter as tk
import customtkinter as ctk

import cv2
from PIL import Image

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# destroy() 전 after 콜백 일괄 취소 — customtkinter 내부 콜백 포함
def _cancel_all_after(root):
    try:
        for after_id in root.tk.call('after', 'info'):
            try:
                root.after_cancel(after_id)
            except Exception:
                pass
    except Exception:
        pass

# StringVar.__del__을 스레드 안전하게 패치
# CTkLabel(textvariable=) 연결 시 순환 참조 발생 → CPython 주기적 GC가
# 백그라운드 스레드에서 __del__을 호출하면 RuntimeError가 발생하므로 억제
_orig_variable_del = tk.Variable.__del__
def _safe_variable_del(self):
    try:
        _orig_variable_del(self)
    except RuntimeError:
        pass
tk.Variable.__del__ = _safe_variable_del


# ── 공유: 회원가입 CTkToplevel 다이얼로그 ────────────────────────────────────────



# ── 공유: 마스코트 이미지 로드 헬퍼 ──────────────────────────────────────────

def _load_mascot(parent_frame, mascot_path: str | None, size: int = 130) -> None:
    """마스코트 이미지를 parent_frame 에 붙인다. 실패 시 조용히 무시."""
    if not mascot_path:
        return
    try:
        img     = Image.open(mascot_path).resize((size, size), Image.Resampling.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
        lbl     = ctk.CTkLabel(parent_frame, image=ctk_img, text="")
        lbl.image = ctk_img
        lbl.pack(pady=(6, 2))
    except Exception:
        pass


# ── StartupWindow ─────────────────────────────────────────────────────────────

class StartupWindow:
    """
    앱 시작 시 표시되는 창.
    좌측: MediaPipe 랜드마크 오버레이 카메라 피드
    우측: 마스코트 + 로그인/회원가입 폼 + 캘리브레이션 버튼
    """

    _FRAME_W = 420
    _FRAME_H = 315
    _POLL_MS = 33

    def __init__(self, detector, auth_manager, on_done, switch_logger,
                 mascot_path: str | None = None):
        self.detector      = detector
        self.auth_manager  = auth_manager
        self.on_done       = on_done
        self.switch_logger = switch_logger
        self.mascot_path   = mascot_path

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
            self._photo = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(self._FRAME_W, self._FRAME_H),
            )
            self._cam_label.configure(image=self._photo)
        except queue.Empty:
            pass
        if not self._stop_cam.is_set() and self._root.winfo_exists():
            self._poll_id = self._root.after(self._POLL_MS, self._poll_frame)

    # ── 캘리브레이션 ──────────────────────────────────────────────────────────

    def _on_calibrate(self):
        baseline = self.detector.calibrate()
        if baseline is None:
            self._status_var.set("자세가 감지되지 않았습니다. 잠시 후 다시 시도하세요.")
            return
        self._status_var.set(f"캘리브레이션 완료!  기준값: {baseline:.3f}")
        self._root.after(800, self._finish)

    def _finish(self):
        self._auth_msg = None
        self._stop_cam.set()
        _cancel_all_after(self._root)
        self.on_done()
        self._root.withdraw()  # destroy 대신 숨김 — 트레이 모드가 같은 CTk 루트를 재사용
        self._root.quit()      # mainloop 종료

    # ── 로그인 / 로그아웃 ─────────────────────────────────────────────────────


    def _on_google_login(self):
        self._auth_msg.set("인터넷 브라우저에서 구글 로그인을 진행해주세요...")
        self._root.update()

        def _do():
            uid = self.auth_manager.login_with_google()
            if self._stop_cam.is_set() or not self._root.winfo_exists():
                return
            if uid:
                self.switch_logger(uid)
                try:
                    self._root.after(0, lambda: self._auth_msg.set(f"구글 로그인 성공: {self.auth_manager.get_email()}"))
                    self._root.after(0, self._update_auth_ui)
                except Exception:
                    pass
            else:
                err = self.auth_manager.last_error or "알 수 없는 오류"
                try:
                    self._root.after(0, lambda: self._auth_msg.set(f"구글 로그인 실패: {err}"))
                except Exception:
                    pass
        threading.Thread(target=_do, daemon=True).start()

    def _on_logout(self):
        self.auth_manager.logout()
        self.switch_logger(None)
        self._auth_msg.set("로그아웃되었습니다.")
        self._update_auth_ui()

    def _on_logout(self):
        self.auth_manager.logout()
        self.switch_logger(None)
        self._auth_msg.set("로그아웃되었습니다.")
        self._update_auth_ui()

    # ── 회원가입 ──────────────────────────────────────────────────────────────


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
        self._root = ctk.CTk()
        self._root.title("Turtle Check — 시작")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        if platform.system() == "Darwin":
            try:
                self._root.createcommand("tk::mac::Quit", self._on_close)
            except Exception:
                pass

        # 좌측: 카메라 피드
        left = ctk.CTkFrame(self._root, fg_color="black", corner_radius=0)
        left.pack(side="left")

        self._cam_label = ctk.CTkLabel(left, text="", width=self._FRAME_W, height=self._FRAME_H)
        self._cam_label.pack()

        ctk.CTkLabel(left, text="● MediaPipe 자세 감지 중",
                     fg_color="transparent", text_color="#00e676",
                     font=ctk.CTkFont(size=11)).pack(pady=6)

        # 우측: 마스코트 + 인증 + 캘리브레이션
        right = ctk.CTkFrame(self._root, fg_color="transparent", corner_radius=0)
        right.pack(side="right", fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(right, text="Turtle Check",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(0, 4))

        _load_mascot(right, self.mascot_path, size=120)

        self._auth_msg = tk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self._auth_msg,
                     text_color="gray", wraplength=230).pack(pady=(4, 0))

        # 비로그인 폼
        self._login_frame = ctk.CTkFrame(right, fg_color="transparent")
        
        google_btn = ctk.CTkButton(self._login_frame, text="G 구글계정으로 시작", width=188,
            fg_color="#db4437", hover_color="#c23321", text_color="white",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_google_login)
        google_btn.pack(pady=15)

        # 로그인 완료 상태
        self._logged_frame = ctk.CTkFrame(right, fg_color="transparent")
        self._logged_lbl   = tk.StringVar()
        ctk.CTkLabel(self._logged_frame, textvariable=self._logged_lbl,
                     text_color="#4caf50").pack(pady=6)
        ctk.CTkButton(self._logged_frame, text="로그아웃", width=90,
                      fg_color="transparent", border_width=1,
                      command=self._on_logout).pack()

        self._update_auth_ui()

        ctk.CTkFrame(right, height=2, fg_color=("gray70", "gray30")).pack(fill="x", pady=10)

        ctk.CTkLabel(right, text="바른 자세로 앉은 후\n캘리브레이션을 시작하세요.",
                     justify="center").pack()

        self._status_var = tk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self._status_var,
                     text_color="#5c9fe8", wraplength=230).pack(pady=4)

        ctk.CTkButton(right, text="캘리브레이션 시작 (P)",
                      font=ctk.CTkFont(size=13, weight="bold"), width=200,
                      command=self._on_calibrate).pack(pady=4)

        self._root.bind("<p>", lambda e: self._on_calibrate())
        self._root.bind("<P>", lambda e: self._on_calibrate())

        ctk.CTkButton(right, text="비로그인으로 시작",
                      fg_color="transparent", text_color="gray",
                      hover_color=("gray70", "gray30"),
                      command=self._finish).pack(pady=2)

    def _on_close(self):
        self._stop_cam.set()
        _cancel_all_after(self._root)
        self._root.destroy()

    def run(self):
        self._build_ui()
        self._cam_ref = threading.Thread(target=self._cam_thread, daemon=True)
        self._cam_ref.start()
        self._poll_id = self._root.after(self._POLL_MS, self._poll_frame)
        self._root.mainloop()
        self._stop_cam.set()
        self._cam_ref.join(timeout=2.0)
        return self._root  # 트레이 모드에서 CTk 루트 재사용


# ── SettingsWindow ────────────────────────────────────────────────────────────

class SettingsWindow:
    """
    트레이 "설정 화면 열기" 클릭 시 표시되는 창.

    좌측: 메인 카메라 루프의 frame_queue 에서 MediaPipe 프레임 수신
    우측: 마스코트 + 인증 상태 + 로그인/로그아웃 + 캘리브레이션 버튼
    """

    _FRAME_W = 420
    _FRAME_H = 315
    _POLL_MS  = 33

    def __init__(self, detector, auth_manager, live_frame_queue,
                 start_visual, stop_visual, switch_logger,
                 mascot_path: str | None = None,
                 on_auth_change=None,
                 parent=None):
        self.detector          = detector
        self.auth_manager      = auth_manager
        self._live_frame_queue = live_frame_queue
        self._start_visual     = start_visual
        self._stop_visual      = stop_visual
        self.switch_logger     = switch_logger
        self.mascot_path       = mascot_path
        self._on_auth_change   = on_auth_change
        self._parent           = parent
        self._root             = None
        self._photo            = None

    def show_in_main_thread(self):
        """메인 tkinter 스레드에서 직접 호출. 비주얼 모드 활성 후 창 열기."""
        self._start_visual()
        try:
            self._build_ui()
        except Exception:
            self._stop_visual()
            raise

    def _close(self):
        self._stop_visual()
        self._auth_msg = None
        if self._root and self._root.winfo_exists():
            _cancel_all_after(self._root)
            self._root.destroy()

    # ── 캘리브레이션 ──────────────────────────────────────────────────────────

    def _on_calibrate(self):
        baseline = self.detector.calibrate()
        if baseline is None:
            self._status_var.set("자세가 감지되지 않았습니다. 잠시 후 다시 시도하세요.")
        else:
            self._status_var.set(f"캘리브레이션 완료!  기준값: {baseline:.3f}")

    # ── 인증 ──────────────────────────────────────────────────────────────────

        
    def _on_google_login(self):
        self._auth_msg.set("인터넷 브라우저에서 구글 로그인을 진행해주세요...")
        if self._root: self._root.update()
        
        def _do():
            uid = self.auth_manager.login_with_google()
            if uid:
                self.switch_logger(uid)
                if self._root:
                    self._root.after(0, lambda: self._auth_msg.set(f"구글 로그인 성공: {self.auth_manager.get_email()}"))
                    self._root.after(0, self._update_auth_ui)
                if self._on_auth_change: self._on_auth_change()
            else:
                err = self.auth_manager.last_error or "알 수 없는 오류"
                if self._root: self._root.after(0, lambda: self._auth_msg.set(f"구글 로그인 실패: {err}"))
        threading.Thread(target=_do, daemon=True).start()

    def _on_logout(self):
        self.auth_manager.logout()
        self.switch_logger(None)
        self._auth_msg.set("로그아웃되었습니다.")
        self._update_auth_ui()
        if self._on_auth_change:
            self._on_auth_change()

    def _update_auth_ui(self):
        if self.auth_manager.is_logged_in():
            self._login_frame.pack_forget()
            self._logged_frame.pack(fill="x", pady=4)
            self._logged_lbl.set(f"로그인: {self.auth_manager.get_email()}")
        else:
            self._logged_frame.pack_forget()
            self._login_frame.pack(fill="x", pady=4)

    # ── 프레임 폴링 ───────────────────────────────────────────────────────────

    def _poll_frame(self):
        try:
            img = self._live_frame_queue.get_nowait()
            self._photo = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(self._FRAME_W, self._FRAME_H),
            )
            self._cam_label.configure(image=self._photo)
        except queue.Empty:
            pass
        if self._root and self._root.winfo_exists():
            self._poll_id = self._root.after(self._POLL_MS, self._poll_frame)

    # ── UI 빌드 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        if self._parent is not None:
            self._root = ctk.CTkToplevel(self._parent)
        else:
            self._root = ctk.CTk()

        self._root.title("Turtle Check — 설정")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)
        self._root.protocol("WM_DELETE_WINDOW", self._close)

        if platform.system() == "Darwin":
            try:
                self._root.createcommand("tk::mac::Quit", self._close)
            except Exception:
                pass

        # 좌측: 카메라 피드
        left = ctk.CTkFrame(self._root, fg_color="black", corner_radius=0)
        left.pack(side="left")

        self._cam_label = ctk.CTkLabel(left, text="", width=self._FRAME_W, height=self._FRAME_H)
        self._cam_label.pack()

        ctk.CTkLabel(left, text="● MediaPipe 자세 감지 중",
                     fg_color="transparent", text_color="#00e676",
                     font=ctk.CTkFont(size=11)).pack(pady=6)

        # 우측: 마스코트 + 인증 + 캘리브레이션
        right = ctk.CTkFrame(self._root, fg_color="transparent", corner_radius=0)
        right.pack(side="right", fill="both", expand=True, padx=20, pady=14)

        ctk.CTkLabel(right, text="Turtle Check",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(0, 2))

        _load_mascot(right, self.mascot_path, size=100)

        self._auth_msg = tk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self._auth_msg,
                     text_color="gray", wraplength=230).pack(pady=(4, 0))

        # 비로그인 폼
        self._login_frame = ctk.CTkFrame(right, fg_color="transparent")
        google_btn = ctk.CTkButton(self._login_frame, text="G 구글계정으로 시작", width=188,
            fg_color="#db4437", hover_color="#c23321", text_color="white",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_google_login)
        google_btn.pack(pady=15)

        # 로그인 완료 상태
        self._logged_frame = ctk.CTkFrame(right, fg_color="transparent")
        self._logged_lbl   = tk.StringVar()
        ctk.CTkLabel(self._logged_frame, textvariable=self._logged_lbl,
                     text_color="#4caf50").pack(pady=4)
        ctk.CTkButton(self._logged_frame, text="로그아웃", width=85,
                      fg_color="transparent", border_width=1,
                      command=self._on_logout).pack()

        self._update_auth_ui()

        ctk.CTkFrame(right, height=2, fg_color=("gray70", "gray30")).pack(fill="x", pady=10)

        ctk.CTkLabel(right, text="바른 자세로 앉은 후\n캘리브레이션을 시작하세요.",
                     justify="center").pack()

        self._status_var = tk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self._status_var,
                     text_color="#5c9fe8", wraplength=230).pack(pady=4)

        ctk.CTkButton(right, text="캘리브레이션 시작 (P)",
                      font=ctk.CTkFont(size=13, weight="bold"), width=200,
                      command=self._on_calibrate).pack(pady=4)

        self._root.bind("<p>", lambda e: self._on_calibrate())
        self._root.bind("<P>", lambda e: self._on_calibrate())

        ctk.CTkFrame(right, height=2, fg_color=("gray70", "gray30")).pack(fill="x", pady=8)

        ctk.CTkButton(right, text="창 닫기",
                      fg_color="transparent", text_color="gray",
                      hover_color=("gray70", "gray30"),
                      command=self._close).pack(pady=2)

        self._poll_id = self._root.after(self._POLL_MS, self._poll_frame)


# ── AuthWindow ────────────────────────────────────────────────────────────────

class AuthWindow:
    """
    트레이 메뉴의 '로그인' 클릭 시 표시되는 컴팩트 창.

    show_in_main_thread(on_complete) 를 메인 tkinter 스레드에서 직접 호출.
    on_complete(uid | None) 은 창이 닫힐 때 호출됨.
    """

    def __init__(self, auth_manager, parent=None):
        self.auth_manager = auth_manager
        self._parent      = parent
        self._root        = None
        self._on_complete = None

    def show_in_main_thread(self, on_complete):
        """메인 tkinter 스레드에서 직접 호출. 창을 열고 즉시 반환."""
        self._on_complete = on_complete
        self._build_ui()

    def _close(self, uid=None):
        self._email_var = None
        self._pw_var = None
        self._msg = None
        self._root.destroy()
        if self._on_complete:
            self._on_complete(uid)

    def _on_google_login(self):
        self._msg.set("인터넷 브라우저에서 구글 로그인을 진행해주세요...")
        self._root.update()
        
        def _do():
            uid = self.auth_manager.login_with_google()
            if uid:
                self._root.after(0, lambda: self._close(uid))
            else:
                err = self.auth_manager.last_error or "알 수 없는 오류"
                self._root.after(0, lambda: self._msg.set(f"구글 로그인 실패: {err}"))
        threading.Thread(target=_do, daemon=True).start()

    def _build_ui(self):
        if self._parent is not None:
            self._root = ctk.CTkToplevel(self._parent)
        else:
            self._root = ctk.CTk()

        self._root.title("로그인 / 회원가입")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)
        self._root.protocol("WM_DELETE_WINDOW", lambda: self._close(None))

        if platform.system() == "Darwin":
            try:
                self._root.createcommand("tk::mac::Quit", lambda: self._close(None))
            except Exception:
                pass

        frame = ctk.CTkFrame(self._root, fg_color="transparent")
        frame.pack(padx=24, pady=20)

        ctk.CTkLabel(frame, text="Turtle Check",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(0, 10))

        self._msg = tk.StringVar(value="")
        ctk.CTkLabel(frame, textvariable=self._msg,
                     text_color="gray", wraplength=250).pack()

        form = ctk.CTkFrame(frame, fg_color="transparent")
        form.pack(pady=10)
        
        google_btn = ctk.CTkButton(frame, text="G 구글계정으로 시작", width=212,
            fg_color="#db4437", hover_color="#c23321", text_color="white",
            font=ctk.CTkFont(weight="bold"),
            command=self._on_google_login)
        google_btn.pack(pady=(0, 10))

        ctk.CTkButton(frame, text="취소",
                      fg_color="transparent", text_color="gray",
                      hover_color=("gray70", "gray30"),
                      command=lambda: self._close(None)).pack(pady=(10, 0))
