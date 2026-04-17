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
import datetime
from firebase_admin import credentials, firestore


class FirebaseUploader:
    
    def get_stats(self, uid: str) -> dict | None:
        """Firestore의 'day' 컬렉션에서 사용자의 누적 통계 데이터를 가져옵니다."""
        if not self._available or not uid:
            return None
        
        try:
            # 오늘 날짜 문자열 만들기 (예: "2026-04-09")
            today_str = datetime.now().strftime("%Y-%m-%d")
            # 클라우드 함수가 누적해둔 day/{uid} 문서 조회
            doc_ref = self.db.collection("day").document(uid).collection("history").document(today_str)
            doc = doc_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            else:
                return None
        except Exception as e:
            print(f"[Firebase] 통계 데이터 조회 중 오류 발생: {e}")
            return None
    
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
        if not self._available or not uid or not os.path.exists(file_path):
            return False

        try:
            data = []
            total_tracked_seconds = 0
            total_turtle_seconds  = 0
            bad_posture_count     = 0

            # 1. 파일 읽으면서 요약 데이터 계산 및 배열(data) 생성
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    entry = json.loads(line)
                    data.append(entry)
                    total_tracked_seconds += entry.get("total_seconds", 0)
                    total_turtle_seconds  += entry.get("turtle_seconds", 0)
                    bad_posture_count     += entry.get("status", 0)

            if not data or total_tracked_seconds == 0:
                return False

            # 2. 파일명 분석 (예: "2026-04-09_13.jsonl")
            base_name = os.path.basename(file_path)
            raw_name  = os.path.splitext(base_name)[0] 
            
            try:
                date_part, hour_part = raw_name.split('_')
                h_int = int(hour_part)
                hour_range = f"{h_int}~{h_int+1}"
            except ValueError:
                date_part = "unknown_date"
                hour_range = raw_name

            # 3. 계층형 경로 설정: hour / {uid} / {date_part} / {hour_range}
            doc_ref = (
                self.db
                .collection("hour")
                .document(uid)
                .collection(date_part)
                .document(hour_range)
            )

            # 4. 요약 데이터와 배열을 한 번에 업로드!
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

            print(f"[Firebase] 요약+배열 업로드 완료: hour/{uid}/{date_part}/{hour_range}")
            return True

        except Exception as e:
            print(f"[Firebase] 업로드 실패: {e}")
            return False
