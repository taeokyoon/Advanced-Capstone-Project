"""
auth.py — Firebase Auth REST API 기반 사용자 인증 + 세션 관리

비로그인 모드가 기본: api_key 미설정 또는 네트워크 오류 시 로그인 없이 계속 동작.
"""
import json
import logging
import os
from datetime import datetime

import requests

log = logging.getLogger(__name__)

_SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
_SIGN_UP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signUp"


class AuthManager:
    """
    이메일/비밀번호 로그인 + 로컬 세션 파일 기반 재시작 후 세션 복원.
    모든 메서드는 예외를 외부로 던지지 않는다 (호출자 부담 최소화).
    """

    def __init__(self, session_path: str, api_key: str):
        self.session_path = session_path
        self.api_key      = api_key
        self._uid:   str | None = None
        self._email: str | None = None
        self.last_error: str | None = None

    # ── 세션 유지 ──────────────────────────────────────────────────────────────

    def load_session(self) -> bool:
        if not os.path.exists(self.session_path):
            return False
        try:
            with open(self.session_path, encoding="utf-8") as f:
                data = json.load(f)
            uid = data.get("uid")
            if not uid:
                return False
            self._uid   = uid
            self._email = data.get("email")
            log.info("세션 복원: %s (%s)", self._email, self._uid)
            return True
        except Exception as e:
            log.warning("세션 파일 읽기 실패: %s", e)
            return False

    def save_session(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
            data = {
                "uid":          self._uid,
                "email":        self._email,
                "logged_in_at": datetime.now().isoformat(),
            }
            with open(self.session_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("세션 저장 실패: %s", e)

    def _clear_session(self) -> None:
        self._uid   = None
        self._email = None
        if os.path.exists(self.session_path):
            try:
                os.remove(self.session_path)
            except Exception:
                pass

    # ── 인증 ──────────────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> str | None:
        if not self.api_key:
            log.warning("firebase_api_key 가 설정되지 않았습니다.")
            return None
        if not email or not password:
            return None
        self._uid   = None
        self._email = None
        try:
            resp = requests.post(
                f"{_SIGN_IN_URL}?key={self.api_key}",
                json={"email": email, "password": password, "returnSecureToken": True},
                timeout=10,
            )
            resp.raise_for_status()
            body        = resp.json()
            self._uid   = body["localId"]
            self._email = body["email"]
            self.save_session()
            log.info("로그인 성공: %s (%s)", self._email, self._uid)
            return self._uid
        except requests.exceptions.HTTPError as e:
            reason = self._extract_firebase_error(e)
            log.warning("로그인 실패: %s", reason)
            return None
        except requests.exceptions.RequestException as e:
            log.warning("네트워크 오류: %s", e)
            return None

    def check_email_exists(self, email: str) -> bool | None:
        """
        True=이미 사용 중, False=사용 가능, None=확인 불가.
        Firebase 이메일 열거 보호가 꺼져 있어야 정확히 동작.
        """
        if not self.api_key or not email:
            return None
        try:
            resp = requests.post(
                f"{_SIGN_IN_URL}?key={self.api_key}",
                json={"email": email, "password": "__probe__", "returnSecureToken": False},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            reason = self._extract_firebase_error(e)
            log.debug("이메일 확인: %s", reason)
            if "INVALID_PASSWORD" in reason or "INVALID_LOGIN_CREDENTIALS" in reason:
                return True
            if "EMAIL_NOT_FOUND" in reason or "INVALID_EMAIL" in reason:
                return False
            self.last_error = reason
            return None
        except requests.exceptions.RequestException as e:
            self.last_error = f"NETWORK: {e}"
            log.warning("이메일 확인 네트워크 오류: %s", e)
            return None

    def signup(self, email: str, password: str) -> str | None:
        if not self.api_key:
            log.warning("firebase_api_key 가 설정되지 않았습니다.")
            return None
        if not email or not password:
            return None
        try:
            resp = requests.post(
                f"{_SIGN_UP_URL}?key={self.api_key}",
                json={"email": email, "password": password, "returnSecureToken": True},
                timeout=10,
            )
            resp.raise_for_status()
            body        = resp.json()
            self._uid   = body["localId"]
            self._email = body["email"]
            self.save_session()
            log.info("회원가입 성공: %s (%s)", self._email, self._uid)
            return self._uid
        except requests.exceptions.HTTPError as e:
            reason = self._extract_firebase_error(e)
            self.last_error = reason
            log.warning("회원가입 실패: %s", reason)
            return None
        except requests.exceptions.RequestException as e:
            self.last_error = "NETWORK_ERROR"
            log.warning("네트워크 오류: %s", e)
            return None

    def logout(self) -> None:
        email = self._email
        self._clear_session()
        log.info("로그아웃: %s", email)

    # ── 상태 조회 ─────────────────────────────────────────────────────────────

    def get_uid(self) -> str | None:
        return self._uid

    def get_email(self) -> str | None:
        return self._email

    def is_logged_in(self) -> bool:
        return self._uid is not None

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_firebase_error(e: requests.exceptions.HTTPError) -> str:
        try:
            return e.response.json()["error"]["message"]
        except Exception:
            return str(e)
