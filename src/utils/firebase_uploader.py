"""
firebase_uploader.py — Firestore 업로드 (로그인 사용자 전용)

Firestore 경로:
    users/{uid}/posture_logs/{YYYY-MM-DD_HH}

uid 가 없으면 업로드를 건너뛴다 (비로그인 보호).
firebase_key.json 이 없거나 초기화 실패 시 graceful degradation.
"""
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore


class FirebaseUploader:
    def __init__(self, key_path: str):
        self._available = False
        self.db = None
        if not os.path.exists(key_path):
            print(f"[Firebase] 서비스 계정 키 없음 — 업로드 비활성: {key_path}")
            return
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(key_path)
                firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self._available = True
        except Exception as e:
            print(f"[Firebase] 초기화 실패 — 업로드 비활성: {e}")

    def upload_log_file(self, file_path: str, uid: str | None) -> bool:
        """
        jsonl 파일을 읽어 Firestore 에 업로드.

        uid   : 로그인 사용자 식별자. None 이면 업로드 스킵.
        반환값: 업로드 성공 여부 (uid 없음 / 파일 없음 / 오류 시 False)
        """
        if not self._available:
            return False
        if not uid:
            return False
        if not os.path.exists(file_path):
            return False

        try:
            data = []
            total_tracked_seconds = 0
            total_turtle_seconds = 0
            bad_posture_count = 0

            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    data.append(entry)
                    total_tracked_seconds += entry.get("total_seconds", 0)
                    total_turtle_seconds  += entry.get("turtle_seconds", 0)
                    bad_posture_count     += entry.get("status", 0)

            if not data or total_tracked_seconds == 0:
                return False

            base_name = os.path.basename(file_path)
            doc_name  = os.path.splitext(base_name)[0]

            # users/{uid}/posture_logs/{doc_name}
            doc_ref = (
                self.db
                .collection("users")
                .document(uid)
                .collection("posture_logs")
                .document(doc_name)
            )
            doc_ref.set({
                "date_hour":             doc_name,
                "uid":                   uid,
                "total_tracked_seconds": total_tracked_seconds,
                "total_turtle_seconds":  total_turtle_seconds,
                "bad_posture_count":     bad_posture_count,
                "log_data":              data,
                "uploaded_at":           firestore.SERVER_TIMESTAMP,
            })

            print(
                f"[Firebase] 업로드 성공: {doc_name} "
                f"(측정 {total_tracked_seconds}s, 거북목 {total_turtle_seconds}s)"
            )
            return True

        except Exception as e:
            print(f"[Firebase] 업로드 실패 ({file_path}): {e}")
            return False
