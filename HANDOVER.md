# StreamPlayer 프로젝트 인수인계 문서

> **최종 업데이트:** 2026-02-27  
> **상태:** **사이트 브라우저 + 카테고리 관리 + 브라우저 확장 + 사이트 창 재생 + 광고 차단(fake window) + 대기열 관리 강화 + HLS 프록시 + 5단계 백업 + 중복 필터 + 추가 대기열 + 카테고리 컨텍스트 메뉴 구현 완료**  
> **사용자 환경:** Windows, Whale + Edge 브라우저 (Chrome 미설치), Python 가상환경(venv)  
> **코드 규모:** 약 7,600줄 (server.py ~3,078 / app.js ~2,070 / style.css ~1,770 / index.html ~296)

---

## 1. 프로젝트 개요

MissAV 등 특정 스트리밍 사이트의 영상 URL을 입력하면 바로 재생하는 **데스크탑 스트리밍 플레이어**.

### 핵심 기능

- **영상 재생**: HLS.js 기반 M3U8 스트리밍 (빠른 시작 최적화 적용)
- **대기열 관리**: URL 추가/삭제/드래그 정렬, 드래그 앤 드롭 URL 추가
- **재생 위치 복원**: 영상별 마지막 위치 자동 저장/복원 (다중 이벤트 + sendBeacon)
- **히트맵**: 자주 본 구간 시각화 (진행 바 위 3단계 색상)
- **다운로드 대기열**: 최대 2개 동시 다운로드, 개별 진행 상태 표시
- **설정 시스템**: 화질/속도/볼륨/건너뛰기/항상위 등 자동 저장
- **쿠키 관리**: 브라우저 자동 감지 + 내부 쿠키 추출 기능
- **URL 진단(🔍)**: Cloudflare 상태, P.A.C.K.E.R. 분석, M3U8 추출 결과 실시간 확인
- **데이터 내보내기/가져오기**: 전체 데이터 JSON 백업/복원 (병합 방식)
- **사이트 탐색**: MissAV 사이트를 pywebview 내장 브라우저로 직접 탐색 + JS 인젝션으로 [+추가] 버튼 오버레이
- **사이트 창 재생**: 정보 패널 URL 클릭 시 pywebview 사이트 창에서 바로 영상 재생 (내장 플레이어 로딩 지연 우회)
- **광고 차단**: 사이트 창에서 5단계 광고 차단 (팝업/오버레이/클릭하이재킹/외부링크/beforeunload)
- **브라우저 확장**: 강제 인젝션/새로고침/커스텀 우클릭 메뉴/새 탭 열기/Ctrl+클릭 지원
- **카테고리 관리**: 대기열 항목을 카테고리별로 분류/필터링/관리
- **자동저장/이중백업**: 저장 시 data.json.bak→bak2 순환, 손상 시 자동 복구, 5분 주기 백업, 종료 시 저장
- **검색 기능**: MissAV 키워드 검색 API (레거시, search.html)
- **관련 영상**: 영상 정보 패널에서 관련/추천 영상 표시 + 대기열 추가
- **키보드 단축키**: Space, 방향키, M, F, N/P, 쉼표/마침표 등 13개

### 대상 사이트

- `missav.ws`, `missav.ai`, `missav.com`, `njavtv.com`
- 공통 특징: **Cloudflare 보호** + **P.A.C.K.E.R. JavaScript 난독화**

---

## 2. 아키텍처

```
┌──────────────────────────────────────────────────┐
│  사용자                                           │
│  └─ pywebview (네이티브 창) 또는 브라우저           │
│     ├─ index.html + app.js + style.css (메인)     │
│     └─ search.html + search.js + search.css (검색) │
│        └─ HLS.js v1.5.7 (CDN)                    │
│           └─ REST API 호출 (32개 엔드포인트)       │
├──────────────────────────────────────────────────┤
│  Flask 백엔드 (server.py, port 5000)              │
│  ├─ yt-dlp: 범용 영상 추출 + 브라우저 쿠키         │
│  ├─ curl_cffi: Cloudflare TLS 핑거프린트 우회      │
│  ├─ _custom_extract(): MissAV P.A.C.K.E.R. 해제   │
│  ├─ /api/stream: HLS 프록시 (M3U8 캐시 + 폴백)    │
│  ├─ /api/search: MissAV 키워드 검색 (CF 우회)      │
│  ├─ /api/related: 관련 영상 스크래핑               │
│  ├─ 캐시: 추출 캐시(1h) + M3U8 콘텐츠 캐시(30m)    │
│  ├─ 백그라운드: 사전추출 스레드 + 다운로드 워커      │
│  ├─ 자동백업: 5분 주기 + atexit 종료 저장              │
│  └─ data.json + .bak + .bak2: 이중 백업 영속 저장      │
├──────────────────────────────────────────────────┤
│  브라우저 쿠키 (Edge/Whale)                        │
│  └─ yt-dlp cookiesfrombrowser → cf_clearance 추출  │
└──────────────────────────────────────────────────┘
```

### 영상 추출 흐름

1. **대기열에 `stream_url` 저장됨** → 즉시 사용 (재추출 불필요, 1-2초 재생)
2. **없으면 추출**:
   - 커스텀 도메인 → `_custom_extract()` 직접 사용 (yt-dlp 건너뜀)
   - 기타 → yt-dlp 시도 → 실패 시 커스텀 폴백
3. **커스텀 추출기** (`_custom_extract()`):
   - `_fetch_page_with_cf_bypass()`: 3단계 CF 우회 (curl_cffi+브라우저쿠키 → curl_cffi+cookies.txt → requests)
   - P.A.C.K.E.R. 디코딩 4단계:
     - 방법1: `pcode`에서 직접 M3U8 URL 검색
     - 방법2: `_unpack_packer()` — base-N 토큰을 keywords 배열로 치환
     - 방법3: `_reconstruct_m3u8_from_keywords()` — hitomi.py 방식 인덱스 패턴
     - 방법4: 스크립트/페이지 전체 폴백 검색
4. M3U8 마스터 플레이리스트 → 화질 설정에 따라 선택
5. **M3U8 URL 만료(403) 시** → 자동 재추출 + 캐시 갱신

---

## 3. 파일 구조

```
StreamPlayer/
├── server.py          (2,578줄) 핵심 백엔드 - Flask 서버 + 추출 + 캐시 + 다운로드 + 검색 + 브라우저 + 광고차단
├── app.py             (111줄)   pywebview 데스크탑 런처 (메인창 + 검색창, SmartScreen 비활성화)
├── hitomi.py          (407줄)   참조용 원본 MissAV 추출기 (직접 실행 안 됨)
├── static/
│   ├── app.js         (1,710줄) 프론트엔드 SPA (HLS.js + UI + 설정 + 다운로드 + 카테고리 + 사이트창재생 + 다중선택)
│   ├── style.css      (1,246줄) 다크 테마 스타일 (CSS 변수 기반)
│   ├── search.js      (247줄)  검색 창 프론트엔드 (검색·결과·대기열추가·관련영상)
│   └── search.css     (335줄)  검색 창 스타일 (다크 테마)
├── templates/
│   ├── index.html     (257줄)  메인 HTML 레이아웃 + 설정 모달 + 카테고리 관리 모달 + 벌크 액션 바
│   └── search.html    (57줄)   검색 창 HTML
├── start.bat          (38줄)   원클릭 실행 (venv + pip + 실행)
├── requirements.txt   (6줄)    Python 의존성
├── data.json          (런타임) 대기열/재생위치/히트맵/설정/카테고리 데이터
├── data.json.bak      (런타임) 1차 백업 (저장 시 자동 생성)
├── data.json.bak2     (런타임) 2차 백업 (이전 .bak 보관)
├── cookies.txt        (선택)   Netscape 쿠키 파일 (수동 또는 내부 추출)
├── README.md          (72줄)   사용 설명서
├── HANDOVER.md        (이 파일) 인수인계 문서
└── downloads/         (런타임) 다운로드된 영상 저장 폴더
```

---

## 4. API 엔드포인트 (32개)

### 페이지

| 메서드 | 경로      | 용도                    |
| ------ | --------- | ----------------------- |
| GET    | `/`       | 메인 페이지 렌더링      |
| GET    | `/search` | 검색 전용 페이지 렌더링 |

### 대기열

| 메서드 | 경로                 | 용도                                 |
| ------ | -------------------- | ------------------------------------ |
| GET    | `/api/queue`              | 대기열 목록 조회                               |
| POST   | `/api/queue`              | URL 추가 (중복 시 409 응답)                    |
| DELETE | `/api/queue/<id>`         | 항목 삭제 (playback, heatmap도 삭제)           |
| POST   | `/api/queue/clear`        | 전체 삭제                                      |
| POST   | `/api/queue/reorder`      | 드래그 순서 변경 (ids 배열)                    |
| POST   | `/api/queue/move`         | 항목 일괄 이동 (ids + position: top/bottom)    |
| POST   | `/api/queue/bulk-delete`  | 항목 일괄 삭제 (ids)                           |
| POST   | `/api/queue/bulk-category`| 항목 카테고리 일괄 변경 (ids + category)       |

### 재생 위치 / 히트맵

| 메서드   | 경로                 | 용도                    |
| -------- | -------------------- | ----------------------- |
| GET/POST | `/api/playback/<id>` | 재생 위치 조회/저장     |
| GET/POST | `/api/heatmap/<id>`  | 히트맵 데이터 조회/기록 |

### 스트리밍

| 메서드 | 경로          | 용도                                                      |
| ------ | ------------- | --------------------------------------------------------- |
| GET    | `/api/stream` | HLS 프록시 (M3U8 캐시 + Range 지원 + 만료 시 자동 재추출) |

### 다운로드

| 메서드 | 경로                         | 용도                   |
| ------ | ---------------------------- | ---------------------- |
| POST   | `/api/download`              | 다운로드 대기열에 추가 |
| GET    | `/api/download/status/<uid>` | 개별 다운로드 상태     |
| GET    | `/api/download/all-status`   | 모든 다운로드 상태     |
| GET    | `/api/download/file/<uid>`   | 완료 파일 전송         |

### 설정 / 윈도우

| 메서드  | 경로                | 용도                                       |
| ------- | ------------------- | ------------------------------------------ |
| GET/PUT | `/api/settings`     | 설정 조회/업데이트 (alwaysOnTop 즉시 적용) |
| POST    | `/api/window/ontop` | 항상 위 토글                               |
| POST    | `/api/window/size`  | 창 크기 저장                               |

### 쿠키 / 진단 / 데이터

| 메서드 | 경로                   | 용도                                  |
| ------ | ---------------------- | ------------------------------------- |
| GET    | `/api/cookies/status`  | 쿠키 파일/자동추출 상태               |
| POST   | `/api/cookies/extract` | 브라우저 쿠키 수동 추출 → cookies.txt |
| POST   | `/api/debug`           | URL 진단 (CF/PACKER/M3U8 분석)        |
| GET    | `/api/data/export`     | 전체 데이터 JSON 내보내기             |
| POST   | `/api/data/import`     | 데이터 가져오기 (기존과 병합)         |

### 검색 & 관련 영상 & 사이트 탐색 & 사이트 창 재생

| 메서드 | 경로                         | 용도                                                   |
| ------ | ---------------------------- | ------------------------------------------------------ |
| GET    | `/api/search?q=&page=&sort=` | MissAV 키워드 검색 (CF 우회 스크래핑, 레거시)          |
| GET    | `/api/related?url=`          | 비디오 페이지에서 관련/추천 영상 추출                  |
| POST   | `/api/open-search`           | MissAV 사이트 브라우저 창 열기 (pywebview + JS 인젝션) |
| POST   | `/api/open-tab`              | 지정 URL을 새 pywebview 사이트 창으로 열기 (사이트 창 재생용) |

### 카테고리 관리

| 메서드 | 경로                       | 용도                            |
| ------ | -------------------------- | ------------------------------- |
| GET    | `/api/categories`          | 카테고리 목록 조회              |
| POST   | `/api/categories`          | 카테고리 생성 (name, color)     |
| PUT    | `/api/categories/<id>`     | 카테고리 수정 (이름/색상)       |
| DELETE | `/api/categories/<id>`     | 카테고리 삭제 (항목은 미분류로) |
| POST   | `/api/categories/reorder`  | 카테고리 순서 변경              |
| POST   | `/api/queue/<id>/category` | 대기열 항목의 카테고리 지정     |

---

## 5. 설정 시스템 (DEFAULT_SETTINGS)

| 키                  | 기본값   | 용도                                   |
| ------------------- | -------- | -------------------------------------- |
| `quality`           | `"best"` | 화질 (best/1080p/720p/480p/360p/worst) |
| `downloadFolder`    | `""`     | 다운로드 폴더 (비면 `downloads/`)      |
| `skipForward`       | `10`     | ←/→ 건너뛰기 초                        |
| `skipBackward`      | `10`     | (skipForward와 동기화됨)               |
| `skipForwardShift`  | `5`      | Shift+←/→ 건너뛰기 초                  |
| `skipBackwardShift` | `5`      | (skipForwardShift와 동기화됨)          |
| `defaultVolume`     | `1.0`    | 기본 볼륨 (0.0~1.0)                    |
| `defaultSpeed`      | `1.0`    | 기본 재생 속도 (0.25~2.0)              |
| `autoplayNext`      | `true`   | 영상 끝나면 다음 자동 재생             |
| `alwaysOnTop`       | `false`  | 항상 위 (pywebview)                    |
| `windowWidth`       | `1400`   | 창 너비                                |
| `windowHeight`      | `850`    | 창 높이                                |

---

## 6. 캐시 & 백그라운드 시스템

### 캐시

| 캐시                  | TTL             | 용도                                       |
| --------------------- | --------------- | ------------------------------------------ |
| `_extract_cache`      | 1시간           | yt-dlp/커스텀 추출 결과 (url → info)       |
| `_m3u8_content_cache` | 30분            | 처리된 M3U8 콘텐츠 (상대→절대 URL 변환 후) |
| `_detected_browser`   | 영구 (1회 감지) | 감지된 브라우저 이름                       |

### 백그라운드 스레드

| 스레드                   | 용도                                                                  |
| ------------------------ | --------------------------------------------------------------------- |
| `_background_preextract` | 서버 시작 3초 후, `stream_url` 없는 대기열 항목 사전 추출 + M3U8 캐시 |
| 다운로드 워커            | `_do_download_worker()` — 각 다운로드마다 daemon 스레드               |
| `_periodic_backup`       | 5분 간격 자동 백업 (daemon 스레드, 이중 순환)                         |
| `atexit` 핸들러          | 프로그램 종료 시 `_shutdown_save()` 최종 저장                         |

### 다운로드 대기열

| 항목        | 값                                                                           |
| ----------- | ---------------------------------------------------------------------------- |
| 최대 동시   | `_MAX_CONCURRENT_DL = 1` (안정성 + 속도 우선, 순차 다운로드)                  |
| 상태        | `queued` → `downloading` → `done` / `error`                                  |
| 폴링        | 프론트엔드에서 1.5초 간격 `/api/download/all-status`                         |
| 파일명      | `_sanitize_filename()`: 특수문자 제거, 최대 200자                            |
| yt-dlp 옵션 | `concurrent_fragment_downloads=4`, `buffersize=256KB`, `http_chunk_size=50MB` |

---

## 7. HLS.js 빠른 시작 설정

| 설정                     | 값      | 목적                                       |
| ------------------------ | ------- | ------------------------------------------ |
| `maxBufferLength`        | `4`     | 4초만 버퍼 후 즉시 재생 시작               |
| `maxMaxBufferLength`     | `30`    | 최대 30초 버퍼                             |
| `maxBufferSize`          | `30MB`  | 메모리 제한                                |
| `startLevel`             | `-1`    | 자동 화질 선택                             |
| `enableWorker`           | `true`  | Web Worker로 디먹싱 (메인스레드 부하 감소) |
| `testBandwidth`          | `false` | 대역폭 테스트 건너뛰기                     |
| `abrEwmaDefaultEstimate` | `5Mbps` | 초기 대역폭 5Mbps 가정                     |
| `startFragPrefetch`      | `true`  | 첫 세그먼트 미리 로드                      |
| `manifestLoadingTimeOut` | `15초`  | 매니페스트 타임아웃                        |

---

## 8. UI 기능 목록

### 플레이어

| 기능             | 설명                                                                                                        |
| ---------------- | ----------------------------------------------------------------------------------------------------------- |
| HLS 재생         | HLS.js → 실패 시 직접 src 폴백 → Safari 네이티브                                                            |
| 재생 위치 복원   | `loadedmetadata`/`canplay` 이벤트에서 시크. `beforeunload`에서 `sendBeacon` 동기 저장. 5초 인터벌 자동 저장 |
| 히트맵           | 2초마다 재생 초 기록, 프로그레스 바에 3단계 색상 시각화                                                     |
| 마지막 위치 마커 | 프로그레스 바에 이전 재생 위치를 노란 마커로 표시                                                           |
| 클릭/더블클릭    | 클릭=재생/정지 (200ms 타이머), 더블클릭=전체화면                                                            |
| 스킵 인디케이터  | 건너뛰기 시 좌/우에 500ms 동안 아이콘 표시                                                                  |
| 재생 속도        | 드롭다운 0.25x ~ 2x                                                                                         |
| 볼륨 자동 저장   | 슬라이더 500ms / 키보드 1초 디바운스로 서버에 저장                                                          |

### 대기열

| 기능               | 설명                                                      |
| ------------------ | --------------------------------------------------------- |
| URL 추가           | 입력 / Enter / 드래그 앤 드롭 (text/uri-list, text/plain) |
| 드래그 정렬        | 항목 드래그로 순서 변경 (서버 저장)                       |
| 클릭/더블클릭      | 클릭=정보 패널 (250ms), 더블클릭=재생                     |
| 정보 패널          | URL, 길이, 화질 variant, 다운로드 상태 표시 (고정 DOM)    |
| 재생 위치 배지     | 썸네일에 이전 위치 표시 (resume-badge)                    |
| 다운로드 완료 배지 | 썸네일에 ✅ 표시                                          |
| 자동 재생          | 영상 종료 시 1초 대기 후 다음 재생                        |
| 중복 방지          | URL MD5 해시로 ID 생성, 동일 URL 추가 차단                |

### 다운로드 패널 (NEW)

| 기능             | 설명                                                                   |
| ---------------- | ---------------------------------------------------------------------- |
| 개별 항목 표시   | 각 다운로드의 제목 + 상태 아이콘(⬇️/⏳/✅/❌) + 퍼센트 + 프로그레스 바 |
| 실시간 갱신      | 1.5초 폴링으로 진행률 업데이트                                         |
| 자동 파일 트리거 | 완료 시 브라우저 다운로드 트리거                                       |
| 자동 숨김        | 모든 다운로드 완료 후 8초 뒤 패널 자동 숨김                            |
| 닫기 버튼        | ✕ 버튼으로 수동 닫기 가능                                              |

### 기타 UI

| 기능         | 설명                                                  |
| ------------ | ----------------------------------------------------- |
| 설정 모달    | 화질, 폴더, 건너뛰기 초, 볼륨, 속도, 자동재생, 항상위 |
| 쿠키 상태    | 상단 바에 녹색/주황 점, 클릭 시 수동 추출             |
| URL 진단     | 🔍 버튼 → CF 차단, PACKER, M3U8, 모듈 상태 상세       |
| 데이터 백업  | 📤 내보내기 / 📥 가져오기 (JSON, 병합 방식)           |
| 항상 위      | 📌 버튼 → pywebview `window.on_top`                   |
| 단축키 안내  | 토글 패널, 바깥 클릭 닫기                             |
| 창 크기 저장 | resize 이벤트 1초 디바운스 → sendBeacon               |

---

## 9. 키보드 단축키

| 키        | 동작                                |
| --------- | ----------------------------------- |
| `Space`   | 재생/일시정지                       |
| `←`       | 뒤로 건너뛰기 (설정값, 기본 10초)   |
| `→`       | 앞으로 건너뛰기 (설정값, 기본 10초) |
| `Shift+←` | 짧게 뒤로 (설정값, 기본 5초)        |
| `Shift+→` | 짧게 앞으로 (설정값, 기본 5초)      |
| `↑`       | 볼륨 +5%                            |
| `↓`       | 볼륨 -5%                            |
| `M`       | 음소거 토글                         |
| `F`       | 전체 화면 토글                      |
| `Shift+N` | 다음 영상                           |
| `Shift+P` | 이전 영상                           |
| `,`       | 이전 프레임 (1/30초, 정지 중)       |
| `.`       | 다음 프레임 (1/30초, 정지 중)       |

---

## 10. 개발 히스토리 (시행착오 기록)

### Phase 1: 기본 구조 (성공)

- Flask + yt-dlp 백엔드, HLS.js 프론트엔드로 시작
- 대기열, 재생 위치 기억, 히트맵, 키보드 단축키 구현

### Phase 2: Cloudflare 우회 (시행착오 많음)

**시도 1: 단순 requests** → 403 Forbidden (CF 차단)

**시도 2: rookiepy + DrissionPage** → ⚠️ **심각한 문제 발생**

- `cryptography` → Rust 컴파일러 필요 → **시스템 메모리 폭주, 브라우저 크래시, 강제 재부팅**
- **교훈: Rust 컴파일이 필요한 패키지는 절대 사용하지 말 것**

**시도 3: curl_cffi (최종 채택)** → ✅ 성공

- TLS 핑거프린트 위장 + 브라우저 cf_clearance 쿠키 전송

### Phase 3: P.A.C.K.E.R. 디코딩 (핵심 난관)

- P.A.C.K.E.R.는 URL을 base-62 인코딩 토큰으로 표현 → 단순 regex 불가
- 3단계 디코딩 + 키워드 재구성 방식으로 해결

### Phase 4: 기능 확장 (3차례 대규모 개선)

- **1차**: 설정 시스템, 다운로드 기능, 자동 저장, 항상 위, 화질 선택
- **2차**: 재생 위치 복원, 볼륨 저장, 클릭 재생/정지, 더블클릭 대기열, 추출 캐시, 드래그 앤 드롭 URL
- **3차**: 다운로드 파일명, 재생 속도, 다운로드 대기열, 완료 배지, 드래그 정렬, 정보 패널, 내부 쿠키 관리

### Phase 5: 성능 최적화 + 다운로드 UI

- **M3U8 콘텐츠 캐시** (30분 TTL): CDN에서 받은 M3U8을 메모리에 캐시, 상대URL→절대URL 변환 포함
- **백그라운드 사전추출**: 서버 시작 시 `stream_url` 없는 항목 자동 추출 + M3U8 사전 캐시
- **URL 만료 자동 대응**: M3U8 로드 실패(403) 시 자동 재추출 + 캐시 갱신
- **HLS.js 빠른 시작**: 버퍼 4초, Worker 활성화, 대역폭 테스트 건너뛰기, 5Mbps 가정
- **다운로드 패널**: 요약 한 줄 → 개별 항목 리스트 (제목 + 아이콘 + 퍼센트 + 프로그레스 바)

### Phase 6: 검색 & 관련 영상 (완료)

- **검색 API + UI**: MissAV 키워드 검색, 별도 search.html 페이지 (레거시)
- **관련 영상**: 정보 패널에 관련 영상 비동기 표시 + 대기열 추가 버튼
- **비디오 카드 파서**: `_parse_video_cards()` — 범용 MissAV HTML 비디오 카드 파싱

### Phase 7: 사이트 브라우저 + 카테고리 관리 (완료)

- **사이트 브라우저**: 검색 창을 커스텀 UI 대신 MissAV 사이트를 직접 pywebview 내장 브라우저로 탐색하는 방식으로 전환
  - `BrowseAPI` 클래스: pywebview `js_api` 브릿지를 통해 JS↔Python 직접 통신 (`add_to_queue`, `get_queue_urls`, `get_queue_count`, `open_new_tab`)
  - JS 인젝션: 매 페이지 로드마다 `evaluate_js()`로 플로팅 툴바 + 카드별 [+] 오버레이 버튼 주입
  - 영상 카드 자동 감지: `MutationObserver` (300ms 디바운스)로 동적 콘텐츠에도 대응
  - 현재 대기열 상태 실시간 동기화 (추가됨 표시)
  - SmartScreen 경고 비활성화: `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 환경변수
- **카테고리 관리**: 대기열 항목을 카테고리별로 정리
  - 카테고리 CRUD API (생성/수정/삭제/순서변경)
  - 카테고리 탭 바: 전체/미분류/각 카테고리별 필터링 + 항목 수 표시
  - 대기열 아이템에 카테고리 인디케이터(색상 점) + 드롭다운으로 카테고리 변경
  - 카테고리 관리 모달: 추가/이름변경/삭제

### Phase 7-B: 브라우저 확장 + 데이터 안전 (완료)

- **강제 인젝션 버튼** (🔧): 툴바에 아이콘 버튼 — 모든 `data-sp-done` 속성 초기화 후 카드 버튼 강제 재주입
- **새로고침 버튼** (↻): 툴바에 아이콘 버튼 — `location.reload()` 실행
- **커스텀 우클릭 메뉴**: 기본 브라우저 우클릭 대체
  - 링크: 새 탭에서 열기 / 링크 주소 복사 / 대기열에 추가 (영상 링크)
  - 텍스트 선택: 텍스트 복사
  - 공통: 뒤로/앞으로/새로고침/페이지 URL 복사
- **새 탭/창 지원**: `_open_browse_tab()` 함수로 새 pywebview 창 생성
  - 툴바 ⧉ 버튼 → 현재 페이지 새 창
  - Ctrl+클릭 / 중간버튼 클릭 → 링크를 새 창으로
  - 우클릭 메뉴 → '새 탭에서 열기'
  - 새 창도 동일한 `js_api` + JS 인젝션 적용
- **자동저장 + 이중백업 시스템**:
  - `_save_data()`: 저장 전 `.bak` → `.bak2` 순환, `data.json` → `.bak` 복사, 임시파일에 쓰고 rename (안전 쓰기)
  - `_load_data()`: `data.json` 손상 시 `.bak` → `.bak2` 순서로 자동 복구
  - `_periodic_backup()`: 5분마다 데몬 스레드가 자동 백업
  - `atexit` 핸들러: 종료 시 최종 저장
- **리소스 최적화**:
  - MutationObserver 300ms 디바운스 (매 DOM 변경마다 실행 방지)
  - 카드 버튼 재검사 setInterval 2초 → 3초
  - 메인 앱 외부 추가 감지 폴링 3초 → 5초 + `document.hidden` 시 스킵

### Phase 8: 사이트 창 재생 + 광고 차단 (완료)

- **사이트 창 재생** (`/api/open-tab`): 정보 패널의 영상 URL을 클릭하면 MissAV 사이트에서 직접 재생
  - 내장 HLS 플레이어의 30초~1분 로딩 지연을 우회하는 대안
  - `POST /api/open-tab` — URL을 `_open_browse_tab()`으로 새 pywebview 사이트 창 생성
  - `app.js`: 정보 패널 URL을 `<a target="_blank">` 대신 `.info-open-site` 클래스 + 이벤트 위임으로 변경
  - pywebview 미사용 시 `window.open()` 브라우저 폴백 자동 적용
- **5단계 광고 차단** (`_BROWSE_INJECT_JS` 상단): 사이트 창에서 영상 재생 시 광고 팝업이 외부 브라우저로 열리는 문제 해결
  - **1단계: `window.open()` 오버라이드 (fake window)** — `_makeFakeWindow()` 함수가 가짜 window 객체를 반환. 속성/메서드(`closed, close, focus, document, location, setTimeout` 등)를 모방하여 광고 스크립트가 팝업이 성공한 것으로 인식. 같은 도메인이든 외부든 **모든 window.open()을 차단**하되 현재 페이지를 이동시키지 않음. 2초 후 `closed=true`로 자동 설정. 이전 방식(`location.href` 이동)은 현재 페이지가 광고로 전환되는 치명적 버그가 있었음
  - **2단계: 광고 DOM 요소 주기적 제거** — `div[id*=pop]`, `div[class*=overlay]`, `div[id*=ad-]`, `iframe[src*=ad]`, `[style*=z-index:2147483647]` 등 17개 CSS 선택자로 광고 요소 탐지+제거. SP 툴바/컨텍스트 메뉴는 보호
  - **3단계: 클릭 하이재킹 차단** — 화면 50% 이상을 덮는 투명/반투명 div 감지 시 클릭 이벤트 차단+요소 제거. 외부 도메인 링크 클릭도 자동 차단
  - **4단계: `onbeforeunload` 잠금** — `Object.defineProperty()`로 광고 스크립트가 `onbeforeunload`에 끼어드는 것 방지
  - **5단계: 주기적 정리** — 1초 간격 × 10회 → 이후 5초 간격으로 지속적 광고 요소 클린업

### Phase 9: 대기열 관리 강화 + 추가 신뢰성 개선 (완료)

- **대기열 스크롤 버튼**: 대기열 헤더에 ▲/▼ 버튼 — 리스트 맨 위/맨 아래로 한 번에 스크롤
- **항목 개별 이동**: 각 대기열 항목에 호버 시 ⤒(맨 위)/⤓(맨 아래) 이동 버튼 표시
- **다중 선택 모드**: ☑ 버튼으로 선택 모드 토글 → 체크박스로 복수 항목 선택
  - **벌크 액션 바**: 선택 모드 활성화 시 상단에 액션 바 표시
  - 전체 선택/해제 토글
  - 선택 항목 맨 위/맨 아래로 일괄 이동 (`POST /api/queue/move`)
  - 선택 항목 카테고리 일괄 변경 (`POST /api/queue/bulk-category`)
  - 선택 항목 일괄 삭제 (`POST /api/queue/bulk-delete`)
- **중복 URL 추가 방지 강화**:
  - 서버 `POST /api/queue`: 중복 시 409 응답 + `{error, duplicate: true}` 반환 (기존: 묵시적 무시)
  - 클라이언트 `addToQueue()`: 서버 호출 전 로컬 대기열에서 URL 사전 체크
  - 관련 영상 추가 버튼: 중복 시 "이미 대기열에 있습니다" 메시지 표시
- **사이트 창 추가 신뢰성 개선**:
  - `BrowseAPI.add_to_queue()`: 추출 실패 시 최대 3회 재시도 (1초 간격)
  - 추출 전 중복 체크 선행 (불필요한 추출 방지)
  - 저장 후 검증 (`_load_data()`로 실제 저장 확인)
  - 실패 시 상세 에러 메시지 + 5초 뒤 재시도 가능하도록 버튼 복구
  - 카드 버튼/툴바 버튼: 추가 진행 상태 실시간 표시 (`⏳ 추가 중...`)
- **신규 API 엔드포인트 3개**:
  - `POST /api/queue/move` — 항목 IDs + position(top/bottom) → 일괄 이동
  - `POST /api/queue/bulk-delete` — 항목 IDs → 일괄 삭제 + playback/heatmap 정리
  - `POST /api/queue/bulk-category` — 항목 IDs + category → 일괄 카테고리 변경

---

## 11. 핵심 기술 상세

### 11.1 P.A.C.K.E.R. 난독화 구조

```javascript
eval(function (p, a, c, k, e, d) {
  // p = 템플릿 코드 (base-N 토큰 포함)
  // a = base (36 또는 62)
  // c = 키워드 수
  // k = 키워드 배열 ('|'로 분리)
  while (c--)
    if (k[c])
      p = p.replace(new RegExp("\\b" + c.toString(a) + "\\b", "g"), k[c]);
  return p;
});
```

### 11.2 `_unpack_packer()` 작동 방식

1. `kstr.split('|')` → keywords 배열
2. `pcode` 안의 모든 알파벳/숫자 토큰을 regex로 매칭
3. 각 토큰을 `_base_n_decode(token, base)` → 인덱스
4. `keywords[인덱스]`로 치환
5. 복원된 JS에서 M3U8 URL 검색

### 11.3 Cloudflare 우회 3단계

1. `curl_cffi` + Edge/Whale 브라우저 쿠키 (yt-dlp cookie jar)
2. `curl_cffi` + `cookies.txt` 파일
3. 일반 `requests` 폴백

- `cf_clearance` 쿠키가 핵심 (30분~수시간 유효)

### 11.4 HLS 스트림 프록시 (`/api/stream`)

1. 대기열의 `stream_url` 즉시 사용 (저장되어 있으면)
2. 없으면 `_extract_info()` → `stream_url` 추출 후 대기열에 저장
3. M3U8: `_fetch_and_cache_m3u8()` → 캐시 hit 시 즉시 반환
4. 캐시 miss/만료: CDN에서 가져와서 상대→절대 URL 변환 후 캐시
5. 403 에러: 자동 재추출 → 새 URL로 재시도
6. MP4 등: 64KB 청크 스트리밍 (Range 요청 지원)

---

## 12. 데이터 저장 구조 (data.json)

```json
{
  "queue": [{
    "id": "MD5해시",
    "url": "원본 URL",
    "title": "영상 제목",
    "duration": 3600,
    "thumbnail": "썸네일 URL",
    "added_at": "ISO 날짜",
    "stream_url": "M3U8 CDN URL (캐시용)",
    "http_headers": {"Referer": "...", "Origin": "..."},
    "variants": [{"resolution": "1920x1080", "bandwidth": 5000000}]
  }],
  "playback": { "항목ID": { "position": 1234.5, "updated_at": "ISO 날짜" } },
  "heatmaps": { "항목ID": { "123": 5, "124": 3 } },
  "settings": { ...DEFAULT_SETTINGS 오버라이드... }
}
```

- 파일 기반, `_data_lock = threading.Lock()` 쓰기 보호
- 항목 ID: URL의 MD5 해시
- **이중 백업**: 저장 시 `data.json.bak` → `data.json.bak2` 순환, `data.json` → `data.json.bak` 복사 후 안전 쓰기 (tmp → rename)
- **크래시 복구**: `_load_data()`가 `data.json` 손상 시 `.bak` → `.bak2` 순서로 자동 복구 시도
- **주기적 백업**: 5분마다 daemon 스레드가 자동 저장, `atexit`으로 종료 시 최종 저장

---

## 13. 의존성 & 설치

### Python 패키지

| 패키지                 | 용도                      | 비고     |
| ---------------------- | ------------------------- | -------- |
| `flask>=3.0`           | 웹 서버                   |          |
| `yt-dlp>=2024.0`       | 영상 추출 + 브라우저 쿠키 |          |
| `requests>=2.31`       | HTTP 폴백                 |          |
| `beautifulsoup4>=4.12` | HTML 파싱                 |          |
| `pywebview>=5.0`       | 데스크탑 창               | 선택사항 |
| `curl_cffi>=0.7`       | CF 우회 TLS 핑거프린트    | 핵심!    |

### ⚠️ 절대 설치하면 안 되는 패키지

| 패키지         | 이유                                              |
| -------------- | ------------------------------------------------- |
| `rookiepy`     | `cryptography` → Rust 컴파일 → 시스템 크래시 위험 |
| `DrissionPage` | 동일 문제                                         |

### CDN 의존성

- `hls.js` v1.5.7 — `https://cdn.jsdelivr.net/npm/hls.js@1.5.7`

---

## 14. 실행 방법

### 간편 실행

```
start.bat 더블클릭
```

자동으로: venv 생성 → 위험 패키지 제거 → pip install → 앱 실행

### 수동 실행

```bash
cd T:\VSCODE\StreamPlayer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

### 서버만 실행 (디버그)

```bash
python server.py
# http://localhost:5000 에서 브라우저로 접속
```

---

## 15. 알려진 제한/주의사항

### Cloudflare 관련

- 첫 사용 시 Edge/Whale에서 대상 사이트에 한 번 접속하여 CF 체크 통과 필요
- `cf_clearance` 만료 시 다시 브라우저에서 접속 필요 (30분~수시간 주기)
- CF 정책 변경 시 `curl_cffi`의 `impersonate` 값 업데이트 필요할 수 있음

### P.A.C.K.E.R. 관련

- 사이트가 P.A.C.K.E.R. 구조를 변경하면 키워드 인덱스 패턴 조정 필요
- `_unpack_packer()`가 범용적이므로 대부분의 변경에 대응 가능

### 기술적 제한

- `data.json` 동시 접근: 쓰기만 Lock 보호, 읽기는 보호 안 됨 (race condition 가능)
- 다운로드 상태가 메모리에만 저장 — 서버 재시작 시 손실
- 포트 `127.0.0.1:5000` 하드코딩 (충돌 시 수동 변경 필요)
- Whale 브라우저는 `chromium`으로 매핑 (완전 호환은 아닐 수 있음)
- 스트림 프록시 64KB 청크 (대역폭 제한 가능)

### 사용자 환경

- 코딩 지식이 없는 사용자 → 비기술적 안내, `start.bat` 원클릭 방식 필수
- Windows 환경만 지원 (브라우저 감지 경로가 Windows 전용)

---

## 16. 핵심 코드 포인터 (빠른 참조)

| 작업                   | 파일      | 함수/위치                                                        |
| ---------------------- | --------- | ---------------------------------------------------------------- |
| CF 우회                | server.py | `_fetch_page_with_cf_bypass()`                                   |
| 브라우저 감지          | server.py | `_detect_browser()`                                              |
| 브라우저 쿠키 추출     | server.py | `_build_cookie_jar_from_browser()`                               |
| P.A.C.K.E.R. 언팩      | server.py | `_unpack_packer()`                                               |
| 키워드 URL 재구성      | server.py | `_reconstruct_m3u8_from_keywords()`                              |
| 커스텀 추출 메인       | server.py | `_custom_extract()`                                              |
| M3U8 캐시              | server.py | `_fetch_and_cache_m3u8()`                                        |
| 백그라운드 사전추출    | server.py | `_background_preextract()`                                       |
| HLS 프록시             | server.py | `/api/stream` route                                              |
| 다운로드 워커          | server.py | `_do_download_worker()`                                          |
| 다운로드 대기열        | server.py | `_process_download_queue()`                                      |
| 진단 API               | server.py | `/api/debug` route                                               |
| 설정 관리              | server.py | `DEFAULT_SETTINGS`, `/api/settings`                              |
| 쿠키 추출 API          | server.py | `/api/cookies/extract`                                           |
| 비디오 카드 파싱       | server.py | `_parse_video_cards()` (~L800)                                   |
| 관련 영상 추출         | server.py | `_extract_related_videos()` (~L912)                              |
| 검색 API               | server.py | `/api/search` (~L948)                                            |
| 관련 영상 API          | server.py | `/api/related` (~L998)                                           |
| 검색 창 열기 API       | server.py | `/api/open-search` (~L1560)                                      |
| 사이트 창 재생 API     | server.py | `/api/open-tab` (~L1721)                                         |
| 광고 차단 (5단계)      | server.py | `_BROWSE_INJECT_JS` 상단 `blockAds()` (~L130-235)                    |
| 새 탭 열기             | server.py | `_open_browse_tab()` (~L522)                                     |
| 자동백업 스레드        | server.py | `_periodic_backup()`, `_shutdown_save()` (~L2500)                |
| 영상 재생              | app.js    | `playItem()`                                                     |
| HLS.js 설정            | app.js    | `new Hls({...})`                                                 |
| 다운로드 패널 렌더링   | app.js    | `renderDownloadList()`, `_renderDlItem()`                        |
| 대기열 렌더링          | app.js    | `renderQueue()`                                                  |
| 설정 모달              | app.js    | `btnSettingsSave` 이벤트                                         |
| 진단 UI                | app.js    | `btnDiag` 이벤트 핸들러                                          |
| 검색 버튼 핸들러       | app.js    | `btnSearchWin` 클릭 (~L1265)                                     |
| 사이트 창 재생 핸들러 | app.js    | `.info-open-site` 이벤트 위임 (~L389)                          |
| 정보패널 관련 영상     | app.js    | `showItemInfo()` (~L294), `loadRelatedForInfoPanel()` (~L318)    |
| 검색 창 프론트엔드     | search.js | `doSearch()`, `renderResults()`, `addToQueue()`, `showRelated()` |
| 창 상태 복원 + 검색 창 | app.py    | `main()`                                                         |

---

## 16-A. 검색 & 관련 영상 기능 (신규 — ⚠️ 미해결 이슈 있음)

### 검색 기능 개요

Hitomi Downloader처럼 별도 창에서 MissAV를 키워드 검색하고, 결과를 메인 플레이어 대기열에 추가하는 기능.

### 구현 완료된 부분

#### 백엔드 (`server.py`)

| 함수/라우트                          | 위치   | 용도                                                                    |
| ------------------------------------ | ------ | ----------------------------------------------------------------------- |
| `_parse_video_cards(soup, base_url)` | ~L800  | MissAV HTML에서 비디오 카드 파싱 (썸네일/제목/길이/URL). 검색/관련 공통 |
| `_extract_related_videos(url)`       | ~L912  | 비디오 페이지에서 관련 영상 추출 (CF 우회 → 파싱)                       |
| `GET /api/search`                    | ~L948  | 키워드 검색. q/page/sort 파라미터. 다음페이지 여부 반환                 |
| `GET /api/related`                   | ~L998  | 비디오 URL → 관련 영상 목록 반환                                        |
| `POST /api/open-search`              | ~L1008 | 검색 창 show() 호출 (pywebview 네이티브)                                |
| `GET /search`                        | ~L940  | search.html 서빙                                                        |

#### 검색 창 UI (별도 페이지)

- **`templates/search.html`** (63줄): 검색 입력, 정렬 셀렉트(관련순/최신/조회/좋아요), 결과 그리드, 페이지네이션, 관련 영상 슬라이드 패널
- **`static/search.js`** (233줄): `doSearch()`, `renderResults()`, `addToQueue()`, `showRelated()`, 기존 대기열 추적(중복 방지), 페이지네이션
- **`static/search.css`** (330줄): 다크 테마, 비디오 카드 그리드, 관련 패널 슬라이드 애니메이션

#### 메인 창 통합

- **`index.html`**: `<button id="btnSearch">🔍</button>` 추가 (상단 바 우측, btnOnTop 앞)
- **`app.js`** (~L1265): 🔍 버튼 클릭 → `/api/open-search` POST → pywebview 창 show / 실패 시 `window.open` 팝업 폴백
- **`app.js`** L294 `showItemInfo()`: 정보 패널에 "📎 관련 영상" 섹션 추가 (비동기 로드)
- **`app.js`** L318 `loadRelatedForInfoPanel()`: `/api/related` 호출 → 관련 영상 최대 10개 표시 (썸네일+제목+길이+추가버튼)
- **`app.js`** L345: `infoPanelBody` 이벤트 위임 — `.info-related-add` 버튼 클릭 → 대기열 추가
- **`style.css`**: `.info-related-section`, `.info-related-item`, `.info-related-thumb`, `.info-related-add` 등 스타일 추가

### ❌ 미해결: pywebview 네이티브 검색 창이 안 열림

**증상**: 🔍 버튼 클릭 시 네이티브 pywebview 창이 아니라 **브라우저 탭**이 열림

**시도한 접근법과 실패 이유**:

#### 시도 1: Flask 라우트에서 `webview.create_window()` 직접 호출

- 실패: Flask 라우트는 백그라운드 스레드에서 실행되고, `webview.start()` 이전에는 `guilib`이 `None`

#### 시도 2: `threading.Event()` + watcher 데몬 스레드

- `server.py`에 `_search_window_request = threading.Event()` 플래그
- `app.py`에 `_search_window_watcher()` 스레드가 0.3초마다 폴링 → `webview.create_window()` 호출
- 실패: 브라우저만 열림. 정확한 실패 원인 디버그 되지 않음
- Windows에서 pywebview WinForms 백엔드가 COM/STA 환경을 요구하는 것과 관련 가능성

#### 시도 3 (현재 코드): `hidden=True`로 미리 생성 + `show()`

- `app.py`에서 `webview.start()` 전에 검색 창을 `hidden=True`로 생성
- `closing` 이벤트에서 `hide()` + `return False`로 파괴 방지
- `/api/open-search`에서 `_search_window.show()` 호출
- **아직 테스트 안 됨 / 여전히 브라우저만 열릴 수 있음**
- 우려: `server.py`에서 `show()` 호출 시 `window.gui`가 초기화 안 됐거나, JS의 `if (!res.ok)` 분기로 `window.open` 폴백 발동

**핵심 발견 (pywebview 소스 분석 — `c:\Users\weize\...\webview\`)**:

```
webview/__init__.py L419-427:
  - create_window()에서 guilib 초기화 + 비메인스레드이면 guilib.create_window() 호출

webview/platforms/winforms.py L725-770:
  - master 윈도우: STA 스레드 생성 → app.Run() (이벤트 루프)
  - child 윈도우: _main_window_created.wait() → i.Invoke(create) (GUI 스레드 마샬링)

winforms.py L453 show():
  - InvokeRequired면 Invoke() 사용 → thread-safe
```

**추천 해결 방향** (다음 세션):

1. **디버그 우선**: `python app.py` 실행 후 콘솔에서 에러 메시지 확인. `_search_window.show()` 호출 시 예외가 발생하는지, 아니면 JS 단에서 `window.open` 폴백이 실행되는 건지 구분
2. **`webview.start(func=callback)` 방식**: `start()`의 `func` 파라미터에 콜백 전달 → `guilib` 초기화 이후 시점에서 `create_window()` 호출 가능
3. **`hidden=True` 타이밍 수정**: `webview.start()` 전에 `set_search_window()` 호출 시 `window.gui`가 아직 없을 수 있음 → `func` 콜백 안에서 `set_search_window()` 호출하도록 변경
4. **`webview.start()` 이후의 `create_window()`**: pywebview 문서상 `start()` 호출 후 다른 스레드에서 `create_window()` 가능 → `func` 콜백에서 이벤트 대기 루프 구현

### 현재 app.py 검색 창 관련 코드:

```python
# 검색 윈도우 (숨긴 상태로 미리 생성)
search_window = webview.create_window(
    title="StreamPlayer 검색",
    url="http://127.0.0.1:5000/search",
    width=1000, height=700,
    min_size=(600, 400),
    text_select=True, hidden=True,
)

# X 버튼 → 숨기기만
def _on_search_closing():
    search_window.hide()
    return False
search_window.events.closing += _on_search_closing

from server import set_webview_window, set_search_window
set_webview_window(window)
set_search_window(search_window)

webview.start()
```

### 현재 server.py 검색 창 API:

```python
_search_window = None

def set_search_window(window):
    global _search_window
    _search_window = window

@app.route("/api/open-search", methods=["POST"])
def open_search_window():
    if not _search_window:
        return jsonify({"ok": False, "error": "pywebview not available"})
    try:
        _search_window.show()
        return jsonify({"ok": True, "action": "shown"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
```

---

## 17. 앞으로 개선할 점 (TODO)

- [x] **✅ pywebview 네이티브 검색 창 수정** — 동적 생성 방식으로 해결
- [x] **✅ 사이트 브라우저 전환** — 커스텀 검색 UI 대신 MissAV 사이트 직접 탐색 + JS 인젝션
- [x] **✅ 카테고리 관리** — 대기열 항목 카테고리별 분류/필터링/관리
- [x] **✅ 강제 인젝션 버튼** — [+] 버튼 안 보일 때 강제 재주입
- [x] **✅ 새로고침 버튼** — 페이지 새로고침
- [x] **✅ 커스텀 우클릭 메뉴** — 링크/텍스트 복사, 새 탭 열기, 대기열 추가
- [x] **✅ 새 탭/창 지원** — Ctrl+클릭, 중간버튼, 우클릭으로 새 pywebview 창
- [x] **✅ 자동 저장 + 이중 백업** — .bak/.bak2 순환, 안전 쓰기, 크래시 복구, 5분 주기 백업, atexit 종료 저장
- [x] **✅ 리소스 최적화** — MutationObserver 디바운스, 폴링 주기 완화, document.hidden 스킵
- [x] **✅ 사이트 창 재생** — 정보 패널 URL 클릭 시 pywebview 사이트 창에서 영상 직접 재생 (`/api/open-tab`)
- [x] **✅ 광고 차단** — 사이트 창에서 5단계 광고 차단 (팝업/오버레이/클릭하이재킹/외부링크/beforeunload)
- [x] **✅ 광고 차단 개선 (fake window)** — `window.open()` 오버라이드를 `return null` → fake window 객체 반환으로 변경. 현재 페이지 이동 없이 광고 스크립트를 속여 영상 재생 정상화
- [x] **✅ 대기열 관리 강화** — 스크롤 ▲/▼ 버튼, 항목 개별 맨위/맨아래 이동 버튼, 다중 선택 모드 + 벌크 이동/삭제/카테고리 변경
- [x] **✅ 중복 URL 방지 강화** — 서버 409 응답, 클라이언트 사전 체크, 관련 영상 중복 표시
- [x] **✅ 사이트 창 추가 신뢰성** — 3회 재시도, 저장 검증, 상세 에러 표시, 실패 시 재시도 가능

### Phase 10: HLS 프록시 복원 + 5단계 백업 + 대기열 UX 강화 (완료)

- **HLS 세그먼트 프록시 복원**: `/api/ts-proxy` 엔드포인트로 CDN 헤더(Referer/Origin) 주입, `_fetch_and_cache_m3u8()`에서 세그먼트 URL을 프록시 경로로 리라이트, 캐시 TTL 확장 (6h/2h)
- **5단계 시간차 백업 시스템**: `backups/auto/` (매 저장), `backups/10min/`, `backups/30min/`, `backups/1hour/`, `backups/startup/` (시작 시). 데이터 급감 시 `.safety` 자동 백업
- **중복 URL 필터 버튼** (🔁): 대기열 헤더에 추가, URL 슬러그 비교로 로케일 접두어(`/ko/`, `/en/` 등) 차이 무시
- **카드 추가 무한 재시도**: 사이트 창 [+] 버튼 실패 시 5초 간격 자동 재시도 (최대 30회), 중복이면 즉시 완료
- **추가 대기열 상태 UI**: 사이트 창 툴바에 `대기: 3/10` 카운터 + pulse 애니메이션
- **이동 시 스크롤 유지**: 맨위/맨아래 이동 버튼 클릭 시 현재 스크롤 위치 보존
- **썸네일 호버 확대**: 대기열 썸네일에 마우스 호버 시 2.5배 확대 (z-index 팝아웃)
- **컨텍스트 메뉴 카테고리 이동**: 우클릭 메뉴에 카테고리 목록 동적 표시 + 빠른 이동
- **우클릭 → 사이트 방문**: pywebview 내장 탭으로 열기 (외부 브라우저 대신)
- [ ] CF 쿠키 만료 자동 감지 + 사용자 알림
- [ ] data.json 읽기 Lock 추가 (동시 접근 안정성)
- [ ] 다운로드 상태 영속 저장 (서버 재시작 시 복원)
- [ ] 다크/라이트 테마 전환
- [ ] 브라우저 감지 macOS/Linux 확장
- [ ] 포트 충돌 시 자동 대체 포트 탐색
- [ ] 전체 프로그램 가다듬기 (UI 폴리싱, 에러 처리 개선)

---

## 18. 트러블슈팅 가이드

| 증상                             | 원인                                     | 해결                                                      |
| -------------------------------- | ---------------------------------------- | --------------------------------------------------------- |
| "Cloudflare가 차단하고 있습니다" | cf_clearance 만료                        | Edge에서 사이트 접속 후 재시도                            |
| M3U8 URL 없음                    | P.A.C.K.E.R. 구조 변경                   | 서버 콘솔 로그 확인, 키워드 패턴 조정                     |
| 영상 로드 안 됨                  | M3U8 URL 만료                            | 자동 재추출 시도됨. 반복 시 대기열에서 삭제 후 재추가     |
| 재생 시작이 느림                 | stream_url 미저장 (첫 추출)              | 2번째 재생부터 빠름. 백그라운드 사전추출 확인             |
| `pip install` 실패               | Rust/C 컴파일러                          | 해당 패키지 제거, curl_cffi만 사용                        |
| pywebview 창 안 뜸               | pywebview 미설치                         | 자동 브라우저 폴백, 무시 가능                             |
| 쿠키 감지 안 됨                  | 브라우저 미지원                          | `_detect_browser()` 경로 추가                             |
| 다운로드 패널 안 보임            | 다운로드 진행 없음                       | 다운로드 버튼 클릭 후 표시됨                              |
| 포트 5000 충돌                   | 다른 앱이 사용 중                        | 해당 앱 종료 또는 server.py 포트 변경                     |
| 참조 원본                        | hitomi.py                                | `deobfuscate_missav_source()`, `getx()`                   |
| 🔍 검색 클릭 시 브라우저 열림    | pywebview guilib 미초기화 시 show() 예외 | 해결됨: 동적 create_window() 방식. 16-A절 참조            |
| [+] 버튼이 안 보임               | JS DOM 변경 시점 놓침                    | 🔧 강제 인젝션 버튼으로 수동 재주입 가능                  |
| SmartScreen 경고                 | WebView2 SmartScreen 기본 활성화         | WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 환경변수로 비활성화 |
| data.json 손상                   | 비정상 종료/쓰기 중 크래시               | 이중 백업(.bak/.bak2) + 안전 쓰기(tmp→rename) + 자동 복구 |
| 사이트 창에서 광고 팝업          | window.open() 광고 트리거                | 5단계 광고 차단 자동 적용 (Phase 8). 일부 놓치면 새로고침 |
| 내장 플레이어 로딩 느림          | HLS 추출+프록시 지연 (30초~1분)          | 정보 패널 URL → 사이트 창 재생 기능 사용 (즉시 재생)      |

---

_이 문서는 프로젝트의 전체 맥락을 담고 있습니다. 새로운 AI 또는 개발자가 이 문서를 읽으면 현재 상태, 과거 시행착오, 아키텍처를 모두 파악할 수 있습니다._
