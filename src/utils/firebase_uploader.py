import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

class FirebaseUploader:
    def __init__(self, key_path):
        if not firebase_admin._apps:
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()

    def upload_log_file(self, file_path):
        """jsonl 파일을 읽어서 핵심 누적 데이터만 Firebase에 업로드"""
        if not os.path.exists(file_path):
            return False

        try:
            data = []
            total_tracked_seconds = 0  
            total_turtle_seconds = 0   
            bad_posture_count = 0      
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    log_entry = json.loads(line)
                    data.append(log_entry)
                    
                    total_tracked_seconds += log_entry.get("total_seconds", 0)
                    total_turtle_seconds += log_entry.get("turtle_seconds", 0)
                    bad_posture_count += log_entry.get("status", 0)

            if not data or total_tracked_seconds == 0:
                return False 

            base_name = os.path.basename(file_path)
            doc_name = os.path.splitext(base_name)[0]
            
            doc_ref = self.db.collection("posture_logs").document(doc_name)
            
            # 서버/모바일 앱이 계산하기 좋도록 '순수 누적 데이터'만 전송
            doc_ref.set({
                "date_hour": doc_name,
                "total_tracked_seconds": total_tracked_seconds,
                "total_turtle_seconds": total_turtle_seconds,
                "bad_posture_count": bad_posture_count,
                "log_data": data, # 모바일 앱에서 시간대별 그래프를 그릴 때 사용할 원본 배열
                "uploaded_at": firestore.SERVER_TIMESTAMP
            })
            
            print(f"[Firebase] 🚀 업로드 성공: {doc_name} (총 측정: {total_tracked_seconds}초, 거북목: {total_turtle_seconds}초)")
            return True
            
        except Exception as e:
            print(f"[Firebase] ❌ 업로드 실패 ({file_path}): {e}")
            return False