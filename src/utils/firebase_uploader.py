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

import firebase_admin
from firebase_admin import credentials, firestore

log = logging.getLogger(__name__)


class FirebaseUploader:

    def __init__(self, key_path: str):
        self._available = False
        self.db = None
        if not os.path.exists(key_path):
            log.warning("서비스 계정 키 없음 — 업로드 비활성: %s", key_path)
            return
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(key_path)
                firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self._available = True
        except Exception as e:
            log.error("초기화 실패 — 업로드 비활성: %s", e)

    def upload_log_file(self, file_path: str, uid: str | None) -> bool:
        if not self._available or not uid or not os.path.exists(file_path):
            return False

        try:
            data: list[dict] = []
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
                date_part, hour_part = raw_name.split("_")
                h_int      = int(hour_part)
                hour_range = f"{h_int}~{h_int + 1}"
            except ValueError:
                date_part  = "unknown_date"
                hour_range = raw_name

            doc_ref = (
                self.db
                .collection("hour")
                .document(uid)
                .collection(date_part)
                .document(hour_range)
            )
            doc_ref.set({
                "date":                  date_part,
                "hour_range":            hour_range,
                "uid":                   uid,
                "total_tracked_seconds": total_tracked_seconds,
                "total_turtle_seconds":  total_turtle_seconds,
                "bad_posture_count":     bad_posture_count,
                "log_data":              data,
                "uploaded_at":           firestore.SERVER_TIMESTAMP,
            })

            log.info("업로드 완료: hour/%s/%s/%s", uid, date_part, hour_range)
            return True

        except Exception as e:
            log.error("업로드 실패: %s", e)
            return False

    def get_stats(self, uid: str) -> dict | None:
        if not self._available or not uid:
            return None
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            doc_ref   = (
                self.db
                .collection("day")
                .document(uid)
                .collection("history")
                .document(today_str)
            )
            doc = doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            log.error("통계 조회 실패: %s", e)
            return None
