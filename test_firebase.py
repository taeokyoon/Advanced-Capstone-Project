import os
os.environ["GRPC_DNS_RESOLVER"] = "native"

import firebase_admin
from firebase_admin import credentials, firestore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. 그 폴더 위치에 "firebase_key.json"을 안전하게 결합
KEY_PATH = os.path.join(BASE_DIR, "firebase_key.json") 

print("🔌 Firebase 연결 시도 중...")
try:
    cred = credentials.Certificate(KEY_PATH)
    # ... (아래는 기존 코드와 동일) ...
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ 연결 성공!")
except Exception as e:
    print(f"❌ 연결 실패 (키 파일을 확인하세요): {e}")
    exit()

# 2. 보낼 데이터 준비 (텍스트)
test_data = {
    "title": "첫 번째 테스트",
    "message": "안녕하세요! 터미널에서 Firebase로 보내는 텍스트입니다.",
    "is_test": True
}

# 3. 데이터 전송! ('test_messages'라는 컬렉션(폴더)에 저장합니다)
print("🚀 데이터 전송 중...")
try:
    # 문서 이름(ID)을 'my_first_msg'로 지정해서 보냅니다.
    db.collection("test_messages").document("my_first_msg").set(test_data)
    print("🎉 전송 완료! Firebase 콘솔 웹사이트에서 확인해 보세요.")
except Exception as e:
    print(f"❌ 전송 실패: {e}")