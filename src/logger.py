"""
logger.py — JSON Lines 형식으로 분 단위 자세 기록 저장
"""
import json
import os
from datetime import datetime


class PostureLogger:
    """
    초 단위 판정 결과를 누적하다가 flush() 호출 시
    한 줄의 JSON Lines 레코드로 posture_log.jsonl 에 append.
    """

    def __init__(self, log_path: str):
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self.log_path     = log_path
        self.turtle_secs  = 0
        self.total_secs   = 0

    def tick(self, is_turtle: bool):
        """매 판정 초마다 호출."""
        self.total_secs += 1
        if is_turtle:
            self.turtle_secs += 1

    def flush(self) -> bool:
        """누적 데이터를 파일에 기록하고 카운터 초기화. 성공 여부 반환."""
        if self.total_secs == 0:
            return False

        record = {
            "timestamp":      datetime.now().isoformat(timespec="seconds"),
            "status":         1 if self.turtle_secs > self.total_secs / 2 else 0,
            "turtle_seconds": self.turtle_secs,
            "total_seconds":  self.total_secs,
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.turtle_secs = 0
            self.total_secs  = 0
            return True
        except Exception as e:
            print(f"[log error] {e}")
            return False
