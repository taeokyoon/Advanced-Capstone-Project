# TurtleNeckDetector (거북목 감지기)

> 웹캠 하나로 실시간 거북목 자세를 감지하고, Windows 시스템 트레이에서 조용히 동작하며 경고 알림을 보내주는 백그라운드 애플리케이션입니다.

---

## 목차

1. [기능 목록](#기능-목록)
2. [시스템 아키텍처](#시스템-아키텍처)
3. [기술 스택 및 의존성](#기술-스택-및-의존성)
4. [설치 및 실행 방법](#설치-및-실행-방법)
5. [사용 방법](#사용-방법)
6. [빌드 및 배포](#빌드-및-배포)
7. [제한사항 및 개선 방향](#제한사항-및-개선-방향)
8. [라이선스 및 기여 방법](#라이선스-및-기여-방법)

---

## 기능 목록

- **실시간 자세 감지** — 웹캠에서 MediaPipe Pose로 코·어깨 좌표를 추출하여 거북목 여부 판정
- **캘리브레이션** — 사용자의 정상 자세를 기준값으로 설정, 개인 체형·카메라 위치 차이를 자동 보정
- **히스테리시스 판정** — 진입/해제 임계값을 다르게 설정해 상태 떨림(flickering) 방지
- **시스템 트레이 아이콘** — 창 없이 백그라운드 동작, 아이콘 색상으로 상태 즉시 확인
  - 🔘 회색: 캘리브레이션 대기 중
  - 🟢 초록: 자세 정상
  - 🔴 빨강: 거북목 감지됨
- **Windows 토스트 알림** — 거북목 감지 시 1회 팝업 알림 발송
- **JSON Lines 로그 저장** — 분 단위로 `posture_log.jsonl` 파일에 기록 (9시간 근무 기준 약 540건/일)

---

## 시스템 아키텍처

### 전체 구조

```
┌─────────────────────────────────────────────────────┐
│                   turtle_neck.py                    │
│                                                     │
│  [메인 스레드]              [백그라운드 스레드]          │
│  pystray.Icon.run()   ←→   camera_loop()            │
│  트레이 아이콘 관리          카메라 프레임 처리           │
│  메뉴 이벤트 처리            자세 점수 계산              │
│                             판정 + 알림 발송           │
│                             JSON 로그 저장             │
└─────────────────────────────────────────────────────┘
```

> Windows에서 pystray는 반드시 메인 스레드에서 실행해야 합니다.
> 카메라 처리는 daemon 스레드로 분리하여 병렬 동작합니다.

---

### 데이터 흐름

```
웹캠 프레임
    │
    ▼
MediaPipe Pose
    │  코(NOSE), 좌우 어깨(LEFT/RIGHT_SHOULDER) 랜드마크 추출
    ▼
head_forward_score()
    │  (shoulder_y - nose_y) / shoulder_width
    ▼
슬라이딩 윈도우 (deque, 1초)
    │  최근 1초 평균 score 계산
    ▼
판정 로직 (1초마다)
    │  deviation = avg - baseline
    │  deviation < -0.10  →  거북목 진입
    │  deviation > -0.05  →  정상 복귀
    ▼
┌──────────────┬─────────────────┐
트레이 아이콘   Windows 알림      JSON 로그 (60초마다)
업데이트       (상태 전환 시)     posture_log.jsonl
```

---

### 주요 함수 설명

| 함수 / 구성요소 | 역할 |
|---|---|
| `head_forward_score()` | 어깨 너비로 정규화한 코-어깨 Y좌표 비율 계산 |
| `camera_loop()` | 백그라운드 스레드: 프레임 수집 → 점수 계산 → 판정 → 저장 |
| `update_tray()` | 현재 상태에 따라 트레이 아이콘/툴팁 갱신 |
| `notify()` | winotify로 Windows 토스트 알림 발송 |
| `save_record()` | JSON Lines 형식으로 분 단위 기록 append |
| `on_calibrate()` | 트레이 메뉴 → 현재 score를 baseline으로 설정 |
| `on_quit()` | stop_event 세트 → 카메라 스레드 종료 → 트레이 종료 |

---

### 로그 파일 구조 (`posture_log.jsonl`)

한 줄 = 1분 기록 (JSON Lines 형식)

```jsonl
{"timestamp": "2026-03-24T09:01:00", "status": 0, "turtle_seconds": 3, "total_seconds": 60}
{"timestamp": "2026-03-24T09:02:00", "status": 1, "turtle_seconds": 38, "total_seconds": 59}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `timestamp` | string (ISO 8601) | 기록 시각 |
| `status` | 0 or 1 | 구간 다수결 결과 (0: 정상, 1: 거북목) |
| `turtle_seconds` | int | 해당 구간 내 거북목 판정 초 수 |
| `total_seconds` | int | 해당 구간 내 유효 측정 초 수 |

---

## 기술 스택 및 의존성

| 라이브러리 | 용도 |
|---|---|
| `opencv-python` | 웹캠 프레임 캡처 및 전처리 |
| `mediapipe` | Pose 랜드마크 추출 |
| `pystray` | Windows 시스템 트레이 아이콘 |
| `Pillow` | 트레이 아이콘 이미지 생성 |
| `winotify` | Windows 토스트 알림 |
| `PyInstaller` | 실행 파일(.exe) 빌드 |

**Python 버전:** 3.10 이상 권장 (`float | None` 타입 힌트 사용)

---

## 설치 및 실행 방법

### 1. 저장소 클론

```bash
git clone <repository-url>
cd Advanced-Capstone-Project
```

### 2. 의존성 설치

```bash
pip install opencv-python mediapipe pystray pillow winotify pyinstaller
```

### 3. 스크립트로 실행 (개발용)

```bash
python turtle_neck.py
```

> 실행 후 작업표시줄 트레이에 회색 아이콘이 생성됩니다.

---

## 사용 방법

### 1단계: 캘리브레이션

1. 앱 실행 후 **바른 자세로 웹캠 앞에 앉는다**
2. 트레이 아이콘 **우클릭 → 캘리브레이션** 클릭
3. "캘리브레이션 완료" 알림이 뜨면 아이콘이 초록색으로 변경됨

> 캘리브레이션 없이는 감지가 시작되지 않습니다.
> 카메라 위치가 바뀌거나 자리를 옮기면 재캘리브레이션 권장.

### 2단계: 모니터링

- 앱은 백그라운드에서 조용히 동작하며 창이 뜨지 않습니다
- 트레이 아이콘 색상으로 현재 자세 상태 확인 가능
- 거북목 자세가 감지되면 Windows 알림 팝업이 표시됩니다

### 3단계: 로그 확인

앱 실행 파일과 같은 폴더에 `posture_log.jsonl` 파일이 생성됩니다.
텍스트 편집기나 Python으로 읽기 가능:

```python
import json

with open("posture_log.jsonl", encoding="utf-8") as f:
    records = [json.loads(line) for line in f]

print(f"총 {len(records)}건 기록")
```

### 종료

트레이 아이콘 **우클릭 → 종료**

---

## 빌드 및 배포

### PyInstaller로 .exe 생성

```bash
pyinstaller --noconsole --onedir --name TurtleNeckDetector \
    --collect-all mediapipe \
    --hidden-import pystray._win32 \
    turtle_neck.py
```

| 옵션 | 설명 |
|---|---|
| `--noconsole` | 콘솔 창 없이 실행 |
| `--onedir` | 폴더 형태 빌드 (MediaPipe 크기로 인해 `--onefile`보다 안정적) |
| `--collect-all mediapipe` | MediaPipe 모델 파일 포함 |
| `--hidden-import pystray._win32` | Windows 트레이 백엔드 명시적 포함 |

**결과물 위치:** `dist/TurtleNeckDetector/TurtleNeckDetector.exe`

> 빌드 결과물 크기는 MediaPipe 포함으로 인해 약 300~500MB입니다.

---

## 제한사항 및 개선 방향

### 현재 제한사항

| 항목 | 내용 |
|---|---|
| 하드코딩된 임계값 | `DELTA_TURTLE=0.10`, `DELTA_OK=0.05` 코드에 고정됨 |
| 단일 사용자 | 다중 사용자 프로필 미지원 |
| Windows 전용 | pystray/winotify가 Windows 기반 |
| 카메라 단일 고정 | 카메라 인덱스 0 고정, 멀티 카메라 미지원 |
| 로컬 저장만 지원 | 현재 JSON 파일 로컬 저장, 원격 DB 미지원 |

### 개선 방향

- **설정 파일** (`config.json`) 도입으로 임계값 UI 조정 가능하게 변경
- **Firebase 연동** — `posture_log.jsonl` → Firestore 실시간 동기화
- **대시보드** — 주간/월간 거북목 통계 시각화 (웹 또는 앱)
- **알림 쿨다운** — 반복 알림 최소 간격 설정
- **자동 시작** — Windows 시작 프로그램 등록 옵션

---

## 라이선스 및 기여 방법

### 라이선스

```
MIT License

Copyright (c) 2026 TurtleNeckDetector Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
```

### 기여 방법

1. 이 저장소를 Fork 합니다
2. 기능 브랜치를 생성합니다 (`git checkout -b feature/기능명`)
3. 변경사항을 커밋합니다 (`git commit -m 'Add 기능명'`)
4. 브랜치를 Push 합니다 (`git push origin feature/기능명`)
5. Pull Request를 생성합니다

버그 리포트 및 기능 제안은 Issues 탭을 이용해 주세요.

# 폴더 트리 구조
Advanced-Capstone-Project/
│
├── src/                         ← 핵심 모듈 패키지
│   ├── __init__.py
│   ├── detector.py              ← MediaPipe 자세 감지·판정
│   ├── logger.py                ← JSON Lines 로그 저장
│   └── tray_app.py              ← 트레이 아이콘·알림
│
├── data/                        ← 런타임 자동 생성
│   ├── .gitkeep                 (빈 폴더 git 추적용)
│   └── posture_log.jsonl        (앱 실행 후 자동 생성)
│
├── turtle_neck.py               ← 진입점 (Entry Point)
├── config.json                  ← 사용자 설정값
│
├── DEVELOP.md                   ← 설계 지침 (Source of Truth)
├── README.md                    ← 프로젝트 소개
├── requirements.txt             ← 의존성 목록
├── .gitignore
│
└── (빌드/개발 환경)
    ├── dist/                    ← PyInstaller 빌드 출력
    ├── .venv/
    └── __pycache__/

# 파일 구분
- 실제 사용되는 파일 (functional)
turtle_neck.py : 앱 실행 진입점
src/detector.py : 자세 감지 로직
src/logger.py : 로그 기록
src/tray_app.py : UI (트레이, 알림)
config.json : 임계값 설정 (수정가능)
data/posture_log.json : 런타임 자동 생성되는 데이터

- 형식적인 파일 (convention)
DEVELOP.md : 설계 문서
README.md : 프로젝트 소개
requirements.txt : 설치 시에만 적용
.gitignore : git 규칙
data/.gitkeep : 빈 폴더 git 추적용

---

# 2차 개발 계획 — 비로그인 모드 유지 + 로그인 연동 통계 + exe 배포

> 현재 트레이 앱의 즉시 사용 가능한 탐지 기능을 유지하면서,
> 로그인 사용자에게 데이터 연동·통계 기능을 추가하고 exe 배포 체계를 구축한다.

---

## 현재 상태와 문제점

### 완성된 기능 (1차)

| 파일 | 역할 |
|---|---|
| `turtle_neck.py` | 진입점: 스레드 오케스트레이션 |
| `src/detector.py` | MediaPipe 자세 점수 계산 + 히스테리시스 판정 |
| `src/logger.py` | JSON Lines 분 단위 로컬 로그 저장 |
| `src/tray_app.py` | pystray 트레이 아이콘 + 알림 |
| `src/utils/notifier.py` | OS별 알림 추상화 |
| `src/utils/firebase_uploader.py` | Firestore 업로드 (부분 완료) |

### 현재 미해결 사항 (2차 개발 착수 전 기준)

> 아래 항목은 2차 개발(1단계·2단계)을 통해 **모두 해결 완료**되었습니다.

| 항목 | 해결 방법 |
|---|---|
| Firebase 업로드에 사용자 식별자 없음 | `AuthManager` + `uid` 기반 경로 분리로 해결 |
| 비로그인/로그인 모드 구분 없음 | `tray_app.py` 메뉴 동적 전환 + `AuthManager` 통합 |
| exe 빌드 미검증 | `build.bat` 빌드 스크립트 구현 완료 (실행 검증은 4단계) |

---

## 현재 진행 상태 (2026-04-10 기준)

| 단계 | 상태 | 비고 |
|---|---|---|
| 1단계: 모드 분리·인증 기반 | ✅ 완료 | 회원가입 기능 추가 구현 포함 |
| 2단계: 데이터 연동 파이프라인 | ✅ 완료 | 오프라인 큐·uid 분리 동작 확인 |
| 3단계: 통계 조회 | 🔶 부분 완료 | 로컬 기반 통계 팝업 구현, Firestore 쿼리(`stats.py`) 미구현 |
| 4단계: exe 배포 | 🔶 진행 중 | `build.bat` 작성 완료, 실제 빌드 검증 필요 |
| 5단계: 운영 안정화 | ⬜ 미시작 | `app_logger.py` 미구현 |

### 설계 대비 추가 구현된 기능 (미문서화 항목)

| 기능 | 위치 | 설명 |
|---|---|---|
| 회원가입 (`signup`) | `src/auth.py`, `turtle_neck.py` | 이메일 중복확인 버튼 포함 회원가입 폼 |
| `check_email_exists()` | `src/auth.py` | signInWithPassword 프로브 방식 중복 확인 |
| `_ask_signup_credentials()` | `turtle_neck.py` | 이메일 중복확인 + 비밀번호 일치 검증 tkinter 폼 |
| `_SIGNUP_ERROR_MAP` | `turtle_neck.py` | Firebase 에러 코드 → 한국어 메시지 매핑 |
| `flush_with_record()` | `src/logger.py` | flush 결과를 dict로 반환 (업로드 큐 연동용) |
| `get_all_records(hour_prefix)` | `src/utils/upload_queue.py` | 시간대 필터링으로 done+pending 전체 반환 |
| `mark_failed()` | `src/utils/upload_queue.py` | 업로드 실패 항목을 failed 상태로 마킹 |
| `_switch_logger(uid)` | `turtle_neck.py` | 로그인/로그아웃 시 logger·upload_queue 경로 교체 |
| `_get_user_dir(uid)` | `turtle_neck.py` | uid 유무로 logs 하위 경로 결정 |
| `_show_stats()` | `turtle_neck.py` | 로컬 JSONL 기반 통계 tkinter 팝업 (3단계 부분 구현) |

---

## 제품 원칙

1. **비로그인 기본 제공**: 앱 실행 즉시 탐지 기능 사용 가능 — 로그인은 선택
2. **데이터 안전성 우선**: 오프라인/네트워크 오류에서 로컬 데이터 유실 없음
3. **배포 현실성**: 개발 환경 없이 exe만으로 실행 가능

---

## 사용자 모드 정의

### 비로그인 모드 (기본)
- 앱 실행 → 캘리브레이션 → 탐지 즉시 시작
- 로컬 `logs/anonymous/` 폴더에만 저장, Firebase 업로드 없음
- 트레이 메뉴: `캘리브레이션 | 로그인 | 종료`

### 로그인 모드
- Firebase Auth 인증 후 `uid` 연결
- 탐지 데이터를 `users/{uid}/posture_logs/` 경로에 업로드
- 비로그인 시 누적된 로컬 데이터는 로그인 후 일괄 업로드 옵션 제공
- 트레이 메뉴: `캘리브레이션 | 통계 보기 | 로그아웃 | 종료`

---

## 단계별 개발 계획

---

### 1단계: 모드 분리와 인증 기반

**목표**: 비로그인 기본 플로우 유지 + 로그인/로그아웃 UI 추가

#### 신규 파일: `src/auth.py` ✅ 구현 완료

```python
# AuthManager 클래스 — 실제 구현 메서드
class AuthManager:
    def login(email, password) -> uid | None      # Firebase Auth REST 로그인
    def signup(email, password) -> uid | None     # 신규 계정 생성 (설계 추가)
    def check_email_exists(email) -> bool | None  # 중복 이메일 확인 (설계 추가)
    def logout()
    def get_uid() -> str | None
    def get_email() -> str | None
    def is_logged_in() -> bool
    def load_session()   # 앱 재시작 후 세션 복원
    def save_session()   # uid, email, 로그인 시각 → logs/session.json
    # last_error: str | None  — 마지막 에러 코드 보관 (회원가입 에러 전달용)
```

세션 저장 경로: `logs/session.json`

#### 수정 파일: `src/tray_app.py` ✅ 구현 완료

- `build_tray()` 에 `auth_manager` 파라미터 추가
- 로그인 상태에 따라 메뉴 동적 생성 (`visible` 람다)
- 비로그인: `캘리브레이션 | 로그인 | 회원가입 | 종료` (회원가입 추가됨)
- 로그인: `캘리브레이션 | 통계 보기 | 로그아웃 | 종료`

#### 수정 파일: `turtle_neck.py` ✅ 구현 완료

- `AuthManager` 인스턴스 생성 및 앱 시작 시 `load_session()` 호출
- `on_login()`, `on_logout()`, `on_signup()` 콜백 구현
- `_ask_credentials()` — tkinter 이메일/비밀번호 입력 다이얼로그
- `_ask_signup_credentials()` — 이메일 중복확인 버튼 포함 회원가입 전용 폼
- `_SIGNUP_ERROR_MAP` — Firebase 에러 코드 → 한국어 안내 메시지 매핑
- `_show_signup_error()` — 회원가입 실패 시 에러 팝업

#### 완료 기준
- [x] 로그인 없이 기존 탐지 기능이 그대로 동작
- [x] 로그인/로그아웃 전환이 앱 재시작 포함 안정 동작
- [x] 트레이 메뉴가 로그인 상태에 따라 올바르게 전환됨
- [x] 회원가입 후 자동 로그인 및 로그 경로 전환 동작 (추가 달성)

---

### 2단계: 데이터 연동 파이프라인

**목표**: 사용자 식별자 연결 + 오프라인 복구 큐 구현

#### 데이터 저장 경로 분리

```
logs/
├── anonymous/               ← 비로그인 데이터 (uid 없음)
│   └── posture_log.jsonl
└── {uid}/                   ← 로그인 사용자별 데이터
    ├── posture_log.jsonl
    └── upload_queue.jsonl   ← 업로드 대기 레코드
```

#### Firestore 경로 설계

```
users/
└── {uid}/
    └── posture_logs/
        └── {YYYY-MM-DD_HH}/    ← 시간 단위 문서
            ├── total_tracked_seconds
            ├── total_turtle_seconds
            ├── bad_posture_count
            ├── log_data[]
            └── uploaded_at
```

#### 수정 파일: `src/utils/firebase_uploader.py` ✅ 구현 완료

- `upload_log_file(file_path, uid)` 로 시그니처 변경
- `uid` 없으면 업로드 스킵 (비로그인 보호)
- Firestore 경로: `users/{uid}/posture_logs/{YYYY-MM-DD_HH}`
- Firestore 문서 필드: `total_tracked_seconds`, `total_turtle_seconds`, `bad_posture_count`, `log_data[]`, `uploaded_at`

#### 신규 파일: `src/utils/upload_queue.py` ✅ 구현 완료

```python
# UploadQueue 클래스 — 실제 구현 메서드
class UploadQueue:
    def enqueue(record: dict)                        # pending 상태로 JSONL에 append
    def get_pending() -> list[dict]                  # status == "pending" 항목 반환
    def get_all_records(hour_prefix) -> list[dict]   # done+pending 전체 반환 (설계 추가)
    def mark_done(entry_ids: list[str])              # 업로드 성공 → done 상태
    def mark_failed(entry_ids: list[str])            # 업로드 실패 → failed 상태 (설계 추가)
    def retry_failed()                               # failed → pending 으로 복원 후 재시도
```

업로드 실패 시 `upload_queue.jsonl` 에 `status: "failed"` 기록,
`retry_failed()` 로 `pending` 복원 → 다음 upload_loop 주기에 재시도

각 항목 구조:
```json
{"id": "<uuid>", "status": "pending|done|failed", "queued_at": "<ISO8601>", "record": {<posture record>}}
```

#### 수정 파일: `src/logger.py` ✅ 구현 완료

- 생성자에 `user_dir: str` 파라미터 추가 (uid 기반 경로 주입)
- `flush_with_record() -> dict | None` 추가 — flush 결과를 dict로 반환해 upload_queue 연동 (설계 추가)

#### 수정 파일: `turtle_neck.py` ✅ 구현 완료

- `_get_user_dir(uid)` — uid 유무로 `logs/{uid}` 또는 `logs/anonymous` 반환
- `_switch_logger(uid)` — 로그인/로그아웃 시 logger·upload_queue 경로 교체 및 기존 데이터 flush
- `upload_loop()` — 60초 간격으로 `auth_manager.get_uid()` 확인 후 pending 업로드 실행
- 비로그인이면 `logs/anonymous/` 에만 저장, 업로드 스킵

#### 완료 기준
- [x] 로그인 사용자 데이터가 `users/{uid}/posture_logs/` 에 저장됨
- [x] 비로그인 데이터는 Firebase에 전송되지 않음
- [x] 네트워크 단절 후 재연결 시 pending 레코드 자동 재전송 확인 (코드 검증 완료)

---

### 3단계: 통계 조회 최소 기능

**목표**: 일/주 단위 통계 집계 + 트레이 내 간단 요약 표시

#### 통계 집계 지표

| 지표 | 집계 단위 | 계산 방식 |
|---|---|---|
| 일일 거북목 비율 | 일 단위 | `total_turtle_seconds / total_tracked_seconds` |
| 주간 평균 비율 | 주 단위 | 최근 7일 일일 비율 평균 |
| 오늘 거북목 횟수 | 일 단위 | `bad_posture_count` 합계 |

#### 신규 파일: `src/stats.py` ⬜ 미구현 (Firestore 쿼리 기반)

```python
# 다음 스프린트 구현 예정
class StatsManager:
    def get_daily_summary(uid, date) -> dict
    def get_weekly_summary(uid) -> dict
    def _query_firestore(uid, date_range) -> list[dict]
```

#### 부분 구현: `turtle_neck.py` — `_show_stats()` 🔶 로컬 기반으로 선구현

- 로그인 사용자 전용, `logs/{uid}/posture_log.jsonl` 로컬 파일을 직접 읽어 집계
- tkinter 팝업으로 `계정 / 기록 수 / 총 측정 시간 / 거북목 비율(%)` 표시
- Firestore 쿼리(주간 통계) 미구현 — `stats.py` 완성 후 교체 예정

#### 수정 파일: `src/tray_app.py` ✅ 부분 구현

- "통계 보기" 메뉴: 로그인 상태(`is_logged_in()`)일 때만 `visible=True`로 표시
- 비로그인 상태에서는 메뉴 자체가 숨겨짐 (별도 제한 메시지 없이 항목 비노출)

#### 완료 기준
- [x] 로그인 사용자 기준 오늘 통계 팝업 표시 (로컬 JSONL 기반)
- [ ] 주간 통계 집계 및 표시 (`stats.py` + Firestore 쿼리) — 다음 스프린트
- [x] 비로그인 상태에서 통계 메뉴 비노출 (메뉴 항목 자체 숨김 처리)

---

### 4단계: 엔드유저 배포 (exe 전환)

**목표**: PyInstaller 빌드 파이프라인 완성 + 포터블 패키지 배포

#### 빌드 명령 (자동화 스크립트: `build.bat`) ✅ 스크립트 구현 완료

`build.bat` 실행 시 아래 명령을 자동 수행합니다:

```bat
python -m pyinstaller ^
  --noconsole ^
  --onedir ^
  --name TurtleNeckDetector ^
  --collect-all mediapipe ^
  --hidden-import pystray._win32 ^
  --hidden-import firebase_admin ^
  --hidden-import google.cloud.firestore ^
  --add-data "config.json;." ^
  --add-data "firebase_key.json;." ^
  turtle_neck.py
```

설계 대비 추가된 옵션:
- `--hidden-import google.cloud.firestore` — Firestore 클라이언트 명시적 포함

`build.bat` 기능:
- `.venv` 가상환경 자동 감지 및 활성화
- PyInstaller 설치 여부 사전 확인
- 이전 빌드(`dist/TurtleNeckDetector`, `build/turtle_neck`) 자동 정리
- 빌드 성공/실패 메시지 출력

> `sys.frozen` 분기는 `turtle_neck.py` 에 구현됨 — 유지.
> 빌드 후 `dist/TurtleNeckDetector/` 에서 직접 실행 검증 필수.

#### 포터블 패키지 구성

```
TurtleNeckDetector/
├── TurtleNeckDetector.exe   ← 실행 파일
├── config.json              ← 사용자 수정 가능 설정
├── firebase_key.json        ← 서비스 계정 키
└── logs/                    ← 런타임 자동 생성
```

#### 완료 기준
- [x] `build.bat` 스크립트 작성 완료 (사전 검증 완료)
- [ ] `python turtle_neck.py` 없이 exe 단독 실행 성공 — 실행 검증 필요
- [ ] 신규 PC에서 exe 더블클릭 → 트레이 아이콘 정상 동작 확인
- [ ] 로그인/로그아웃/캘리브레이션 모두 exe 환경에서 동작

---

### 5단계: 운영 안정화

**목표**: 로그 수집 정책 정리 + 업데이트 전략 + 릴리스 프로세스 확정

#### 로그 수집 정책

| 이벤트 | 기록 위치 | 형식 |
|---|---|---|
| 인증 실패 | `logs/app.log` | `[AUTH_FAIL] timestamp, reason` |
| 업로드 실패 | `logs/app.log` | `[UPLOAD_FAIL] timestamp, file, error` |
| 크래시 | `logs/crash.log` | `traceback` 전체 |

#### 신규 파일: `src/app_logger.py`

`logging` 모듈 기반 파일 + 콘솔 핸들러

#### 업데이트 전략 (이번 단계: 수동 업데이트)

- GitHub Releases 에 새 버전 포터블 zip 업로드
- 트레이 메뉴 "버전 확인" 클릭 시 최신 버전 비교 후 다운로드 링크 안내
- 자동 업데이트는 다음 스프린트에서 검토

#### 완료 기준
- [ ] 인증 실패, 업로드 실패 시나리오 테스트 결과 문서화
- [ ] 릴리스 체크리스트 작성 및 1회 배포 검증 완료

---

## 이번 스프린트 범위

### ✅ 완료
- **1단계 전체**: `AuthManager` (로그인/로그아웃/회원가입), 트레이 메뉴 동적 전환, 세션 지속
- **2단계 전체**: 로그 경로 분리(`_switch_logger`), `FirebaseUploader` uid 연결, `UploadQueue` 구현
- **3단계 부분**: 로컬 JSONL 기반 통계 팝업 `_show_stats()` 선구현
- **4단계 사전**: `build.bat` 빌드 스크립트 작성 완료

### 🔶 다음 스프린트 우선 과제
- **3단계 완성**: `src/stats.py` 구현 (Firestore 쿼리 기반 일/주 통계)
- **4단계 완성**: 실제 exe 빌드 실행 및 신규 환경 검증
- **5단계**: `src/app_logger.py` 앱 이벤트 로그 (인증 실패·업로드 실패·크래시)

### 제외 (추후 검토)
- 자동 업데이트 완성형 배포
- 개인 맞춤 코칭/알림 고도화
- 주간/월간 통계 대시보드 (웹 또는 앱)

---

## 목표 폴더 구조 (2차 개발 후)

```
Advanced-Capstone-Project/
│
├── src/
│   ├── __init__.py
│   ├── auth.py              ← [신규] Firebase Auth 세션 관리
│   ├── detector.py          ← [유지]
│   ├── logger.py            ← [수정] uid 기반 경로 주입
│   ├── stats.py             ← [신규] 통계 집계 (3단계)
│   ├── app_logger.py        ← [신규] 앱 이벤트 로그 (5단계)
│   └── utils/
│       ├── firebase_uploader.py  ← [수정] uid 파라미터 추가
│       ├── notifier.py           ← [유지]
│       └── upload_queue.py       ← [신규] 오프라인 큐
│
├── logs/                    ← 런타임 자동 생성
│   ├── anonymous/           ← 비로그인 데이터
│   │   └── posture_log.jsonl
│   ├── {uid}/               ← 로그인 사용자별 데이터
│   │   ├── posture_log.jsonl
│   │   └── upload_queue.jsonl
│   ├── session.json         ← 로그인 세션 저장
│   └── app.log              ← 앱 이벤트 로그
│
├── turtle_neck.py           ← [수정] AuthManager 통합
├── config.json              ← [유지]
├── firebase_key.json        ← [유지]
├── DEVELOP.md               ← 이 파일
├── README.md
└── requirements.txt         ← [수정] 추가 의존성 반영
```

---

## 최종 성공 기준

| 시나리오 | 기준 |
|---|---|
| 비로그인 사용자 | 앱 실행 → 캘리브레이션 → 탐지까지 로그인 없이 동작 |
| 로그인 사용자 | 로그인 후 데이터가 `users/{uid}/posture_logs/` 에 업로드됨 |
| 오프라인 복구 | 네트워크 재연결 후 pending 레코드 자동 재전송 |
| exe 배포 | 개발 환경 없는 PC에서 exe 더블클릭만으로 트레이 동작 |