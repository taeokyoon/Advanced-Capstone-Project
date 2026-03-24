"""
turtle_neck.py — 진입점 (Entry Point)
설정 로드 → 카메라 스레드 시작 → 트레이 아이콘 실행
"""
import cv2
import json
import os
import threading
import time

from src.detector import PostureDetector
from src.logger   import PostureLogger
from src.tray_app import build_tray, set_tray_state, notify

# ── 설정 로드 ─────────────────────────────────────────────────────────────────
_BASE        = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE, "config.json")

with open(_CONFIG_PATH, encoding="utf-8") as f:
    cfg = json.load(f)

SAVE_INTERVAL = cfg["save_interval_seconds"]
LOG_PATH      = os.path.join(_BASE, "data", "posture_log.jsonl")

# ── 전역 객체 ─────────────────────────────────────────────────────────────────
detector   = PostureDetector(cfg["delta_turtle"], cfg["delta_ok"])
logger     = PostureLogger(LOG_PATH)
stop_event = threading.Event()
tray_icon  = None   # 메인 스레드에서 할당 후 카메라 스레드에서 참조
last_save  = time.time()


# ── 카메라 루프 (백그라운드 스레드) ──────────────────────────────────────────
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
    threading.Thread(target=camera_loop, daemon=True).start()
    tray_icon.run()   # Windows: 반드시 메인 스레드에서 실행
