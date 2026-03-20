# 임계치 (threshold)로 1차 판정
# 깜빡임 방지용으로 "연속 프레임 조건(간단 버전)" 추가

# 테스트결과 정상자세여도 turtle neck 판정이 뜸. 임계값을 다시 조정해야될 듯

import cv2
import mediapipe as mp

from collections import deque

cap = cv2.VideoCapture(0)

mp_pose = mp.solutions.pose
mp_draw = mp.solutions.drawing_utils

pose = mp_pose.Pose(
static_image_mode=False,
model_complexity=1,
enable_segmentation=False,
min_detection_confidence=0.5,
min_tracking_confidence=0.5,
)

# threshold (나의 측정 값 기준으로 시작점)
TH_ON = 0.62 # 거북목 판정 기준
TH_OFF = 0.59 # 정상 기준

# 최근 프레임 판정 기록 (1=거북목 후보, 0=정상)
history = deque(maxlen=10)
is_turtle = False

while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        print("프레임을 읽지 못함")
        continue
    
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    result = pose.process(frame_rgb)
    score = None
    
    if result.pose_landmarks:
        lms = result.pose_landmarks.landmark
        mp_draw.draw_landmarks(frame, result.pose_landmarks, mp_pose.POSE_CONNECTIONS)
        LS = lms[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        RS = lms[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        LE = lms[mp_pose.PoseLandmark.LEFT_EAR.value]
        RE = lms[mp_pose.PoseLandmark.RIGHT_EAR.value]
        shoulder_width = abs(LS.x - RS.x)
        if shoulder_width > 1e-6:
            Sz = (LS.z + RS.z) / 2
            Ez = (LE.z + RE.z) / 2
            score = (Sz - Ez) / shoulder_width
            
    # score가 있을 때만 판정에 반영
    
    if score is not None:
        turtle_candidate = 1 if score >= TH_ON else 0
        history.append(turtle_candidate)
        
        # 연속/다수결 기반 토글 (깜빡임 방지)
        count_turtle = sum(history)
        
        if not is_turtle:
            # 아직 정상 상태일때: history에서 거북목 후보가 충분히 많으면 켬
            if count_turtle >= 7:
                is_turtle = True
        else:
            # 이미 거북목 경고 상태일때: score가 충분히 내려가면 끈다
            if score <= TH_OFF and count_turtle <= 3:
                is_turtle = False
                
    # 화면 표시
    if score is None:
        cv2.putText(frame, "score: (no pose)", (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        
    else:
        cv2.putText(frame, f"score: {score:.4f}", (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(frame, f"TH_ON: {TH_ON:.3f}  TH_OFF: {TH_OFF:.3f}", (20, 75),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        
    if is_turtle:
        cv2.putText(frame, "TURTLE NECK!", (20, 130),
        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
        cv2.putText(frame, "Fix your posture", (20, 175),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

    else:
        cv2.putText(frame, "Posture: OK", (20, 130),
        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 200, 0), 3)
        
    cv2.imshow("Step4 - Turtle Neck Warning", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == 27:
        break  

pose.close()
cap.release()
cv2.destroyAllWindows()