# 수정사항
# 1초동안의 평균/비율로 판단
# 1초의 score만 모아서 판단. FPS 30기준 최근 30개 정도
# 매 프레임마다 화면은 갱신하지만 경고 ON/OFF는 1초에 한번씩 수행

import cv2
import mediapipe as mp

from collections import deque
import time

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    raise RuntimeError("카메라 에러")

mp_pose = mp.solutions.pose
mp_draw = mp.solutions.drawing_utils

pose = mp_pose.Pose (
    static_image_mode = False,
    model_complexity = 1,
    enable_segmentation = False,
    min_detection_confidence = 0.5,
    min_tracking_confidence = 0.5,
)

TH = 0.66

# 1초 score 저장이라 maxlen 넉넉하게
scores = deque(maxlen=200)

# 초마다 판정하기 위한 타이머
last_eval = time.time()
is_turtle = False

while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        continue
    
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = pose.process(frame_rgb)
    
    score = None
    
    if result.pose_landmarks:
        lms = result.pose_landmarks.landmark
        mp_draw.draw_landmarks(frame, result.pose_landmarks,
                               mp_pose.POSE_CONNECTIONS)
        LS = lms[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        RS = lms[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        LE = lms[mp_pose.PoseLandmark.LEFT_EAR.value]
        RE = lms[mp_pose.PoseLandmark.RIGHT_EAR.value]
        shoulder_width = abs(LS.x - RS.x)
        if shoulder_width > 1e-6:
            Sz = (LS.z + RS.z) / 2
            Ez = (LE.z + RE.z) / 2
            score = (Sz - Ez) / shoulder_width
    now = time.time()
    
    # score 를 시간과 함께 저장
    if score is not None:
        scores.append((now, score))
        
    # 최근 1초 데이터만 남김
    while scores and (now - scores[0][0] > 1.0):
        scores.popleft()
        
    if now - last_eval >= 1.0 and len(scores) >= 5:
        last_eval = now
        
        # 1초 평균 score
        avg = sum(s for _, s in scores) / len(scores)
        
        # 1초 중 TH 이상인 비율
        ratio = sum(1 for _, s in scores if s >= TH) / len(scores)
        
        # 판정규칙(예민함 줄이기) / 평균 TH 이상이고 초단 70% 이상이 TH 이상이면 거북목으로 판정
        is_turtle = (avg >= TH) and (ratio >= 0.7)
    
    if scores is None:
        cv2.putText(frame, "scores: (no pose)", (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        
    else:
        cv2.putText(frame, f"score: {score:.4f}", (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(frame, f"TH: {TH:.3f} (1s eval)", (20, 75),
           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

    if is_turtle:
        cv2.putText(frame, "TURTLE NECK!", (20, 130),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
        cv2.putText(frame, "Fix your posture", (20, 175),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    else:
        cv2.putText(frame, "Posture: OK", (20, 130),
        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 200, 0), 3)
        
    cv2.imshow("turtle-neck - 1 second decision", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == 27: # ESC 키로 종료
        break
    
pose.close()
cap.release()
cv2.destroyAllWindows()