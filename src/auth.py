"""
auth.py — Firebase Auth REST API 기반 사용자 인증 + 세션 관리

비로그인 모드가 기본: api_key 미설정 또는 네트워크 오류 시 로그인 없이 계속 동작.
"""
import json
import os
import requests
from datetime import datetime

_SIGN_IN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
)


class AuthManager:
    """
    이메일/비밀번호 로그인 + 로컬 세션 파일 기반 재시작 후 세션 복원.
    모든 메서드는 예외를 외부로 던지지 않는다 (호출자 부담 최소화).
    """

    def __init__(self, session_path: str, api_key: str):
        """
        session_path : 세션을 저장할 JSON 파일 경로 (예: logs/session.json)
        api_key      : Firebase 프로젝트 Web API 키 (config.json 에서 주입)
                       빈 문자열이면 로그인 시도 시 즉시 실패 처리.
        """
        self.session_path = session_path
        self.api_key = api_key
        self._uid: str | None = None
        self._email: str | None = None

    # ── 세션 유지 ──────────────────────────────────────────────────────────────

    def load_session(self) -> bool:
        """앱 시작 시 저장된 세션 파일을 읽어 uid/email 복원. 성공 시 True."""
        if not os.path.exists(self.session_path):
            return False
        try:
            with open(self.session_path, encoding="utf-8") as f:
                data = json.load(f)
            uid = data.get("uid")
            if not uid:
                return False
            self._uid = uid
            self._email = data.get("email")
            print(f"[Auth] 세션 복원: {self._email} ({self._uid})")
            return True
        except Exception as e:
            print(f"[Auth] 세션 파일 읽기 실패: {e}")
            return False

    def save_session(self):
        """현재 uid/email 을 세션 파일에 기록."""
        try:
            os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
            data = {
                "uid": self._uid,
                "email": self._email,
                "logged_in_at": datetime.now().isoformat(),
            }
            with open(self.session_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Auth] 세션 저장 실패: {e}")

    def _clear_session(self):
        self._uid = None
        self._email = None
        if os.path.exists(self.session_path):
            try:
                os.remove(self.session_path)
            except Exception:
                pass

    # ── 인증 ──────────────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> str | None:
        """
        Firebase Auth REST API 로 이메일/비밀번호 인증.
        성공 시 uid(str) 반환, 실패 시 None.
        """
        if not self.api_key:
            print("[Auth] firebase_api_key 가 config.json 에 설정되지 않았습니다.")
            return None
        if not email or not password:
            return None
        try:
            resp = requests.post(
                f"{_SIGN_IN_URL}?key={self.api_key}",
                json={
                    "email": email,
                    "password": password,
                    "returnSecureToken": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()
            self._uid = body["localId"]
            self._email = body["email"]
            self.save_session()
            print(f"[Auth] 로그인 성공: {self._email} ({self._uid})")
            return self._uid
        except requests.exceptions.HTTPError as e:
            # Firebase 가 반환하는 에러 메시지 추출
            try:
                reason = e.response.json()["error"]["message"]
            except Exception:
                reason = str(e)
            print(f"[Auth] 로그인 실패: {reason}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[Auth] 네트워크 오류: {e}")
            return None

    def logout(self):
        """로컬 세션 삭제 후 비로그인 상태로 전환."""
        email = self._email
        self._clear_session()
        print(f"[Auth] 로그아웃: {email}")

    # ── 상태 조회 ─────────────────────────────────────────────────────────────

    def get_uid(self) -> str | None:
        return self._uid

    def get_email(self) -> str | None:
        return self._email

    def is_logged_in(self) -> bool:
        return self._uid is not None
