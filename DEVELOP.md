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