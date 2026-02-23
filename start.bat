@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ══════════════════════════════════════
echo   StreamPlayer 시작
echo ══════════════════════════════════════
echo.

:: 가상환경 확인/생성
if not exist "venv" (
    echo [1/4] 가상환경 생성 중...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo [오류] Python이 설치되지 않았습니다!
        echo   https://www.python.org/downloads/ 에서 설치 후
        echo   "Add Python to PATH" 체크를 꼭 해주세요.
        echo.
        pause
        exit /b 1
    )
)

:: 가상환경 활성화
echo [2/4] 가상환경 활성화 중...
call venv\Scripts\activate.bat

:: 의존성 설치
echo [3/4] 패키지 설치 확인 중...
:: 이전 버전의 무거운 패키지 제거 (Rust 컴파일 문제 방지)
pip uninstall rookiepy DrissionPage -y -q 2>nul
pip install -r requirements.txt -q 2>nul
if errorlevel 1 (
    echo   일부 패키지 설치 실패, 개별 설치 시도...
    pip install flask yt-dlp requests beautifulsoup4 pywebview curl_cffi -q 2>nul
)

:: 데스크탑 앱 실행
echo [4/4] 앱 실행 중...
echo.
python app.py
pause
