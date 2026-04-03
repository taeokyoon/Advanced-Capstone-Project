@echo off
REM ─────────────────────────────────────────────────────────────────
REM  TurtleNeckDetector — PyInstaller exe 빌드 스크립트 (Windows)
REM
REM  사전 조건:
REM    pip install pyinstaller
REM    (또는 .venv 활성화 후 실행)
REM
REM  결과물: dist\TurtleNeckDetector\TurtleNeckDetector.exe
REM ─────────────────────────────────────────────────────────────────

setlocal

echo [Build] TurtleNeckDetector 빌드 시작...

REM .venv 가 있으면 자동 활성화
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [Build] 가상환경 활성화됨
)

REM pyinstaller 설치 확인
python -m pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo [오류] PyInstaller 가 설치되어 있지 않습니다.
    echo        pip install pyinstaller 를 먼저 실행하세요.
    pause
    exit /b 1
)

REM 이전 빌드 정리
if exist "dist\TurtleNeckDetector" (
    echo [Build] 이전 빌드 폴더 삭제 중...
    rmdir /s /q "dist\TurtleNeckDetector"
)
if exist "build\turtle_neck" (
    rmdir /s /q "build\turtle_neck"
)

REM PyInstaller 빌드 실행
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

if errorlevel 1 (
    echo.
    echo [오류] 빌드 실패. 위의 오류 메시지를 확인하세요.
    pause
    exit /b 1
)

echo.
echo [Build] 빌드 성공!
echo [Build] 실행 파일 위치: dist\TurtleNeckDetector\TurtleNeckDetector.exe
echo.
echo [안내] 배포 시 포함 필요 파일:
echo   - dist\TurtleNeckDetector\ (폴더 전체)
echo   - config.json 은 빌드에 포함됨 (사용자 수정 불필요 시 그대로 배포)
echo   - firebase_key.json 보안 주의: 외부 공유 금지
echo.
pause
