"""
firebase_uploader.py — Firestore 업로드 (로그인 사용자 전용)

Firestore 경로:
    hour/{uid}/{YYYY-MM-DD}/{H~H+1}

uid 가 없으면 업로드를 건너뛴다 (비로그인 보호).
firebase_key.json 이 없거나 초기화 실패 시 graceful degradation.
"""
import json
import logging
import os
from datetime import datetime

import requests

log = logging.getLogger(__name__)

class FirebaseUploader:
    def __init__(self, auth_manager, project_id: str):
        self.auth_manager = auth_manager
        # 클라우드 함수(서버) 접속 주소
        self.base_url = f"https://asia-northeast3-{project_id}.cloudfunctions.net"
        self._available = bool(project_id)

    def upload_log_file(self, file_path: str, uid: str | None) -> bool:
        # uid 대신 안전한 토큰을 가져옵니다.
        id_token = self.auth_manager.get_valid_token()
        if not self._available or not id_token or not os.path.exists(file_path):
            return False

        try:
            data = []
            total_tracked_seconds = 0
            total_turtle_seconds  = 0
            bad_posture_count     = 0

            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    entry = json.loads(line)
                    data.append(entry)
                    total_tracked_seconds += entry.get("total_seconds", 0)
                    total_turtle_seconds  += entry.get("turtle_seconds", 0)
                    bad_posture_count     += entry.get("status", 0)

            if not data or total_tracked_seconds == 0:
                return False

            base_name = os.path.basename(file_path)
            raw_name  = os.path.splitext(base_name)[0] 
            
            try:
                date_part, hour_part = raw_name.split('_')
                h_int = int(hour_part)
                hour_range = f"{h_int}~{h_int+1}"
            except ValueError:
                date_part = "unknown_date"
                hour_range = raw_name

            payload = {
                "date": date_part,
                "hour_range": hour_range,
                "total_tracked_seconds": total_tracked_seconds,
                "total_turtle_seconds": total_turtle_seconds,
                "bad_posture_count": bad_posture_count,
                "log_data": data
            }

            url = f"{self.base_url}/uploadLog"
            headers = {"Authorization": f"Bearer {id_token}"}
            
            response = requests.post(url, json=payload, headers=headers, timeout=15)

            if response.status_code == 200:
                log.info("업로드 완료: hour/%s/%s", date_part, hour_range)
                return True
            else:
                log.error("업로드 거부됨: %s", response.text)
                return False

        except Exception as e:
            log.error("업로드 실패: %s", e)
            return False

    def get_stats(self, uid: str) -> dict | None:
        id_token = self.auth_manager.get_valid_token()
        if not self._available or not id_token:
            return None
            
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            url = f"{self.base_url}/getStats?date={today_str}"
            headers = {"Authorization": f"Bearer {id_token}"}
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            log.error("통계 데이터 조회 실패: %s", e)
            return None
