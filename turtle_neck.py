"""
turtle_neck.py — 진입점 (Entry Point)
설정 로드 → 카메라 스레드 시작 → 업로드 스레드 시작 → 트레이 아이콘 실행
"""
import cv2
import json
import os
import sys
import threading
import time

from src.detector import PostureDetector
from src.logger   import PostureLogger
from src.tray_app import build_tray, set_tray_state, notify
from src.utils.firebase_uploader import FirebaseUploader  # ── [추가됨] ──

# ── Mac / Windows 패키징을 위한 안전한 경로 설정 ─────────────────

# 1. 설정 파일(config.json) 경로 찾기
if getattr(sys, 'frozen', False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_CONFIG_PATH = os.path.join(_BASE, "config.json")

with open(_CONFIG_PATH, encoding="utf-8") as f:
    cfg = json.load(f)

SAVE_INTERVAL = cfg["save_interval_seconds"]

# 2. [수정됨] 프로젝트 폴더 내부로 로그 경로 지정 및 Firebase 키 경로 세팅
APP_DATA_DIR = os.path.join(_BASE, "logs") 
FIREBASE_KEY_PATH = os.path.join(_BASE, "firebase_key.json")

if not os.path.exists(APP_DATA_DIR):
    os.makedirs(APP_DATA_DIR)

LOG_PATH = os.path.join(APP_DATA_DIR, "posture_log.jsonl")

# ───────────────────────────────────────────────────────────────────────

# ── 전역 객체 ─────────────────────────────────────────────────────────────────
detector   = PostureDetector(cfg["delta_turtle"], cfg["delta_ok"])
logger     = PostureLogger(LOG_PATH)
uploader   = FirebaseUploader(FIREBASE_KEY_PATH)  # ── [추가됨] ──
stop_event = threading.Event()
tray_icon  = None   
last_save  = time.time()


# ── 카메라 루프 (백그라운드 스레드 1) ──────────────────────────────────────────
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
            logger.tick(detector.is_turtle)
            if changed:
                set_tray_state(tray_icon, detector.baseline_score, detector.is_turtle)
                if detector.is_turtle:
                    notify("거북목 감지!", "자세를 바로잡아 주세요.")

        now = time.time()
        if detector.baseline_score is not None and now - last_save >= SAVE_INTERVAL:
            last_save = now
            logger.flush()

    detector.close()
    cap.release()


# ── [새로 추가됨] 업로드 루프 (백그라운드 스레드 2) ──────────────────────────
def upload_loop():
    upload_interval = 60 

    while not stop_event.wait(upload_interval):
        files = [f for f in os.listdir(APP_DATA_DIR) if f.endswith('.jsonl')]
        
        for file_name in files:
            file_path = os.path.join(APP_DATA_DIR, file_name)
            
            if os.path.getsize(file_path) == 0:
                continue
                
            # Firebase 업로드 성공 시
            if uploader.upload_log_file(file_path):
                try:
                    # [수정됨] 이름 변경(rename) 대신 아예 삭제(remove)해 버립니다!
                    os.remove(file_path)
                    print(f"[정리] 업로드 완료된 파일 삭제됨: {file_name}")
                except Exception as e:
                    print(f"[경고] 파일 삭제 실패: {e}")


# ── 트레이 메뉴 액션 ─────────────────────────────────────────────────────────
def on_calibrate(icon, item):
    baseline = detector.calibrate()
    if baseline is not None:
        set_tray_state(icon, baseline, detector.is_turtle)
        notify("캘리브레이션 완료", f"기준값: {baseline:.3f}")
    else:
        notify("캘리브레이션 실패", "자세가 감지되지 않습니다. 잠시 후 재시도하세요.")

def on_quit(icon, item):
    stop_event.set()
    icon.stop()


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tray_icon = build_tray(on_calibrate, on_quit)
    
    # 1. 카메라 스레드 시작
    threading.Thread(target=camera_loop, daemon=True).start()
    
    # 2. Firebase 업로드 스레드 시작
    threading.Thread(target=upload_loop, daemon=True).start()
    
    # 3. 트레이 GUI 실행
    tray_icon.run()