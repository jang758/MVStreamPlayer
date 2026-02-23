# StreamPlayer 🎬

쿠키 기반 인증을 지원하는 스트리밍 비디오 플레이어입니다.

## 시작하기

### 1. 실행

```
start.bat 더블클릭
```

또는 수동 실행:

```bash
pip install -r requirements.txt
python server.py
```

### 2. 브라우저에서 접속

```
http://localhost:5000
```

## 쿠키 설정 (선택)

인증이 필요한 스트리밍 사이트의 경우:

1. **방법 A** — `cookies.txt` 파일(Netscape 포맷)을 앱 폴더(`StreamPlayer/`)에 넣기
   - 히토미 다운로더의 쿠키 파일을 이 포맷으로 변환하여 사용 가능
   - 크롬 확장 "Get cookies.txt LOCALLY" 등으로 추출 가능

2. 쿠키가 감지되면 상단에 `🍪 쿠키 적용됨` 표시

## 기능

| 기능                | 설명                                            |
| ------------------- | ----------------------------------------------- |
| 📋 대기열           | URL을 계속 추가하면 리스트에 누적               |
| 💾 마지막 위치 기억 | 재생 위치 자동 저장, 다시 열면 복원             |
| 🔥 반복 히트맵      | 자주 본 구간이 진행바에 강조 표시               |
| ⬇ 다운로드          | 다운로드 버튼으로 영상 저장 (`downloads/` 폴더) |
| ⌨ 단축키            | Space, ←→, J/L, F 등                            |

## 키보드 단축키

| 키        | 동작                           |
| --------- | ------------------------------ |
| `Space`   | 재생/정지                      |
| `Shift+←` | 5초 뒤로                       |
| `Shift+→` | 5초 앞으로                     |
| `←`       | 10초 뒤로                      |
| `→`       | 10초 앞으로                    |
| `↑/↓`     | 음량 조절                      |
| `M`       | 음소거                         |
| `F`       | 전체화면                       |
| `Shift+N` | 다음 영상                      |
| `Shift+P` | 이전 영상                      |
| `,` / `.` | 프레임 단위 이동 (일시정지 중) |

## 지원 사이트

- **범용**: yt-dlp가 지원하는 모든 사이트 (YouTube, etc.)
- **MissAV 계열**: missav.ws, missav.ai, missav.com, njavtv.com
  - P.A.C.K.E.R. 난독화 해제 + 쿠키 인증 지원
  - 히토미 다운로더의 `hitomi.py` 로직 기반 커스텀 추출기 내장

## 폴더 구조

```
StreamPlayer/
├── server.py          # 백엔드 서버 (yt-dlp + 커스텀 추출기)
├── hitomi.py          # 참조용 - MissAV 추출 원본 로직
├── static/
│   ├── style.css      # 다크 테마 스타일
│   └── app.js         # 프론트엔드 앱 로직
├── templates/
│   └── index.html     # 메인 페이지
├── downloads/         # 다운로드된 영상
├── cookies.txt        # (직접 넣기) 쿠키 파일
├── data.json          # 자동 생성 - 대기열/재생위치/히트맵
├── requirements.txt
├── start.bat
└── README.md
```
