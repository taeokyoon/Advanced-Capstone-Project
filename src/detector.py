"""
detector.py — MediaPipe Pose 기반 자세 점수 계산 및 거북목 판정
"""
import time
import cv2
import mediapipe as mp
from collections import deque


class PostureDetector:
    """
    head_forward_score 계산 + 슬라이딩 윈도우 평균 + 히스테리시스 판정.
    카메라 스레드에서만 사용한다고 가정 (스레드 세이프 아님).
    """

    def __init__(self, delta_turtle: float, delta_ok: float):
        self.delta_turtle  = delta_turtle
        self.delta_ok      = delta_ok
        self.scores: deque = deque(maxlen=200)
        self.baseline_score: float | None = None
        self.is_turtle: bool = False
        self._last_eval: float = time.time()

        self._mp_pose = mp.solutions.pose
        self._pose    = self._mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    # ── 프레임 처리 ───────────────────────────────────────────────────────────
    def _calc_score(self, lms) -> "float | None":
        """랜드마크 배열에서 head_forward_score 계산."""
        NOSE = lms[self._mp_pose.PoseLandmark.NOSE.value]
        LS   = lms[self._mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        RS   = lms[self._mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        if min(LS.visibility, RS.visibility) <= 0.5:
            return None
        sw = abs(LS.x - RS.x)
        if sw <= 0.05:
            return None
        return ((LS.y + RS.y) / 2 - NOSE.y) / sw

    def process_frame(self, frame) -> "float | None":
        """BGR 프레임을 받아 head_forward_score 반환. 감지 실패 시 None."""
        result = self._pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not result.pose_landmarks:
            return None
        return self._calc_score(result.pose_landmarks.landmark)

    def process_frame_visual(self, frame) -> "tuple[float | None, object]":
        """BGR 프레임 처리 후 (score, rgb_annotated) 반환. 시작 창 시각화 전용."""
        rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._pose.process(rgb)
        if not result.pose_landmarks:
            return None, rgb
        mp.solutions.drawing_utils.draw_landmarks(
            rgb,
            result.pose_landmarks,
            self._mp_pose.POSE_CONNECTIONS,
        )
        return self._calc_score(result.pose_landmarks.landmark), rgb

    # ── 상태 갱신 (1초마다 판정) ──────────────────────────────────────────────
    def update(self, score: float | None) -> tuple[bool, bool]:
        """
        score 를 슬라이딩 윈도우에 추가하고 1초마다 판정.

        Returns:
            evaluated    (bool): 이번 호출에서 판정이 수행됐는지
            state_changed(bool): is_turtle 상태가 바뀌었는지
        """
        now = time.time()
        if score is not None:
            self.scores.append((now, score))

        # 1초 이전 데이터 제거
        while self.scores and now - self.scores[0][0] > 1.0:
            self.scores.popleft()

        if now - self._last_eval < 1.0 or len(self.scores) < 5:
            return False, False

        self._last_eval = now
        avg = sum(s for _, s in self.scores) / len(self.scores)

        if self.baseline_score is None:
            return True, False

        deviation = avg - self.baseline_score
        prev      = self.is_turtle

        if not self.is_turtle and deviation < -self.delta_turtle:
            self.is_turtle = True
        elif self.is_turtle and deviation > -self.delta_ok:
            self.is_turtle = False

        return True, (self.is_turtle != prev)

    # ── 캘리브레이션 ──────────────────────────────────────────────────────────
    def calibrate(self) -> float | None:
        """현재 슬라이딩 윈도우 평균을 baseline 으로 설정. 데이터 부족 시 None."""
        if len(self.scores) < 5:
            return None
        self.baseline_score = sum(s for _, s in self.scores) / len(self.scores)
        return self.baseline_score

    def close(self):
        self._pose.close()
