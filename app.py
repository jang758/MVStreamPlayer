"""
StreamPlayer 데스크탑 앱 런처
더블클릭 한 번으로 자체 윈도우에서 실행됩니다.
"""

import threading
import sys
import os
import json
from pathlib import Path

# 현재 파일 위치 기준으로 경로 설정
os.chdir(os.path.dirname(os.path.abspath(__file__)))

DATA_FILE = Path(__file__).parent / "data.json"

def _read_settings():
    """data.json에서 설정 읽기"""
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("settings", {})
    except Exception:
        pass
    return {}

def start_server():
    """Flask 서버를 백그라운드에서 시작"""
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    from server import app
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

if __name__ == "__main__":
    print("=" * 40)
    print("  StreamPlayer 데스크탑 앱 시작 중...")
    print("=" * 40)
    
    # Flask 서버를 별도 스레드에서 시작
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # 서버가 올라올 시간을 줌
    import time
    time.sleep(1.5)
    
    try:
        import webview

        # WebView2 SmartScreen 비활성화 (missav.ws 탐색 시 경고 방지)
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
            '--disable-features=msSmartScreenProtection,msSafeLinksValidation'
            ' --safebrowsing-disable-auto-update'
            ' --disable-client-side-phishing-detection'
            ' --no-first-run'
        )
        
        # 저장된 설정에서 창 크기, 항상 위 읽기
        settings = _read_settings()
        win_w = settings.get("windowWidth", 1400)
        win_h = settings.get("windowHeight", 850)
        on_top = settings.get("alwaysOnTop", False)
        
        # 데스크탑 메인 윈도우 생성
        window = webview.create_window(
            title="StreamPlayer",
            url="http://127.0.0.1:5000",
            width=win_w,
            height=win_h,
            min_size=(900, 600),
            text_select=False,
            confirm_close=False,
            on_top=on_top,
        )
        
        # server.py에 메인 윈도우 참조 전달
        from server import set_webview_window, set_webview_ready
        set_webview_window(window)
        
        # 검색 윈도우는 /api/open-search 호출 시 동적 생성 (server.py에서 처리)
        def _on_webview_started():
            """guilib 초기화 완료 후 호출 — 이 시점부터 create_window() 가능"""
            set_webview_ready()
        
        
        print(f"  앱이 실행되었습니다! ({win_w}x{win_h}, 항상위={'ON' if on_top else 'OFF'})")
        print("  창을 닫으면 앱이 종료됩니다.")
        
        # 윈도우 시작 (func 콜백으로 guilib 초기화 완료 시그널)
        # 이 줄에서 블로킹됨 — 창 닫을 때까지
        webview.start(func=_on_webview_started)
        
    except ImportError:
        print("")
        print("  [알림] pywebview가 설치되지 않아 브라우저로 엽니다.")
        print("  데스크탑 앱으로 쓰려면: pip install pywebview")
        print("")
        import webbrowser
        webbrowser.open("http://127.0.0.1:5000")
        print("  브라우저에서 열렸습니다. 이 창을 닫으면 서버가 종료됩니다.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    except Exception as e:
        print(f"  오류 발생: {e}")
        print("  브라우저로 대체 실행합니다...")
        import webbrowser
        webbrowser.open("http://127.0.0.1:5000")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
