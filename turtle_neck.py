import cv2
import mediapipe as mp
import sqlite3
import os
from collections import deque
from datetime import datetime
import time

# ── 초기화 ───────────────────────────────────────────────────────────────────
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise RuntimeError("카메라를 열 수 없습니다.")

mp_pose = mp.solutions.pose
mp_draw = mp.solutions.drawing_utils
pose = mp_pose.Pose(
    static_image_mode=False,
    model_complexity=1,
    enable_segmentation=False,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

# ── 파라미터 ─────────────────────────────────────────────────────────────────
# 캘리브레이션 기반 임계값 (기준 score에서 얼마나 벗어나면 거북목로 판정)
# 체형·카메라 위치에 무관하게 동작 → C키로 바른 자세 기준점 설정 후 사용
#
# 거북목일 때 score가 기준보다 낮아지는 환경 기준 (사용자 확인됨):
#   기준에서 DELTA_TURTLE 이상 떨어지면 → 거북목
#   기준에서 DELTA_OK 이내로 돌아오면  → 정상
DELTA_TURTLE     = 0.10  # 판정 시작: 기준보다 0.10 이상 낮아지면 거북목
DELTA_OK         = 0.05  # 해제 기준: 기준보다 0.05 이내로 돌아오면 정상
# 실측값 기준 (정상 0.60~0.66 / 거북목 0.45~0.55, 기준 편차 0.08~0.18)
DB_SAVE_INTERVAL = 60    # DB 저장 주기 (초). 60 = 분당 1개 → 9h 540개/일

scores: deque       = deque(maxlen=200)
last_eval: float    = time.time()
last_db_save: float = time.time()
is_turtle: bool     = False
baseline_score: float | None = None   # C키로 설정되는 기준값

# 분 단위 집계 카운터
minute_turtle_secs: int = 0
minute_total_secs:  int = 0

# ── SQLite 초기화 ─────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posture.db")
print(f"[DB] {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
conn.execute("""
    CREATE TABLE IF NOT EXISTS posture_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp      TEXT    NOT NULL,
        status         INTEGER NOT NULL,  -- 0: 정상, 1: 거북목 (구간 다수결)
        turtle_seconds INTEGER NOT NULL,  -- 구간 내 거북목으로 판정된 초 수
        total_seconds  INTEGER NOT NULL   -- 구간 내 유효 측정된 초 수
    )
""")
conn.commit()


def save_record(timestamp: str, status: int, turtle_seconds: int, total_seconds: int) -> None:
    try:
        conn.execute(
            "INSERT INTO posture_log (timestamp, status, turtle_seconds, total_seconds) VALUES (?, ?, ?, ?)",
            (timestamp, status, turtle_seconds, total_seconds),
        )
        conn.commit()
        print(f"[DB saved] {timestamp}  status={status}  {turtle_seconds}/{total_seconds}s")
    except Exception as e:
        print(f"[DB error] {e}")


def head_forward_score(nose_y: float, shoulder_y: float, shoulder_width: float) -> float:
    """
    어깨 대비 코의 수직 위치 비율 (어깨 너비로 거리 정규화).

    Y축은 이미지 픽셀에서 직접 읽으므로 Z(모델 추정)보다 훨씬 안정적.
    거북목 발생 시:
      - 코가 내려감  (nose_y 증가)  → shoulder_y - nose_y 감소
      - 어깨가 올라옴(shoulder_y 감소) → shoulder_y - nose_y 감소
    → score 감소 = 거북목 신호
    """
    return (shoulder_y - nose_y) / shoulder_width


while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        continue

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = pose.process(frame_rgb)

    score = None

    if result.pose_landmarks:
        lms = result.pose_landmarks.landmark
        mp_draw.draw_landmarks(frame, result.pose_landmarks, mp_pose.POSE_CONNECTIONS)

        NOSE = lms[mp_pose.PoseLandmark.NOSE.value]
        LS   = lms[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        RS   = lms[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]

        if min(LS.visibility, RS.visibility) > 0.5:
            shoulder_width = abs(LS.x - RS.x)
            if shoulder_width > 0.05:
                shoulder_y = (LS.y + RS.y) / 2
                score = head_forward_score(NOSE.y, shoulder_y, shoulder_width)

    now = time.time()

    if score is not None:
        scores.append((now, score))

    # 1초 슬라이딩 윈도우 유지
    while scores and now - scores[0][0] > 1.0:
        scores.popleft()

    # ── 1초에 한 번: 탐지 판정 + 분 단위 카운터 누적 ──────────────────────────
    if now - last_eval >= 1.0 and len(scores) >= 5:
        last_eval = now
        avg = sum(s for _, s in scores) / len(scores)

        if baseline_score is not None:
            deviation = avg - baseline_score  # 음수 = score 감소 = 이 환경에선 거북목

            if not is_turtle and deviation < -DELTA_TURTLE:
                is_turtle = True
            elif is_turtle and deviation > -DELTA_OK:
                is_turtle = False

            minute_total_secs += 1
            if is_turtle:
                minute_turtle_secs += 1

            print(f"[score] {avg:.3f}  deviation: {deviation:+.3f}  "
                  f"{'TURTLE' if is_turtle else 'OK'}"
                  f"  ({minute_turtle_secs}/{minute_total_secs}s)")

    # ── DB_SAVE_INTERVAL마다: DB 저장 + 카운터 초기화 ─────────────────────────
    if (baseline_score is not None
            and now - last_db_save >= DB_SAVE_INTERVAL
            and minute_total_secs > 0):
        last_db_save = now
        save_record(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            status=1 if minute_turtle_secs > minute_total_secs / 2 else 0,
            turtle_seconds=minute_turtle_secs,
            total_seconds=minute_total_secs,
        )
        minute_turtle_secs = 0
        minute_total_secs  = 0

    # ── HUD ────────────────────────────────────────────────────────────────
    if baseline_score is None:
        # 캘리브레이션 안내
        cv2.putText(frame, "바른 자세로 앉은 후 [C]키를 누르세요", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 200, 255), 2)
        if score is not None:
            cv2.putText(frame, f"현재 score: {score:.3f}", (20, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
    else:
        if score is not None:
            avg_now = sum(s for _, s in scores) / max(len(scores), 1)
            deviation = avg_now - baseline_score
            cv2.putText(frame, f"Score: {avg_now:.3f}  (base: {baseline_score:.3f})", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
            cv2.putText(frame, f"Deviation: {deviation:+.3f}  "
                               f"(turtle < {-DELTA_TURTLE:.2f})", (20, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2)
        else:
            cv2.putText(frame, "No pose detected", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 80, 80), 2)

        if is_turtle:
            cv2.putText(frame, "TURTLE NECK!", (20, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            cv2.putText(frame, "Fix your posture", (20, 175),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        else:
            cv2.putText(frame, "Posture: OK", (20, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 200, 0), 3)

    key = cv2.waitKey(1) & 0xFF
    if key == 27:  # ESC 종료
        break
    elif key in (ord('c'), ord('C')):
        if len(scores) >= 5:
            baseline_score = sum(s for _, s in scores) / len(scores)
            print(f"[calibrated] baseline = {baseline_score:.4f}")

    cv2.imshow("Turtle Neck Detector", frame)

pose.close()
cap.release()
cv2.destroyAllWindows()
conn.close()
