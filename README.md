# TurtleNeckDetector

웹캠 하나로 거북목 자세를 실시간 감지하는 Windows 백그라운드 앱입니다.

## 빠른 시작

```bash
# 가상환경 venv 설치
py -3.11 -m venv .venv
.venv/scripts/activate

# 필요 라이브러리 설치
pip install -r requirements.txt

# 실행
python turtle_neck.py
```

트레이 아이콘 우클릭 → **캘리브레이션** → 모니터링 시작

# 실제 워크플로우
코드 수정
    ↓
py turtle_neck.py  ← 빠른 테스트 (이걸로 주로 개발)
    ↓
잘 되면 pyinstaller로 빌드  ← .exe 갱신
    ↓
.exe로 최종 확인

## 상세 문서

[DEVELOP.md](DEVELOP.md) 참고
