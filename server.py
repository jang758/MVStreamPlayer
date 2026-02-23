"""
StreamPlayer - 스트리밍 비디오 플레이어 백엔드 서버
쿠키 기반 인증을 지원하며 yt-dlp를 통해 영상 스트림을 추출합니다.
MissAV 등 P.A.C.K.E.R. 난독화 사이트는 커스텀 추출기로 폴백합니다.
"""

import os
import json
import time
import hashlib
import re
import threading
import urllib.parse
from pathlib import Path
from flask import Flask, request, jsonify, render_template, Response, send_file, stream_with_context
import yt_dlp
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # 정적 파일 캐시 비활성화

@app.after_request
def _add_no_cache_headers(response):
    """정적 파일에 캐시 방지 헤더 추가 (WebView2 캐시 무효화)"""
    if 'static' in request.path or request.path == '/':
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

BASE_DIR = Path(__file__).parent
COOKIES_FILE = BASE_DIR / "cookies.txt"
DOWNLOADS_DIR = BASE_DIR / "downloads"
DATA_FILE = BASE_DIR / "data.json"

DOWNLOADS_DIR.mkdir(exist_ok=True)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'

# MissAV 등 대상 도메인
CUSTOM_DOMAINS = ['missav.ws', 'missav.ai', 'missav.com', 'njavtv.com']

# pywebview 창 참조 (항상 위 기능 등)
_webview_window = None
_search_window = None
_webview_ready = threading.Event()   # guilib 초기화 완료 시그널

def set_webview_window(window):
    global _webview_window
    _webview_window = window

def set_search_window(window):
    global _search_window
    _search_window = window


# ──────────────────────────────────────────────
# 사이트 브라우저 - pywebview JS API 브릿지
# ──────────────────────────────────────────────

class BrowseAPI:
    """검색/탐색 창에서 pywebview JS 브릿지를 통해 호출되는 API.
    MissAV 사이트를 직접 탐색하면서 대기열에 추가하는 기능을 제공합니다."""

    def add_to_queue(self, url):
        """영상 URL을 대기열에 추가합니다. (JS에서 호출)
        추출 실패 시 최대 2회 재시도합니다."""
        if not url or not url.strip():
            return {"error": "URL이 비어있습니다."}
        url = url.strip()
        # 쿼리 파라미터 제거 (missav URL 정규화)
        if '?' in url:
            url = url.split('?')[0]

        uid = _url_id(url)
        # 중복 체크 먼저
        data = _load_data()
        if any(item["id"] == uid for item in data["queue"]):
            return {"error": "이미 대기열에 있습니다.", "duplicate": True, "title": url}

        # 추출 시도 (최대 2회 재시도)
        last_error = None
        info = None
        for attempt in range(3):
            try:
                info = _extract_info(url)
                break
            except Exception as e:
                last_error = str(e)
                print(f"  [탐색창] 추출 시도 {attempt+1}/3 실패: {last_error}")
                if attempt < 2:
                    time.sleep(1)

        if info is None:
            return {"error": f"영상 정보 추출 실패 (3회 시도): {last_error}"}

        entry = {
            "id": uid,
            "url": url,
            "title": info.get("title", url),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "added_at": time.time(),
            "stream_url": info.get("url", ""),
            "http_headers": info.get("http_headers", {}),
            "variants": info.get("_variants", []),
        }

        # 다시 한번 중복 체크 (추출 중 다른 곳에서 추가되었을 수 있음)
        data = _load_data()
        if any(item["id"] == uid for item in data["queue"]):
            return {"error": "이미 대기열에 있습니다.", "duplicate": True, "title": entry["title"]}
        data["queue"].append(entry)
        _save_data(data)

        # 저장 검증
        verify = _load_data()
        saved = any(item["id"] == uid for item in verify["queue"])
        if not saved:
            return {"error": "저장 실패 — 다시 시도해 주세요.", "save_failed": True}

        print(f"  [탐색창] 대기열 추가: {entry['title'][:60]}")
        return {"ok": True, "title": entry["title"], "id": uid}

    def get_queue_urls(self):
        """대기열에 있는 URL 목록을 반환합니다. (JS에서 호출)"""
        data = _load_data()
        return [item["url"] for item in data["queue"]]

    def get_queue_count(self):
        """대기열 항목 수를 반환합니다. (JS에서 호출)"""
        data = _load_data()
        return len(data["queue"])

    def open_new_tab(self, url):
        """새 탐색 창(탭)을 열어 지정 URL로 이동합니다. (JS에서 호출)"""
        if not url:
            return {"error": "URL이 비어있습니다."}
        try:
            _open_browse_tab(url)
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

_browse_api = BrowseAPI()


# ── 사이트 브라우저용 인젝션 JavaScript ──
_BROWSE_INJECT_JS = r"""
(function() {
    'use strict';
    if (document.getElementById('sp-toolbar')) return;

    /* ══════════════════════════════════════
       광고 차단 — window.open / 팝업 / 리다이렉트 방지
       ══════════════════════════════════════ */
    (function blockAds() {
        /* 1) window.open 완전 차단 — fake window 객체 반환으로 광고 스크립트를 속임 */
        const _origOpen = window.open;
        function _makeFakeWindow(url) {
            const fw = {
                closed: false, opener: window, name: '',
                location: { href: url || '', replace: function(){}, assign: function(){} },
                document: { write: function(){}, writeln: function(){}, close: function(){}, open: function(){ return this; },
                             readyState: 'complete', createElement: function(){ return document.createElement('div'); },
                             body: document.createElement('div'), head: document.createElement('head') },
                navigator: window.navigator,
                close: function() { fw.closed = true; },
                focus: function() {}, blur: function() {},
                postMessage: function() {},
                addEventListener: function() {}, removeEventListener: function() {},
                dispatchEvent: function() { return true; },
                setTimeout: function(fn,ms){ return window.setTimeout(fn,ms); },
                setInterval: function(fn,ms){ return window.setInterval(fn,ms); },
                clearTimeout: function(id){ window.clearTimeout(id); },
                clearInterval: function(id){ window.clearInterval(id); },
                Math: window.Math, Date: window.Date, JSON: window.JSON,
                atob: window.atob, btoa: window.btoa,
                innerWidth: 1024, innerHeight: 768,
                screen: window.screen,
                XMLHttpRequest: window.XMLHttpRequest,
                fetch: window.fetch,
            };
            /* 자동으로 잠시 후 닫힌 것으로 표시 */
            setTimeout(() => { fw.closed = true; }, 2000);
            return fw;
        }
        window.open = function(url, target, features) {
            console.log('[SP AdBlock] window.open 차단 (fake window 반환):', url && url.substring(0, 80));
            return _makeFakeWindow(url);
        };

        /* 2) 광고 오버레이 / 팝업 레이어 주기적 제거 */
        function removeAdElements() {
            /* 전형적인 광고 오버레이 선택자 */
            const adSelectors = [
                'div[id*="pop"]', 'div[class*="pop"]',
                'div[id*="overlay"]', 'div[class*="overlay"]',
                'div[id*="banner"]', 'div[class*="banner"]',
                'div[id*="ad-"]', 'div[class*="ad-"]',
                'div[id*="ads"]', 'div[class*="ads"]',
                'iframe[src*="ad"]', 'iframe[src*="pop"]',
                'iframe[src*="banner"]',
                'a[href*="redirect"]', 'a[href*="click"]',
                '.exo', '.exo_wrapper',
                '[id^="div-gpt-ad"]',
                'div[style*="z-index: 2147483647"]',
            ];
            adSelectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    /* SP 툴바 자체는 건드리지 않음 */
                    if (el.id === 'sp-toolbar' || el.closest('#sp-toolbar')) return;
                    if (el.id === 'sp-ctx-menu' || el.closest('#sp-ctx-menu')) return;
                    el.remove();
                });
            });
        }

        /* 3) 클릭 하이재킹 차단 — 동영상 영역 밖의 투명 오버레이 클릭 방지 */
        document.addEventListener('click', function(e) {
            const el = e.target;
            /* 투명 전체화면 div (광고 트리거) 감지 */
            if (el.tagName === 'DIV' || el.tagName === 'A') {
                const cs = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                /* 화면 대부분을 덮는 투명/반투명 div → 광고 */
                if (rect.width > window.innerWidth * 0.5 && rect.height > window.innerHeight * 0.5) {
                    if (parseFloat(cs.opacity) < 0.15 || cs.visibility === 'hidden' ||
                        cs.pointerEvents === 'auto' && cs.background === 'transparent' ||
                        cs.zIndex > 99999) {
                        e.stopPropagation();
                        e.preventDefault();
                        el.remove();
                        console.log('[SP AdBlock] 투명 오버레이 클릭 차단+제거');
                        return false;
                    }
                }
            }
            /* 외부 도메인 링크 클릭 차단 */
            const link = el.closest('a[href]');
            if (link) {
                try {
                    const href = link.href;
                    const u = new URL(href);
                    const dominated = ['missav.ws','missav.ai','missav.com','njavtv.com'];
                    const isSameSite = dominated.some(d => u.hostname.endsWith(d));
                    if (!isSameSite && !href.startsWith('javascript:')) {
                        /* 외부 광고 링크 */
                        e.stopPropagation();
                        e.preventDefault();
                        console.log('[SP AdBlock] 외부 링크 차단:', href.substring(0, 80));
                        return false;
                    }
                } catch {}
            }
        }, true);

        /* 4) beforeunload 시 광고 스크립트가 끼어드는 것 방지 */
        Object.defineProperty(window, 'onbeforeunload', {
            get: () => null,
            set: () => {},
            configurable: false,
        });

        /* 5) 주기적 광고 요소 정리 (1초 간격, 10회 → 이후 5초 간격) */
        let adCleanCount = 0;
        const adCleanTimer = setInterval(() => {
            removeAdElements();
            adCleanCount++;
            if (adCleanCount >= 10) {
                clearInterval(adCleanTimer);
                /* 이후 5초 간격으로 계속 */
                setInterval(removeAdElements, 5000);
            }
        }, 1000);

        console.log('[SP AdBlock] 광고 차단 활성화');
    })();

    /* ── 상태 ── */
    let addedUrls = new Set();
    let queueCount = 0;

    /* ── 비디오 URL 판별 (여러 패턴 대응) ── */
    function isVideoUrl(url) {
        try {
            const p = new URL(url, location.origin).pathname.replace(/\/+$/, '');
            const parts = p.split('/').filter(Boolean);
            if (parts.length === 0) return false;
            const slug = parts[parts.length - 1];
            if (!/[a-zA-Z]/.test(slug)) return false;
            if (!/-\d/.test(slug)) return false;
            if (slug.length < 4) return false;
            const exclude = ['search','genres','actresses','makers','labels','tags','uncensored-leak','today-hot','weekly-hot','monthly-hot','new','release','login','register','dm','playlist'];
            if (exclude.includes(slug) || exclude.some(ex => parts.includes(ex) && parts.indexOf(ex) === parts.length - 1)) return false;
            return true;
        } catch { return false; }
    }
    function getFullUrl(href) {
        try { return new URL(href, location.origin).href.split('?')[0]; }
        catch { return null; }
    }

    /* ── CSS ── */
    const style = document.createElement('style');
    style.textContent = `
        #sp-toolbar {
            position: fixed; bottom: 0; left: 0; right: 0; height: 40px;
            background: rgba(15,15,20,0.95); backdrop-filter: blur(12px);
            display: flex; align-items: center; padding: 0 12px;
            z-index: 2147483647; font-family: -apple-system, 'Segoe UI', sans-serif;
            color: #e0e0e0; gap: 6px; border-top: 1px solid rgba(74,158,255,0.3);
            box-shadow: 0 -2px 12px rgba(0,0,0,0.5);
        }
        #sp-toolbar .sp-brand {
            font-weight: 700; color: #4a9eff; font-size: 12px;
            white-space: nowrap; user-select: none;
        }
        #sp-toolbar .sp-btn {
            background: #4a9eff; color: #fff; border: none;
            padding: 4px 12px; border-radius: 4px; font-weight: 600;
            cursor: pointer; font-size: 11px; white-space: nowrap;
            transition: all 0.15s;
        }
        #sp-toolbar .sp-btn:hover { background: #6bb3ff; }
        #sp-toolbar .sp-btn.sp-added { background: #4caf50; cursor: default; }
        #sp-toolbar .sp-btn.sp-dup { background: #ff9800; cursor: default; }
        #sp-toolbar .sp-btn:disabled { opacity: 0.6; cursor: wait; }
        #sp-toolbar .sp-btn.sp-na { background: #555; color: #999; cursor: default; }
        #sp-toolbar .sp-icon-btn {
            background: none; border: 1px solid rgba(255,255,255,0.2);
            color: #ccc; width: 28px; height: 28px; border-radius: 4px;
            cursor: pointer; font-size: 14px; display: flex;
            align-items: center; justify-content: center;
            transition: all 0.15s; padding: 0;
        }
        #sp-toolbar .sp-icon-btn:hover { border-color: #4a9eff; color: #4a9eff; background: rgba(74,158,255,0.1); }
        #sp-toolbar .sp-icon-btn:active { transform: scale(0.92); }
        #sp-toolbar .sp-status {
            font-size: 11px; color: #aaa; flex: 1;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        #sp-toolbar .sp-count {
            font-size: 11px; color: #888; white-space: nowrap;
        }
        /* 카드 오버레이 버튼 */
        .sp-card-btn {
            position: absolute; top: 6px; right: 6px;
            width: 28px; height: 28px; border-radius: 50%;
            background: rgba(74,158,255,0.9); color: #fff;
            border: none; font-size: 16px; font-weight: 700;
            cursor: pointer; display: flex; align-items: center;
            justify-content: center; z-index: 100;
            transition: all 0.15s; line-height: 1;
            box-shadow: 0 2px 6px rgba(0,0,0,0.4);
        }
        .sp-card-btn:hover { background: #6bb3ff; transform: scale(1.1); }
        .sp-card-btn.sp-card-added { background: rgba(76,175,80,0.9); cursor: default; font-size: 12px; }
        .sp-card-btn:disabled { opacity: 0.6; cursor: wait; }
        /* 커스텀 컨텍스트 메뉴 */
        #sp-ctx-menu {
            position: fixed; z-index: 2147483647;
            background: rgba(30,30,38,0.98); backdrop-filter: blur(12px);
            border: 1px solid rgba(255,255,255,0.15); border-radius: 6px;
            box-shadow: 0 6px 24px rgba(0,0,0,0.6); padding: 4px;
            min-width: 180px; font-size: 13px; display: none;
        }
        #sp-ctx-menu .sp-ctx-item {
            padding: 7px 14px; color: #ddd; cursor: pointer;
            border-radius: 4px; display: flex; align-items: center; gap: 8px;
            transition: background 0.1s;
        }
        #sp-ctx-menu .sp-ctx-item:hover { background: rgba(74,158,255,0.2); color: #fff; }
        #sp-ctx-menu .sp-ctx-sep { border-top: 1px solid rgba(255,255,255,0.1); margin: 3px 0; }
        #sp-ctx-menu .sp-ctx-item.sp-ctx-disabled { color: #666; cursor: default; }
        #sp-ctx-menu .sp-ctx-item.sp-ctx-disabled:hover { background: none; color: #666; }
        /* 바닥 여백 보정 */
        body { padding-bottom: 48px !important; }
    `;
    document.head.appendChild(style);

    /* ── 커스텀 컨텍스트 메뉴 ── */
    const ctxMenu = document.createElement('div');
    ctxMenu.id = 'sp-ctx-menu';
    document.body.appendChild(ctxMenu);

    let ctxTargetLink = null;
    let ctxSelectedText = '';

    document.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        /* 타겟 분석 */
        const link = e.target.closest('a[href]');
        ctxTargetLink = link ? getFullUrl(link.getAttribute('href')) : null;
        ctxSelectedText = window.getSelection().toString().trim();

        let items = '';

        /* 링크 메뉴 */
        if (ctxTargetLink) {
            const isVid = isVideoUrl(ctxTargetLink);
            const isAdded = addedUrls.has(ctxTargetLink);
            items += `<div class="sp-ctx-item" data-action="open-tab">🔗 새 탭에서 열기</div>`;
            items += `<div class="sp-ctx-item" data-action="copy-link">📋 링크 주소 복사</div>`;
            if (isVid && !isAdded) {
                items += `<div class="sp-ctx-item" data-action="add-queue">➕ 대기열에 추가</div>`;
            } else if (isVid && isAdded) {
                items += `<div class="sp-ctx-item sp-ctx-disabled">✅ 이미 추가됨</div>`;
            }
            items += `<div class="sp-ctx-sep"></div>`;
        }

        /* 텍스트 선택 메뉴 */
        if (ctxSelectedText) {
            items += `<div class="sp-ctx-item" data-action="copy-text">📄 텍스트 복사</div>`;
            items += `<div class="sp-ctx-sep"></div>`;
        }

        /* 공통 메뉴 */
        items += `<div class="sp-ctx-item" data-action="back">◀ 뒤로</div>`;
        items += `<div class="sp-ctx-item" data-action="forward">▶ 앞으로</div>`;
        items += `<div class="sp-ctx-item" data-action="reload">🔄 새로고침</div>`;
        items += `<div class="sp-ctx-item" data-action="copy-page-url">🌐 페이지 URL 복사</div>`;

        ctxMenu.innerHTML = items;
        ctxMenu.style.display = 'block';

        /* 위치 계산 (화면 밖 방지) */
        const mw = ctxMenu.offsetWidth, mh = ctxMenu.offsetHeight;
        let x = e.clientX, y = e.clientY;
        if (x + mw > window.innerWidth) x = window.innerWidth - mw - 4;
        if (y + mh > window.innerHeight - 44) y = window.innerHeight - 44 - mh - 4;
        ctxMenu.style.left = x + 'px';
        ctxMenu.style.top = y + 'px';
    });

    document.addEventListener('click', () => { ctxMenu.style.display = 'none'; });
    document.addEventListener('scroll', () => { ctxMenu.style.display = 'none'; }, true);

    ctxMenu.addEventListener('click', async (e) => {
        const item = e.target.closest('.sp-ctx-item');
        if (!item || item.classList.contains('sp-ctx-disabled')) return;
        const action = item.dataset.action;
        ctxMenu.style.display = 'none';

        switch (action) {
            case 'copy-link':
                if (ctxTargetLink) navigator.clipboard.writeText(ctxTargetLink).catch(() => {});
                break;
            case 'copy-text':
                if (ctxSelectedText) navigator.clipboard.writeText(ctxSelectedText).catch(() => {});
                break;
            case 'copy-page-url':
                navigator.clipboard.writeText(location.href).catch(() => {});
                break;
            case 'open-tab':
                if (ctxTargetLink && window.pywebview && window.pywebview.api) {
                    statusEl.textContent = '🔗 새 탭 열기...';
                    await window.pywebview.api.open_new_tab(ctxTargetLink);
                    setTimeout(() => statusEl.textContent = '', 1500);
                }
                break;
            case 'add-queue':
                if (ctxTargetLink && window.pywebview && window.pywebview.api) {
                    statusEl.textContent = '⏳ 추가 중...';
                    try {
                        const res = await window.pywebview.api.add_to_queue(ctxTargetLink);
                        if (res.ok || res.duplicate) {
                            addedUrls.add(ctxTargetLink);
                            statusEl.textContent = '✅ ' + (res.title || '추가 완료');
                            updateCount(); injectCardButtons();
                        } else {
                            statusEl.textContent = '❌ ' + (res.error || '실패');
                        }
                    } catch { statusEl.textContent = '❌ 오류'; }
                    setTimeout(() => statusEl.textContent = '', 3000);
                }
                break;
            case 'back': history.back(); break;
            case 'forward': history.forward(); break;
            case 'reload': location.reload(); break;
        }
    });

    /* ── 툴바 HTML ── */
    const toolbar = document.createElement('div');
    toolbar.id = 'sp-toolbar';
    const isVideo = isVideoUrl(location.href);
    toolbar.innerHTML = `
        <span class="sp-brand">▶ SP</span>
        <button class="sp-btn ${isVideo ? '' : 'sp-na'}" id="sp-add-btn"
                ${isVideo ? '' : 'disabled'} title="${isVideo ? '이 영상을 대기열에 추가' : '영상 페이지에서만 사용 가능'}">
            ${isVideo ? '+ 추가' : '영상 아님'}
        </button>
        <button class="sp-icon-btn" id="sp-reinject-btn" title="[+] 버튼 강제 표시">🔧</button>
        <button class="sp-icon-btn" id="sp-refresh-btn" title="새로고침">↻</button>
        <button class="sp-icon-btn" id="sp-newtab-btn" title="현재 페이지를 새 탭으로">⧉</button>
        <span class="sp-status" id="sp-status"></span>
        <span class="sp-count" id="sp-count"></span>
    `;
    document.body.appendChild(toolbar);

    const addBtn = document.getElementById('sp-add-btn');
    const statusEl = document.getElementById('sp-status');
    const countEl = document.getElementById('sp-count');

    /* ── 강제 인젝션 버튼 ── */
    document.getElementById('sp-reinject-btn').addEventListener('click', () => {
        document.querySelectorAll('[data-sp-done]').forEach(el => el.removeAttribute('data-sp-done'));
        injectCardButtons();
        statusEl.textContent = '🔧 [+] 버튼 강제 표시 완료';
        setTimeout(() => statusEl.textContent = '', 2000);
    });

    /* ── 새로고침 버튼 ── */
    document.getElementById('sp-refresh-btn').addEventListener('click', () => {
        location.reload();
    });

    /* ── 새 탭 버튼 (현재 페이지) ── */
    document.getElementById('sp-newtab-btn').addEventListener('click', async () => {
        if (window.pywebview && window.pywebview.api) {
            statusEl.textContent = '🔗 새 탭 열기...';
            await window.pywebview.api.open_new_tab(location.href);
            setTimeout(() => statusEl.textContent = '', 1500);
        }
    });

    /* ── 대기열 추가 (현재 페이지) ── */
    if (isVideo) {
        addBtn.addEventListener('click', async () => {
            const url = location.href.split('?')[0];
            if (addedUrls.has(url)) return;
            addBtn.disabled = true;
            addBtn.textContent = '⏳ 추가 중...';
            statusEl.textContent = '영상 정보 추출 중... (최대 30초 소요)';
            try {
                const res = await window.pywebview.api.add_to_queue(url);
                if (res.error) {
                    if (res.duplicate) {
                        addedUrls.add(url);
                        addBtn.textContent = '✅ 추가됨';
                        addBtn.classList.add('sp-dup');
                        statusEl.textContent = '이미 대기열에 있습니다.';
                    } else {
                        addBtn.textContent = '❌ 실패';
                        statusEl.textContent = '❌ ' + res.error;
                        /* 실패 시 버튼 복구하여 재시도 가능 */
                        setTimeout(() => { addBtn.textContent = '+ 추가'; addBtn.disabled = false; }, 5000);
                        setTimeout(() => { statusEl.textContent = ''; }, 8000);
                        return;
                    }
                } else {
                    addedUrls.add(url);
                    addBtn.textContent = '✅ 추가됨';
                    addBtn.classList.add('sp-added');
                    statusEl.textContent = '✅ ' + (res.title || '추가 완료');
                    updateCount();
                }
                setTimeout(() => { statusEl.textContent = ''; }, 3000);
            } catch(e) {
                addBtn.textContent = '❌ 오류';
                statusEl.textContent = '❌ 오류: ' + (e.message || '알 수 없는 오류');
                setTimeout(() => { addBtn.textContent = '+ 추가'; addBtn.disabled = false; statusEl.textContent = ''; }, 5000);
            }
        });
    }

    /* ── 카드 오버레이 버튼 인젝션 ── */
    function injectCardButtons() {
        document.querySelectorAll('a[href]').forEach(a => {
            if (a.dataset.spDone) return;
            a.dataset.spDone = '1';
            const href = a.getAttribute('href');
            if (!href || href.startsWith('#') || href.startsWith('javascript')) return;
            const fullUrl = getFullUrl(href);
            if (!fullUrl || !isVideoUrl(fullUrl)) return;
            const img = a.querySelector('img');
            if (!img) return;
            const wrap = a.closest('div') || a;
            const cs = getComputedStyle(wrap);
            if (cs.position === 'static') wrap.style.position = 'relative';

            const btn = document.createElement('button');
            btn.className = 'sp-card-btn' + (addedUrls.has(fullUrl) ? ' sp-card-added' : '');
            btn.textContent = addedUrls.has(fullUrl) ? '✓' : '+';
            btn.title = addedUrls.has(fullUrl) ? '추가됨' : '대기열에 추가';

            btn.addEventListener('click', async (e) => {
                e.preventDefault(); e.stopPropagation();
                if (addedUrls.has(fullUrl)) return;
                btn.disabled = true; btn.textContent = '…';
                statusEl.textContent = '⏳ 추가 중...';
                try {
                    const res = await window.pywebview.api.add_to_queue(fullUrl);
                    if (res.error) {
                        if (res.duplicate) {
                            addedUrls.add(fullUrl); btn.textContent = '✓'; btn.classList.add('sp-card-added');
                            statusEl.textContent = '이미 대기열에 있습니다.';
                        } else {
                            btn.textContent = '!';
                            statusEl.textContent = '❌ ' + res.error;
                            /* 실패 시 재시도 가능하도록 복구 */
                            setTimeout(() => { btn.textContent = '+'; btn.disabled = false; }, 5000);
                            setTimeout(() => { statusEl.textContent = ''; }, 8000);
                            return;
                        }
                    } else {
                        addedUrls.add(fullUrl);
                        btn.textContent = '✓'; btn.classList.add('sp-card-added');
                        statusEl.textContent = '✅ ' + (res.title || '추가 완료');
                        updateCount();
                    }
                    setTimeout(() => { statusEl.textContent = ''; }, 3000);
                } catch(e) {
                    btn.textContent = '!';
                    statusEl.textContent = '❌ 오류: ' + (e.message || '추가 실패');
                    setTimeout(() => { btn.textContent = '+'; btn.disabled = false; }, 5000);
                    setTimeout(() => { statusEl.textContent = ''; }, 8000);
                }
            });
            wrap.appendChild(btn);
        });
    }

    function updateCount() {
        queueCount = addedUrls.size;
        countEl.textContent = '대기열: ' + queueCount + '개';
    }

    /* ── Ctrl+클릭, 중간버튼 클릭 → 새 탭 ── */
    document.addEventListener('click', (e) => {
        if (!e.ctrlKey && e.button !== 1) return;
        const link = e.target.closest('a[href]');
        if (!link) return;
        const href = getFullUrl(link.getAttribute('href'));
        if (!href) return;
        e.preventDefault(); e.stopPropagation();
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.open_new_tab(href);
        }
    }, true);
    document.addEventListener('auxclick', (e) => {
        if (e.button !== 1) return;
        const link = e.target.closest('a[href]');
        if (!link) return;
        const href = getFullUrl(link.getAttribute('href'));
        if (!href) return;
        e.preventDefault(); e.stopPropagation();
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.open_new_tab(href);
        }
    }, true);

    /* ── 초기화 ── */
    async function init() {
        try {
            const urls = await window.pywebview.api.get_queue_urls();
            urls.forEach(u => addedUrls.add(u));
            urls.forEach(u => addedUrls.add(u.split('?')[0]));
            queueCount = urls.length;
            updateCount();
            if (isVideo && addedUrls.has(location.href.split('?')[0])) {
                addBtn.textContent = '✅ 추가됨';
                addBtn.classList.add('sp-dup');
                addBtn.disabled = true;
            }
        } catch(e) { console.warn('[SP] 대기열 로드 실패:', e); }
        injectCardButtons();
        /* MutationObserver: 디바운스 적용 */
        let mutTimer = null;
        const observer = new MutationObserver(() => {
            if (mutTimer) return;
            mutTimer = setTimeout(() => { mutTimer = null; injectCardButtons(); }, 300);
        });
        observer.observe(document.body, { childList: true, subtree: true });
        /* 안전망: 3초 간격 주기적 재검사 */
        setInterval(injectCardButtons, 3000);
    }

    /* pywebview API가 준비될 때까지 대기 */
    function waitForApi() {
        if (window.pywebview && window.pywebview.api) { init(); }
        else { setTimeout(waitForApi, 200); }
    }
    waitForApi();
})();
"""

def set_webview_ready():
    """pywebview guilib 초기화 완료 시그널. app.py의 func 콜백에서 호출."""
    _webview_ready.set()
    print("  [pywebview] GUI 초기화 완료 — 검색 창 동적 생성 가능")


def _open_browse_tab(url):
    """새 pywebview 창(탭)을 열어 지정 URL의 MissAV 사이트를 표시합니다.
    기존 탐색 창과 동일한 js_api와 JS 인젝션을 적용합니다."""
    import webview
    import time as _time

    def _inject_tab_js(win):
        """새 탭 JS 인젝션 (지연 + 재시도)"""
        _time.sleep(1.5)
        for attempt in range(5):
            try:
                win.evaluate_js(_BROWSE_INJECT_JS)
                print(f"  [새탭] JS 인젝션 성공 (시도 {attempt+1})")
                return
            except Exception as e:
                print(f"  [새탭] JS 인젝션 시도 {attempt+1}/5 실패: {e}")
                if attempt < 4:
                    _time.sleep(1.0)
        print(f"  [새탭] JS 인젝션 최종 실패")

    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path_slug = parsed.path.rstrip('/').split('/')[-1][:40] if parsed.path else ''
        title = f"MissAV — {path_slug}" if path_slug else "MissAV — 새 탭"

        new_win = webview.create_window(
            title=title,
            url=url,
            width=1100,
            height=800,
            min_size=(700, 500),
            text_select=True,
            js_api=_browse_api,
        )
        if new_win is not None:
            # loaded 이벤트 핸들러 (페이지 이동마다)
            new_win.events.loaded += lambda: threading.Thread(
                target=_inject_tab_js, args=(new_win,), daemon=True
            ).start()
            # ★ 최초 로드 누락 대비 수동 인젝션
            threading.Thread(
                target=_inject_tab_js, args=(new_win,), daemon=True
            ).start()
            print(f"  [새탭] 열림: {url[:80]}")
        else:
            print(f"  [새탭] 창 생성 실패: {url[:80]}")
    except Exception as e:
        print(f"  [새탭] 오류: {e}")


def _is_cf_blocked(html: str) -> bool:
    """Cloudflare 차단 여부를 확인합니다."""
    check = html[:5000].lower()
    cf_signs = [
        'just a moment', 'checking your browser', 'cf-turnstile',
        'challenge-platform', 'cf-browser-verification', 'verify you are human',
        '_cf_chl_opt', 'window._cf_chl_opt',
    ]
    hits = sum(1 for s in cf_signs if s in check)
    return hits >= 2


def _detect_browser() -> str:
    """설치된 브라우저를 자동 감지합니다. (yt-dlp가 지원하는 이름 반환)"""
    import shutil
    # 윈도우에서 실제 경로 확인
    browser_checks = [
        ('edge', [
            os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
            os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
        ]),
        ('chrome', [
            os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
        ]),
        ('brave', [
            os.path.expandvars(r'%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe'),
            os.path.expandvars(r'%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe'),
        ]),
        ('firefox', [
            os.path.expandvars(r'%ProgramFiles%\Mozilla Firefox\firefox.exe'),
            os.path.expandvars(r'%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe'),
        ]),
        ('opera', [
            os.path.expandvars(r'%LocalAppData%\Programs\Opera\opera.exe'),
            os.path.expandvars(r'%AppData%\Opera Software\Opera Stable\opera.exe'),
        ]),
    ]

    for name, paths in browser_checks:
        for p in paths:
            if os.path.exists(p):
                print(f"[브라우저 감지] {name} 발견: {p}")
                return name
        # shutil.which 폴백 (PATH에 있는 경우)
        exe_name = name if name != 'edge' else 'msedge'
        if shutil.which(exe_name):
            print(f"[브라우저 감지] {name} (PATH)")
            return name

    # Whale은 Chromium 기반 → Edge의 쿠키 경로와 유사한 구조
    # yt-dlp는 whale을 모르지만, Chromium 기반 쿠키 DB 파일을 직접 읽을 수 있음
    whale_paths = [
        os.path.expandvars(r'%LocalAppData%\Naver\Naver Whale\User Data'),
    ]
    for wp in whale_paths:
        if os.path.isdir(wp):
            print(f"[브라우저 감지] Whale 발견 (Chromium 호환 모드 사용)")
            # Whale은 chromium과 경로 구조가 같음
            return 'chromium'

    print("[브라우저 감지] 브라우저를 찾지 못함")
    return ''


_detected_browser = None  # 캐시

def _get_browser():
    """감지된 브라우저를 캐시하여 반환합니다."""
    global _detected_browser
    if _detected_browser is None:
        _detected_browser = _detect_browser()
    return _detected_browser


def _build_cookie_jar_from_browser(browser: str = ''):
    """yt-dlp를 통해 브라우저의 쿠키 jar를 안전하게 추출합니다."""
    if not browser:
        browser = _get_browser()
    if not browser:
        return None, ''

    try:
        # yt-dlp YoutubeDL 인스턴스를 만들어 쿠키 jar만 가져오기
        # 이 방식이 내부 API보다 안정적
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiesfrombrowser": (browser,),
        }
        ydl = yt_dlp.YoutubeDL(opts)
        cookie_jar = ydl.cookiejar
        print(f"[쿠키] {browser}에서 쿠키 jar 추출 성공 ({len(cookie_jar)}개)")
        return cookie_jar, browser
    except Exception as e:
        print(f"[쿠키] {browser}에서 추출 실패: {e}")
        # 다른 브라우저 시도
        for alt in ['edge', 'chrome', 'chromium', 'firefox', 'brave']:
            if alt == browser:
                continue
            try:
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "cookiesfrombrowser": (alt,),
                }
                ydl = yt_dlp.YoutubeDL(opts)
                cookie_jar = ydl.cookiejar
                print(f"[쿠키] {alt}에서 쿠키 jar 추출 성공 ({len(cookie_jar)}개)")
                return cookie_jar, alt
            except Exception:
                continue
    return None, ''


# ──────────────────────────────────────────────
# 데이터 저장/로드 (파일 기반, 용량 무제한)
# ──────────────────────────────────────────────
_data_lock = threading.Lock()

def _load_data():
    """data.json을 로드합니다. 손상 시 백업에서 복구를 시도합니다."""
    for fp in [DATA_FILE, Path(str(DATA_FILE) + ".bak"), Path(str(DATA_FILE) + ".bak2")]:
        if not fp.exists():
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "categories" not in data:
                data["categories"] = []
            if fp != DATA_FILE:
                print(f"  [복구] {fp.name}에서 데이터 복구 성공")
                # 복구된 데이터를 원본에 저장
                try:
                    with open(DATA_FILE, "w", encoding="utf-8") as f2:
                        json.dump(data, f2, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            return data
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  [경고] {fp.name} 손상됨: {e}")
            continue
        except Exception:
            continue
    return {"queue": [], "playback": {}, "heatmaps": {}, "categories": []}

def _save_data(data):
    """data.json을 저장합니다. 저장 전 이중 백업을 수행합니다.
    백업 순환: data.json.bak → data.json.bak2, data.json → data.json.bak
    ★ 데이터 급감 감지 시 .safety 백업 생성 (덮어쓰기 방지)"""
    with _data_lock:
        bak = Path(str(DATA_FILE) + ".bak")
        bak2 = Path(str(DATA_FILE) + ".bak2")
        safety = Path(str(DATA_FILE) + ".safety")

        # ★ 데이터 급감 보호: 기존 대비 대기열이 50% 이상 줄었으면 .safety 백업
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                old_count = len(existing.get("queue", []))
                new_count = len(data.get("queue", []))
                if old_count > 10 and new_count < old_count * 0.5:
                    # .safety가 없거나 .safety보다 기존 data가 더 크면 백업
                    save_safety = True
                    if safety.exists():
                        try:
                            with open(safety, "r", encoding="utf-8") as sf:
                                safety_data = json.load(sf)
                            if len(safety_data.get("queue", [])) >= old_count:
                                save_safety = False  # 이미 더 큰 safety 백업 있음
                        except:
                            pass
                    if save_safety:
                        import shutil
                        shutil.copy2(str(DATA_FILE), str(safety))
                        print(f"  [⚠ 안전백업] 대기열 급감 감지! ({old_count}→{new_count}) .safety 백업 생성")
            except:
                pass

        try:
            # 백업 순환: .bak → .bak2
            if bak.exists():
                import shutil
                shutil.copy2(str(bak), str(bak2))
            # 현재 data.json → .bak
            if DATA_FILE.exists():
                import shutil
                shutil.copy2(str(DATA_FILE), str(bak))
        except Exception as e:
            print(f"  [백업] 회전 실패 (무시): {e}")
        # 안전 쓰기: 임시 파일에 먼저 쓰고 rename
        tmp = Path(str(DATA_FILE) + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Windows에서 rename 전에 기존 파일 삭제 필요
            if DATA_FILE.exists():
                DATA_FILE.unlink()
            tmp.rename(DATA_FILE)
        except Exception as e:
            print(f"  [저장] 안전 쓰기 실패, 직접 쓰기 시도: {e}")
            try:
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e2:
                print(f"  [저장] 직접 쓰기도 실패: {e2}")

def _url_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

# ──────────────────────────────────────────────
# 설정 관리
# ──────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "quality": "best",
    "downloadFolder": "",
    "skipForward": 10,
    "skipBackward": 10,
    "skipForwardShift": 5,
    "skipBackwardShift": 5,
    "defaultVolume": 1.0,
    "defaultSpeed": 1.0,
    "autoplayNext": True,
    "alwaysOnTop": False,
    "windowWidth": 1400,
    "windowHeight": 850,
}

def _load_settings():
    data = _load_data()
    saved = data.get("settings", {})
    return {**DEFAULT_SETTINGS, **saved}

def _save_settings(settings):
    data = _load_data()
    data["settings"] = settings
    _save_data(data)

# ──────────────────────────────────────────────
# yt-dlp 헬퍼
# ──────────────────────────────────────────────
def _ydl_opts(extract_only=True):
    browser = _get_browser()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best",
        "noplaylist": True,
        # Cloudflare 우회: 브라우저 흔내
        "impersonate": "chrome",
        "extractor_args": {"generic": {"impersonate": ["true"]}},
    }
    # 브라우저 쿠키 자동 추출 (우선)
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    # cookies.txt 폴백
    if COOKIES_FILE.exists():
        if not browser:
            opts["cookiefile"] = str(COOKIES_FILE)
    if extract_only:
        opts["skip_download"] = True
    return opts

# 추출 결과 캐시 (같은 영상 재생 시 즉시 시작)
_extract_cache = {}  # url -> {"info": ..., "time": ...}
_CACHE_TTL = 3600  # 1시간

# M3U8 컨텐츠 캐시 (처리된 M3U8를 메모리에 저장)
_m3u8_content_cache = {}  # video_url -> {"content": str, "time": float}
_M3U8_CONTENT_TTL = 1800  # 30분

def _fetch_and_cache_m3u8(video_url, headers):
    """
    M3U8를 CDN에서 가져와서 처리(상대→절대 URL)하고 캐시합니다.
    캐시된 결과가 있으면 즉시 반환합니다.
    """
    # 캐시 확인
    if video_url in _m3u8_content_cache:
        cached = _m3u8_content_cache[video_url]
        if time.time() - cached["time"] < _M3U8_CONTENT_TTL:
            return cached["content"]

    resp = requests.get(video_url, headers=headers, timeout=15)
    resp.raise_for_status()

    content = resp.text
    base_url = video_url.rsplit('/', 1)[0] + '/'
    lines = content.split('\n')
    fixed_lines = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            if not line.startswith('http'):
                line = base_url + line
        fixed_lines.append(line)

    result = '\n'.join(fixed_lines)
    _m3u8_content_cache[video_url] = {"content": result, "time": time.time()}
    return result

def _background_preextract():
    """서버 시작 시 stream_url이 없는 대기열 항목을 백그라운드로 추출합니다."""
    time.sleep(3)  # 서버 시작 대기
    try:
        data = _load_data()
        urls_to_extract = []
        for item in data.get("queue", []):
            if not item.get("stream_url"):
                urls_to_extract.append({"url": item["url"], "title": item.get("title", "?"), "id": item["id"]})
        if not urls_to_extract:
            print("[사전 추출] 모든 항목이 준비됨")
            return
        print(f"[사전 추출] {len(urls_to_extract)}개 항목 처리 시작...")
        success = 0
        for item_ref in urls_to_extract:
            try:
                info = _extract_info(item_ref["url"])
                video_url = info.get("url", "")
                if video_url:
                    # ★ 매번 최신 데이터를 다시 로드해서 저장 (race condition 방지)
                    fresh_data = _load_data()
                    for q in fresh_data.get("queue", []):
                        if q["id"] == item_ref["id"]:
                            q["stream_url"] = video_url
                            q["http_headers"] = info.get("http_headers", {})
                            q["variants"] = info.get("_variants", [])
                            q["_extracted_at"] = time.time()
                            break
                    _save_data(fresh_data)
                    # M3U8 도 미리 캐시
                    headers = {'User-Agent': USER_AGENT}
                    headers.update(info.get("http_headers", {}))
                    if '.m3u8' in video_url:
                        try:
                            _fetch_and_cache_m3u8(video_url, headers)
                        except:
                            pass
                    success += 1
                    print(f"[사전 추출] ✓ {item_ref['title'][:40]}")
            except Exception as e:
                print(f"[사전 추출] ✗ {item_ref['title'][:40]}: {e}")
            time.sleep(0.5)  # 서버 부하 방지
        print(f"[사전 추출] 완료 ({success}/{len(urls_to_extract)} 성공)")
    except Exception as e:
        print(f"[사전 추출] 오류: {e}")

def _extract_info(url: str, use_cache=True):
    """URL에서 영상 정보를 추출합니다. 커스텀 도메인은 바로 커스텀 추출기 사용."""
    # 캐시 확인
    if use_cache and url in _extract_cache:
        cached = _extract_cache[url]
        if time.time() - cached["time"] < _CACHE_TTL:
            print(f"[캐시] 추출 결과 캐시 사용 ({url[:60]}...)")
            return cached["info"]

    parsed = urllib.parse.urlparse(url)
    is_custom = any(d in parsed.netloc for d in CUSTOM_DOMAINS)

    # 커스텀 도메인은 yt-dlp 건너뛰기 (2~3분 대기 방지 → 즉시 추출)
    if is_custom:
        print(f"[커스텀 도메인] {parsed.netloc} → 커스텀 추출기 바로 사용")
        info = _custom_extract(url)
        _extract_cache[url] = {"info": info, "time": time.time()}
        return info

    # 그 외 사이트는 yt-dlp 시도
    try:
        opts = _ydl_opts(extract_only=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info and (info.get("url") or info.get("formats")):
            _extract_cache[url] = {"info": info, "time": time.time()}
            return info
    except Exception as e:
        raise
    raise ValueError("영상 정보를 추출할 수 없습니다.")


def _load_cookies_into_session(session):
    """쿠키 파일을 세션에 로드합니다."""
    if COOKIES_FILE.exists():
        try:
            from http.cookiejar import MozillaCookieJar
            cj = MozillaCookieJar(str(COOKIES_FILE))
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies = cj
            print(f"[쿠키] {len(cj)} 개 쿠키 로드됨")
        except Exception as e:
            print(f"[쿠키 로드 실패] {e}")


def _fetch_page_with_cf_bypass(url: str):
    """Cloudflare 우회하여 페이지를 가져옵니다.
    순서: curl_cffi+브라우저쿠키 → curl_cffi+cookies.txt → requests"""
    parsed = urllib.parse.urlparse(url)
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': f'{parsed.scheme}://{parsed.netloc}/',
        'Sec-Ch-Ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
    }

    # ── 방법 1: curl_cffi + 브라우저 쿠키 (yt-dlp cookie jar) ──
    cookie_jar, browser_name = _build_cookie_jar_from_browser()
    if cookie_jar:
        try:
            from curl_cffi import requests as cf_requests
            session = cf_requests.Session(impersonate="chrome")
            # cookie jar의 모든 쿠키를 세션에 추가
            domain = parsed.netloc
            parts = domain.split('.')
            base = '.'.join(parts[-2:]) if len(parts) >= 2 else domain
            loaded = 0
            has_cf = False
            for cookie in cookie_jar:
                cd = cookie.domain.lstrip('.')
                if base in cd or cd in domain:
                    session.cookies.set(cookie.name, cookie.value, domain=cookie.domain)
                    loaded += 1
                    if cookie.name == 'cf_clearance':
                        has_cf = True
            print(f"[방법1] {browser_name}에서 {loaded}개 쿠키 로드 (cf_clearance: {'✓' if has_cf else '✗'})")
            if loaded > 0:
                resp = session.get(url, headers=headers, timeout=30)
                if resp.status_code == 200 and not _is_cf_blocked(resp.text):
                    print(f"[방법1] curl_cffi + {browser_name} 쿠키로 성공!")
                    return resp.text, session, f'curl_cffi+{browser_name}'
                else:
                    print(f"[방법1] 브라우저 쿠키로도 CF 차단됨 (cf_clearance={has_cf})")
        except ImportError:
            print("[방법1] curl_cffi 미설치")
        except Exception as e:
            print(f"[방법1 실패] {e}")

    # ── 방법 2: curl_cffi + cookies.txt ──
    if COOKIES_FILE.exists():
        try:
            from curl_cffi import requests as cf_requests
            session = cf_requests.Session(impersonate="chrome")
            from http.cookiejar import MozillaCookieJar
            cj = MozillaCookieJar(str(COOKIES_FILE))
            cj.load(ignore_discard=True, ignore_expires=True)
            for cookie in cj:
                session.cookies.set(cookie.name, cookie.value, domain=cookie.domain)
            print(f"[방법2] cookies.txt에서 {len(cj)}개 쿠키 로드")
            resp = session.get(url, headers=headers, timeout=30)
            if resp.status_code == 200 and not _is_cf_blocked(resp.text):
                print(f"[방법2] curl_cffi + cookies.txt로 성공!")
                return resp.text, session, 'curl_cffi+cookies.txt'
            else:
                print(f"[방법2] cookies.txt로도 CF 차단됨")
        except ImportError:
            print("[방법2] curl_cffi 미설치")
        except Exception as e:
            print(f"[방법2 실패] {e}")

    # ── 방법 3: 일반 requests (최후 폴백) ──
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT})
    _load_cookies_into_session(session)
    resp = session.get(url, headers={**headers, 'User-Agent': USER_AGENT}, timeout=30)
    resp.raise_for_status()
    print(f"[방법3] requests 폴백 (CF 차단 가능성 높음)")
    return resp.text, session, 'requests(폴백)'


# ── P.A.C.K.E.R. 디코딩 헬퍼 함수들 ──

def _base_n_decode(token: str, base: int) -> int:
    """P.A.C.K.E.R.의 base-N 인코딩된 토큰을 정수로 디코딩합니다."""
    ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    result = 0
    for ch in token:
        idx = ALPHABET.index(ch) if ch in ALPHABET else -1
        if idx < 0 or idx >= base:
            return -1  # 디코딩 불가
        result = result * base + idx
    return result


def _unpack_packer(pcode: str, base_n: int, count: int, kstr: str) -> str:
    """P.A.C.K.E.R. 난독화를 실제로 언팩합니다.
    pcode 안의 base-N 인코딩된 토큰을 keywords 배열의 값으로 치환합니다."""
    keywords = kstr.split('|')
    print(f"[UNPACK] keywords 수: {len(keywords)}, base: {base_n}")

    def replacer(match):
        token = match.group(0)
        idx = _base_n_decode(token, base_n)
        if 0 <= idx < len(keywords) and keywords[idx]:
            return keywords[idx]
        return token

    # base에 따른 토큰 패턴
    if base_n <= 10:
        pattern = r'\b\d+\b'
    elif base_n <= 36:
        pattern = r'\b[a-zA-Z0-9]+\b'
    else:  # base62
        pattern = r'\b[a-zA-Z0-9]+\b'

    unpacked = re.sub(pattern, replacer, pcode)
    return unpacked


def _reconstruct_m3u8_from_keywords(kstr: str) -> str:
    """hitomi.py 방식: 키워드 배열의 인덱스 패턴으로 M3U8 URL을 재구성합니다."""
    keywords = kstr.split('|')
    print(f"[키워드재구성] keywords 수: {len(keywords)}")
    if len(keywords) < 3:
        return None

    # 디버그: 키워드 목록 일부 출력
    preview = keywords[:20] if len(keywords) > 20 else keywords
    print(f"[키워드재구성] 키워드 프리뷰: {preview}")

    # hitomi.py 기본 패턴: protocol=8, domain1=7, domain2=6, path=[5,4,3,2,1], filename=14, extension=0
    patterns = [
        {'name': 'Default(hitomi)', 'protocol_idx': 8, 'domain1_idx': 7, 'domain2_idx': 6,
         'path_indices': [5, 4, 3, 2, 1], 'path_separator': '-',
         'filename_idx': 14, 'extension_idx': 0},
    ]

    # m3u8 키워드가 있는 인덱스 찾기 → 동적 패턴 생성
    m3u8_idx = None
    protocol_indices = []
    for i, kw in enumerate(keywords):
        if kw.lower() == 'm3u8':
            m3u8_idx = i
        if kw.lower() in ('https', 'http'):
            protocol_indices.append(i)

    # m3u8 키워드로 동적 패턴 생성 시도
    if m3u8_idx is not None and protocol_indices:
        print(f"[키워드재구성] m3u8 인덱스: {m3u8_idx}, protocol 인덱스: {protocol_indices}")
        for p_idx in protocol_indices:
            # 프로토콜과 m3u8 사이의 키워드가 도메인+경로+파일명
            if p_idx < m3u8_idx and (m3u8_idx - p_idx) >= 3:
                # 프로토콜 다음 2개가 도메인, 마지막이 파일명, 나머지가 경로
                d1_idx = p_idx - 1 if p_idx > 0 else p_idx + 1
                d2_idx = p_idx - 2 if p_idx > 1 else p_idx + 2
                fn_idx = m3u8_idx + 1 if m3u8_idx + 1 < len(keywords) else m3u8_idx - 1

                # 경로 인덱스 추정 (프로토콜과 m3u8 사이)
                path_start = min(d1_idx, d2_idx) - 1
                path_end = 0
                path_idxs = list(range(path_start, path_end, -1)) if path_start > path_end else []

                patterns.append({
                    'name': f'Dynamic(p={p_idx},m={m3u8_idx})',
                    'protocol_idx': p_idx, 'domain1_idx': d1_idx, 'domain2_idx': d2_idx,
                    'path_indices': path_idxs[:8],  # 최대 8세그먼트
                    'path_separator': '-',
                    'filename_idx': fn_idx, 'extension_idx': m3u8_idx
                })

    for patt in patterns:
        p_name = patt['name']
        try:
            indices = [patt['protocol_idx'], patt['domain1_idx'], patt['domain2_idx'],
                       patt['filename_idx'], patt['extension_idx']] + patt['path_indices']
            if any(idx >= len(keywords) or idx < 0 for idx in indices):
                print(f"[키워드재구성] {p_name}: 인덱스 범위 초과 (keywords: {len(keywords)})")
                continue

            proto = keywords[patt['protocol_idx']]
            d1 = keywords[patt['domain1_idx']]
            d2 = keywords[patt['domain2_idx']]
            domain = f"{d1}.{d2}"

            path_parts = [keywords[i] for i in patt['path_indices'] if keywords[i]]
            path_str = patt['path_separator'].join(path_parts)

            fn = keywords[patt['filename_idx']]
            ext = keywords[patt['extension_idx']]

            url = f"{proto}://{domain}/{path_str}/{fn}.{ext}"
            print(f"[키워드재구성] {p_name} 생성: {url}")

            if proto.lower() in ('http', 'https') and '.' in domain and ext.lower() == 'm3u8':
                return url
            else:
                print(f"[키워드재구성] {p_name}: 유효하지 않은 URL")
        except (IndexError, Exception) as e:
            print(f"[키워드재구성] {p_name} 실패: {e}")

    return None


def _select_quality(variants, quality):
    """화질 설정에 따라 적절한 variant를 선택합니다."""
    if not variants:
        return None
    if quality == "worst":
        return variants[-1]
    if quality == "best" or not quality:
        return variants[0]
    # 해상도 기반 선택 (예: "720p" → 높이 720 이하 중 최고)
    m = re.match(r'(\d+)p', quality)
    if m:
        target_h = int(m.group(1))
        for v in variants:
            res = v.get("resolution", "")
            if 'x' in res:
                h = int(res.split('x')[1])
                if h <= target_h:
                    return v
        return variants[-1]
    return variants[0]


def _custom_extract(url: str):
    """hitomi.py 로직 기반 MissAV 커스텀 추출기 (Cloudflare 우회)"""
    parsed = urllib.parse.urlparse(url)
    page, session, method = _fetch_page_with_cf_bypass(url)
    soup = BeautifulSoup(page, 'html.parser')

    # 제목 추출
    title = "video"
    h1 = soup.find('h1')
    if h1 and h1.text.strip():
        title = h1.text.strip()[:80]
    else:
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content'].strip()[:80]

    # 썸네일 추출
    thumbnail = ""
    og_img = soup.find('meta', {'property': 'og:image'})
    if og_img and og_img.get('content'):
        thumbnail = og_img['content']

    # M3U8 URL 추출 - P.A.C.K.E.R. 난독화 해제
    m3u8_url = None

    for script in soup.find_all('script'):
        if not script.string:
            continue
        content = script.string

        # P.A.C.K.E.R. 패턴 감지
        packer_match = re.search(
            r"eval\s*\(\s*function\s*\(p,\s*a,\s*c,\s*k,\s*e,\s*d\s*\)\s*\{.*?return\s+p}\s*\((.*)\)\)",
            content, re.DOTALL | re.IGNORECASE
        )
        if packer_match:
            print(f"[P.A.C.K.E.R.] 발견됨, 디코딩 시도...")
            args_str = packer_match.group(1).strip()

            # pcode 추출
            pcode = ""
            pcode_match = re.match(r"(['\"])(.*?)\1\s*,", args_str)
            if pcode_match:
                quote = pcode_match.group(1)
                pcode_raw = pcode_match.group(2)
                pcode = pcode_raw.replace(f"\\{quote}", quote)
            else:
                print("[P.A.C.K.E.R.] pcode 추출 실패")
                continue

            # base, count 추출
            remaining_after_pcode = args_str[pcode_match.end():]
            nums = re.findall(r'(\d+)', remaining_after_pcode)
            base_n = int(nums[0]) if len(nums) >= 1 else 36
            count = int(nums[1]) if len(nums) >= 2 else 0

            # keyword 문자열 추출 (.split('|') 앞의 문자열)
            kstr = ""
            kstr_match = re.search(
                r",\s*(['\"])((?:\\.|(?!\1)[^\\\r\n])*)\1\s*\.split\(\s*['\"]" + re.escape('|') + r"['\"]\s*\)",
                args_str, re.VERBOSE
            )
            if kstr_match:
                kq = kstr_match.group(1)
                kstr_raw = kstr_match.group(2)
                kstr = kstr_raw.replace(f"\\{kq}", kq)

            print(f"[P.A.C.K.E.R.] base={base_n}, count={count}, keywords={len(kstr.split('|')) if kstr else 0}개")

            # ── 방법 1: pcode에서 직접 M3U8 URL 검색 ──
            direct_m3u8 = re.search(
                r"""(?:file|source|src|f)\s*[:=]\s*(['"])(https?://[^\s"'<>]+\.m3u8[^\s"'<>]*)\1""",
                pcode, re.IGNORECASE
            )
            if direct_m3u8:
                m3u8_url = direct_m3u8.group(2)
                print(f"[P.A.C.K.E.R.] 직접 M3U8 발견: {m3u8_url}")
                break

            simple_m3u8 = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", pcode)
            if simple_m3u8:
                m3u8_url = simple_m3u8.group(1)
                print(f"[P.A.C.K.E.R.] 단순 M3U8 발견: {m3u8_url}")
                break

            # ── 방법 2: P.A.C.K.E.R. 실제 언팩 (base-N 토큰 → 키워드 치환) ──
            if kstr:
                unpacked = _unpack_packer(pcode, base_n, count, kstr)
                if unpacked:
                    print(f"[P.A.C.K.E.R.] 언팩 완료 ({len(unpacked)} chars)")
                    # 언팩된 코드에서 M3U8 검색
                    m3u8_in_unpacked = re.search(
                        r"""(?:file|source|src|f)\s*[:=]\s*(['"])(https?://[^\s"'<>]+\.m3u8[^\s"'<>]*)\1""",
                        unpacked, re.IGNORECASE
                    )
                    if m3u8_in_unpacked:
                        m3u8_url = m3u8_in_unpacked.group(2)
                        print(f"[P.A.C.K.E.R.] 언팩 후 M3U8 발견: {m3u8_url}")
                        break
                    m3u8_simple_unpacked = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", unpacked)
                    if m3u8_simple_unpacked:
                        m3u8_url = m3u8_simple_unpacked.group(1)
                        print(f"[P.A.C.K.E.R.] 언팩 후 단순 M3U8 발견: {m3u8_url}")
                        break

            # ── 방법 3: 키워드 기반 URL 재구성 (hitomi.py 방식) ──
            if kstr:
                reconstructed = _reconstruct_m3u8_from_keywords(kstr)
                if reconstructed:
                    m3u8_url = reconstructed
                    print(f"[P.A.C.K.E.R.] 키워드 재구성 M3U8: {m3u8_url}")
                    break

        # P.A.C.K.E.R.가 아닌 스크립트에서 직접 M3U8 검색 (폴백)
        m3u8_simple = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", content)
        if m3u8_simple:
            m3u8_url = m3u8_simple.group(1)
            break

    # 페이지 전체에서 마지막 폴백
    if not m3u8_url:
        m3u8_page = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", page)
        if m3u8_page:
            m3u8_url = m3u8_page.group(1)

    if not m3u8_url:
        # 디버그 정보 출력
        cf_signs = ['cf-browser-verification', 'Just a moment', 'Checking your browser',
                    'cf-turnstile', 'challenge-platform', 'Verify you are human']
        is_cf = any(sign.lower() in page.lower() for sign in cf_signs)
        page_title = soup.find('title')
        title_text = page_title.text.strip() if page_title else '(title 없음)'
        print(f"\n{'='*50}")
        print(f"[진단] M3U8 추출 실패")
        print(f"  URL: {url}")
        print(f"  추출 방법: {method}")
        print(f"  페이지 크기: {len(page)} bytes")
        print(f"  페이지 제목: {title_text}")
        print(f"  Cloudflare 차단: {'✓ 차단됨 (쿠키/방식 변경 필요)' if is_cf else '✗ 아님'}")
        print(f"  P.A.C.K.E.R. 발견: {'eval(function(p,a,c,k' in page}")
        print(f"  스크립트 수: {len(soup.find_all('script'))}")
        print(f"  페이지 앞부분: {page[:500]}")
        print(f"{'='*50}\n")

        if is_cf:
            browser = _get_browser()
            if browser:
                raise ValueError(
                    f"Cloudflare가 차단하고 있습니다. "
                    f"감지된 브라우저: {browser}. "
                    f"해당 브라우저에서 이 사이트에 접속하여 Cloudflare 체크를 먼저 통과해주세요. "
                    f"(사이트가 열리면 이 앱에서 다시 시도)"
                )
            else:
                raise ValueError(
                    "Cloudflare가 차단하고 있습니다. "
                    "브라우저가 감지되지 않았습니다. "
                    "Chrome 또는 Edge를 설치하고, 해당 사이트에 접속하여 CF 체크를 통과한 뒤 다시 시도해주세요."
                )
        raise ValueError("M3U8 URL을 찾을 수 없습니다. 페이지 구조가 변경되었을 수 있습니다.")

    # M3U8 마스터 플레이리스트 처리 → 최고 화질 선택
    referer = f'{parsed.scheme}://{parsed.netloc}/'
    m3u8_headers = {
        'User-Agent': USER_AGENT,
        'Referer': referer,
        'Origin': referer.rstrip('/'),
    }

    all_variants = []
    try:
        m3u8_resp = session.get(m3u8_url, headers=m3u8_headers, timeout=15)
        m3u8_resp.raise_for_status()
        m3u8_content = m3u8_resp.text

        if '#EXT-X-STREAM-INF:' in m3u8_content:
            lines = m3u8_content.strip().split('\n')
            for i, line in enumerate(lines):
                if line.startswith('#EXT-X-STREAM-INF:'):
                    bw = 0
                    res = ""
                    bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                    if bw_match:
                        bw = int(bw_match.group(1))
                    res_match = re.search(r'RESOLUTION=(\d+x\d+)', line)
                    if res_match:
                        res = res_match.group(1)
                    if i + 1 < len(lines) and not lines[i + 1].startswith('#'):
                        variant_url = urllib.parse.urljoin(m3u8_url, lines[i + 1].strip())
                        all_variants.append({"bandwidth": bw, "resolution": res, "url": variant_url})

            if all_variants:
                all_variants.sort(key=lambda x: x["bandwidth"], reverse=True)
                settings = _load_settings()
                quality = settings.get("quality", "best")
                selected = _select_quality(all_variants, quality)
                if selected:
                    m3u8_url = selected["url"]
                    print(f"[화질] {quality} → {selected.get('resolution', '?')} ({selected['bandwidth']}bps)")
                else:
                    m3u8_url = all_variants[0]["url"]
    except Exception as e:
        print(f"[M3U8 처리 중 오류] {e}")

    # yt-dlp 호환 형식으로 반환
    return {
        "title": title,
        "url": m3u8_url,
        "thumbnail": thumbnail,
        "duration": 0,
        "http_headers": m3u8_headers,
        "ext": "mp4",
        "_custom_extracted": True,
        "_variants": [{"resolution": v["resolution"], "bandwidth": v["bandwidth"]} for v in all_variants],
    }


# ──────────────────────────────────────────────
# MissAV 검색/관련 영상 스크래핑
# ──────────────────────────────────────────────

def _parse_video_cards(soup, base_url):
    """MissAV 페이지에서 영상 카드 목록을 파싱합니다.
    검색 결과, 관련 영상 등에 공통으로 사용됩니다.

    전략:
    1. 비디오 그리드 컨테이너(div.grid)를 찾아서 그 안의 카드만 파싱 (우선)
    2. 그리드를 못 찾으면, 전체 <a> 태그에서 엄격한 URL 필터링으로 폴백
    """
    results = []
    seen_urls = set()
    parsed_base = urllib.parse.urlparse(base_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

    # ── 비디오 slug 판별 도우미 ──
    def _is_video_slug(slug):
        """비디오 코드 패턴인지 확인 (예: abw-366, fc2-ppv-1234567, ssis-001)"""
        # 반드시 하이픈 뒤에 숫자가 있어야 함
        if not re.search(r'-\d', slug):
            return False
        # 너무 짧은 슬러그 제외
        if len(slug) < 4:
            return False
        # 영문+숫자+하이픈+언더스코어만 허용
        if not re.match(r'^[a-zA-Z0-9][-_a-zA-Z0-9]*$', slug):
            return False
        return True

    def _extract_card_data(a_tag, container=None):
        """<a> 태그와 컨테이너에서 카드 데이터를 추출합니다."""
        href = a_tag.get('href', '')
        full_url = urllib.parse.urljoin(base_origin + '/', href)

        # 이미 처리했으면 건너뜀
        if full_url in seen_urls:
            return None
        seen_urls.add(full_url)

        # URL 검증
        up = urllib.parse.urlparse(full_url)
        if not any(d in up.netloc for d in CUSTOM_DOMAINS):
            return None
        path_parts = [p for p in up.path.strip('/').split('/') if p]
        if not path_parts:
            return None
        slug = path_parts[-1]
        if not _is_video_slug(slug):
            return None

        # 탐색 범위 결정 (컨테이너 → a 태그의 부모 → a 태그 자체)
        card = container or a_tag

        # 썸네일 추출
        thumb = ''
        img = card.find('img')
        if img:
            thumb = img.get('data-src') or img.get('src') or img.get('data-original') or ''
            # 1x1 placeholder 이미지 무시
            if thumb and ('base64' in thumb or len(thumb) < 20):
                thumb = img.get('data-src') or ''
            if thumb and not thumb.startswith('http'):
                thumb = urllib.parse.urljoin(base_origin + '/', thumb)

        # 제목 추출: img alt → a alt → a title → 텍스트
        title = ''
        if img:
            title = (img.get('alt') or '').strip()
        if not title:
            title = (a_tag.get('alt') or a_tag.get('title', '')).strip()
        if not title:
            # 카드 내 텍스트에서 찾기
            for tag_name in ['h3', 'h2', 'h4', 'span', 'div']:
                text_el = card.find(tag_name, string=True)
                if text_el and len(text_el.text.strip()) > 3:
                    title = text_el.text.strip()
                    break
        if not title:
            title = slug

        # Duration 추출: 카드/컨테이너 내 시간 패턴
        duration = ''
        dur_pattern = re.compile(r'\b(\d{1,3}:\d{2}(?::\d{2})?)\b')
        search_area = container or card
        for text_node in search_area.find_all(string=dur_pattern):
            m = dur_pattern.search(str(text_node))
            if m:
                duration = m.group(1)
                break

        return {
            'url': full_url,
            'title': title[:120],
            'thumbnail': thumb,
            'duration': duration,
        }

    # ── 전략 1: 비디오 그리드 컨테이너에서 카드 파싱 ──
    grid = soup.find('div', class_=re.compile(r'grid.*grid-cols'))
    if grid:
        # 그리드 내 직접 자식이 각각의 카드
        for card_div in grid.find_all('div', recursive=False):
            # 카드 내 첫 번째 비디오 링크 찾기
            for a_tag in card_div.find_all('a', href=True):
                href = a_tag['href']
                if '?' in href:
                    continue
                data = _extract_card_data(a_tag, container=card_div)
                if data:
                    results.append(data)
                    break  # 카드당 하나만

    # ── 전략 2: 그리드를 못 찾으면 전체 <a> 태그 스캔 (엄격 필터) ──
    if not results:
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # 쿼리 파라미터 있는 URL 제외 (검색/필터/페이지네이션)
            if '?' in href:
                continue
            # /search/, /site/ 경로 제외
            if '/search/' in href or '/site/' in href:
                continue

            data = _extract_card_data(a_tag)
            if data:
                results.append(data)

    return results


def _extract_related_videos(url: str):
    """비디오 페이지에서 관련(추천) 영상 목록을 추출합니다."""
    try:
        html, session, method = _fetch_page_with_cf_bypass(url)
        soup = BeautifulSoup(html, 'html.parser')
        parsed = urllib.parse.urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # 현재 영상 URL 자체는 제외
        all_cards = _parse_video_cards(soup, base_url)
        # 현재 페이지 URL과 동일한 항목 제외
        uid = _url_id(url)
        related = [c for c in all_cards if _url_id(c['url']) != uid]

        print(f"[관련 영상] {url[:60]}... → {len(related)}개 발견")
        return related
    except Exception as e:
        print(f"[관련 영상] 추출 실패: {e}")
        return []


# ──────────────────────────────────────────────
# 라우트 - 페이지
# ──────────────────────────────────────────────
@app.route("/")
def index():
    import time as _t
    return render_template("index.html", cache_bust=str(int(_t.time())))

@app.route("/search")
def search_page():
    """검색 전용 페이지 (별도 창)"""
    return render_template("search.html")

# ──────────────────────────────────────────────
# API - 검색 & 관련 영상
# ──────────────────────────────────────────────
@app.route("/api/search")
def api_search():
    """MissAV에서 키워드로 영상 검색"""
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', '')  # '', 'views', 'published_at', 'likes'
    if not q:
        return jsonify({"results": [], "query": "", "page": 1, "has_next": False})

    # 검색 URL 구성 (MissAV 검색 패턴)
    base = 'https://missav.ws'
    encoded_q = urllib.parse.quote(q)
    search_url = f"{base}/search/{encoded_q}"
    params = []
    if page > 1:
        params.append(f"page={page}")
    if sort:
        params.append(f"sort={sort}")
    if params:
        search_url += '?' + '&'.join(params)

    try:
        html, session, method = _fetch_page_with_cf_bypass(search_url)
        soup = BeautifulSoup(html, 'html.parser')
        results = _parse_video_cards(soup, base)

        # 다음 페이지 존재 여부 확인
        has_next = False
        # 일반적인 페이지네이션: 다음/next 링크 또는 현재 페이지+1 링크
        for a in soup.find_all('a', href=True):
            if f'page={page + 1}' in a['href']:
                has_next = True
                break
            # rel="next" 패턴
            if a.get('rel') and 'next' in a.get('rel', []):
                has_next = True
                break

        print(f"[검색] '{q}' (page={page}) → {len(results)}개 결과, 다음페이지={has_next}")
        return jsonify({
            "results": results,
            "query": q,
            "page": page,
            "has_next": has_next,
        })
    except Exception as e:
        print(f"[검색] 오류: {e}")
        return jsonify({"error": str(e), "results": [], "query": q, "page": page, "has_next": False}), 500


@app.route("/api/related")
def api_related():
    """비디오 페이지에서 관련(추천) 영상 목록 반환"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"related": [], "error": "URL 필수"})
    related = _extract_related_videos(url)
    return jsonify({"related": related})


@app.route("/api/open-tab", methods=["POST"])
def open_tab():
    """지정 URL을 새 pywebview 탭(사이트 브라우저 창)으로 엽니다.
    대기열의 영상 URL을 사이트에서 직접 재생할 때 사용합니다."""
    body = request.json
    url = body.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL이 비어있습니다."}), 400

    if not _webview_ready.is_set():
        return jsonify({"ok": False, "error": "pywebview not ready"})

    try:
        _open_browse_tab(url)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/open-search", methods=["POST"])
def open_search_window():
    """MissAV 사이트를 pywebview 창에서 직접 열기.
    사이트를 그대로 탐색하면서 대기열에 추가할 수 있습니다.
    JS 인젝션으로 각 영상 카드에 [+] 버튼을 오버레이합니다."""
    global _search_window

    if not _webview_ready.is_set():
        return jsonify({"ok": False, "error": "pywebview not ready"})

    try:
        import webview
    except ImportError:
        return jsonify({"ok": False, "error": "pywebview not installed"})

    def _inject_js_safe(win_ref, label="탐색창"):
        """JS 인젝션을 안전하게 수행 (지연 + 재시도)"""
        import time as _time
        _time.sleep(1.5)
        for attempt in range(5):
            try:
                win_ref.evaluate_js(_BROWSE_INJECT_JS)
                print(f"  [{label}] JS 인젝션 성공 (시도 {attempt+1})")
                return True
            except Exception as e:
                print(f"  [{label}] JS 인젝션 시도 {attempt+1}/5 실패: {e}")
                if attempt < 4:
                    _time.sleep(1.0)
        print(f"  [{label}] JS 인젝션 최종 실패")
        return False

    try:
        # 이미 생성된 창이 있으면 show() + JS 재인젝션
        if _search_window is not None and _search_window in webview.windows:
            _search_window.show()
            # show() 후에도 JS 재인젝션 (페이지 이동 후 사라졌을 수 있음)
            threading.Thread(
                target=_inject_js_safe,
                args=(_search_window, "탐색창-show"),
                daemon=True
            ).start()
            return jsonify({"ok": True, "action": "shown"})

        # 사이트 브라우저 창 동적 생성
        _search_window = webview.create_window(
            title="MissAV — StreamPlayer 탐색",
            url="https://missav.ws",
            width=1100,
            height=800,
            min_size=(700, 500),
            text_select=True,
            js_api=_browse_api,
        )

        if _search_window is None:
            return jsonify({"ok": False, "error": "Window creation returned None"})

        # 클로저 참조 안전하게 캡처
        _sw_ref = _search_window

        # 페이지 로드 완료 시 JS 인젝션 (페이지 이동마다 재인젝션)
        def _on_browse_loaded():
            threading.Thread(
                target=_inject_js_safe,
                args=(_sw_ref, "탐색창-loaded"),
                daemon=True
            ).start()

        _search_window.events.loaded += _on_browse_loaded

        # ★ 핵심 수정: 최초 생성 시 loaded 이벤트 누락 대비 수동 인젝션
        # create_window() 후 페이지가 이미 로드되어 loaded 이벤트를 놓칠 수 있음
        threading.Thread(
            target=_inject_js_safe,
            args=(_sw_ref, "탐색창-초기"),
            daemon=True
        ).start()

        # X 버튼 → 파괴하지 않고 숨기기만
        def _on_search_closing():
            try:
                _search_window.hide()
            except Exception:
                pass
            return False   # 실제 닫기 취소
        _search_window.events.closing += _on_search_closing

        print("  [탐색창] MissAV 사이트 브라우저 생성 완료")
        return jsonify({"ok": True, "action": "created"})

    except Exception as e:
        print(f"[탐색창] 오류: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)})

# ──────────────────────────────────────────────
# API - 대기열 관리
# ──────────────────────────────────────────────
@app.route("/api/queue", methods=["GET"])
def get_queue():
    data = _load_data()
    return jsonify(data["queue"])

@app.route("/api/queue", methods=["POST"])
def add_to_queue():
    """URL을 대기열에 추가합니다."""
    body = request.json
    url = body.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL이 비어있습니다."}), 400

    try:
        info = _extract_info(url)
    except Exception as e:
        return jsonify({"error": f"영상 정보를 가져올 수 없습니다: {str(e)}"}), 400

    uid = _url_id(url)
    entry = {
        "id": uid,
        "url": url,
        "title": info.get("title", url),
        "duration": info.get("duration", 0),
        "thumbnail": info.get("thumbnail", ""),
        "added_at": time.time(),
        "stream_url": info.get("url", ""),
        "http_headers": info.get("http_headers", {}),
        "variants": info.get("_variants", []),
    }

    data = _load_data()
    # 중복 방지
    if any(item["id"] == uid for item in data["queue"]):
        return jsonify({"error": "이미 대기열에 있습니다.", "duplicate": True, "title": entry["title"]}), 409
    data["queue"].append(entry)
    _save_data(data)

    return jsonify(entry)

@app.route("/api/queue/<item_id>", methods=["DELETE"])
def delete_from_queue(item_id):
    data = _load_data()
    data["queue"] = [item for item in data["queue"] if item["id"] != item_id]
    # 관련 재생 위치, 히트맵도 삭제
    data["playback"].pop(item_id, None)
    data["heatmaps"].pop(item_id, None)
    _save_data(data)
    return jsonify({"ok": True})

@app.route("/api/queue/clear", methods=["POST"])
def clear_queue():
    data = _load_data()
    data["queue"] = []
    data["playback"] = {}
    data["heatmaps"] = {}
    _save_data(data)
    return jsonify({"ok": True})

@app.route("/api/queue/reorder", methods=["POST"])
def reorder_queue():
    """대기열 순서를 변경합니다."""
    body = request.json
    id_order = body.get("ids", [])
    if not id_order:
        return jsonify({"error": "ids 필수"}), 400
    data = _load_data()
    id_map = {item["id"]: item for item in data["queue"]}
    new_queue = []
    for uid in id_order:
        if uid in id_map:
            new_queue.append(id_map[uid])
    # id_order에 없는 기존 항목도 유지
    for item in data["queue"]:
        if item["id"] not in id_order:
            new_queue.append(item)
    data["queue"] = new_queue
    _save_data(data)
    return jsonify({"ok": True})

@app.route("/api/queue/move", methods=["POST"])
def move_queue_items():
    """대기열 항목을 맨 위 또는 맨 아래로 이동합니다."""
    body = request.json
    item_ids = body.get("ids", [])
    position = body.get("position", "top")  # "top" or "bottom"
    if not item_ids:
        return jsonify({"error": "ids 필수"}), 400
    data = _load_data()
    id_set = set(item_ids)
    moved = [item for item in data["queue"] if item["id"] in id_set]
    rest = [item for item in data["queue"] if item["id"] not in id_set]
    if position == "top":
        data["queue"] = moved + rest
    else:
        data["queue"] = rest + moved
    _save_data(data)
    return jsonify({"ok": True})

@app.route("/api/queue/bulk-delete", methods=["POST"])
def bulk_delete_queue():
    """여러 대기열 항목을 일괄 삭제합니다."""
    body = request.json
    item_ids = body.get("ids", [])
    if not item_ids:
        return jsonify({"error": "ids 필수"}), 400
    data = _load_data()
    id_set = set(item_ids)
    data["queue"] = [item for item in data["queue"] if item["id"] not in id_set]
    for uid in item_ids:
        data["playback"].pop(uid, None)
        data["heatmaps"].pop(uid, None)
    _save_data(data)
    return jsonify({"ok": True})

@app.route("/api/queue/bulk-category", methods=["POST"])
def bulk_set_category():
    """여러 대기열 항목의 카테고리를 일괄 변경합니다."""
    body = request.json
    item_ids = body.get("ids", [])
    category = body.get("category", None)
    if not item_ids:
        return jsonify({"error": "ids 필수"}), 400
    data = _load_data()
    id_set = set(item_ids)
    for item in data["queue"]:
        if item["id"] in id_set:
            if category:
                item["category"] = category
            else:
                item.pop("category", None)
    _save_data(data)
    return jsonify({"ok": True})

# ──────────────────────────────────────────────
# API - 카테고리 관리
# ──────────────────────────────────────────────
@app.route("/api/categories", methods=["GET"])
def get_categories():
    """카테고리 목록 조회"""
    data = _load_data()
    return jsonify(data.get("categories", []))

@app.route("/api/categories", methods=["POST"])
def create_category():
    """새 카테고리 생성"""
    body = request.json
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "이름을 입력하세요."}), 400
    color = body.get("color", "#4a9eff")
    cat_id = "cat_" + hashlib.md5(f"{name}{time.time()}".encode()).hexdigest()[:8]
    cat = {"id": cat_id, "name": name, "color": color}
    data = _load_data()
    data.setdefault("categories", []).append(cat)
    _save_data(data)
    return jsonify(cat)

@app.route("/api/categories/<cat_id>", methods=["PUT"])
def update_category(cat_id):
    """카테고리 수정 (이름/색상)"""
    body = request.json
    data = _load_data()
    for cat in data.get("categories", []):
        if cat["id"] == cat_id:
            if "name" in body:
                cat["name"] = body["name"].strip()
            if "color" in body:
                cat["color"] = body["color"]
            _save_data(data)
            return jsonify(cat)
    return jsonify({"error": "카테고리를 찾을 수 없습니다."}), 404

@app.route("/api/categories/<cat_id>", methods=["DELETE"])
def delete_category(cat_id):
    """카테고리 삭제 (항목은 미분류로)"""
    data = _load_data()
    data["categories"] = [c for c in data.get("categories", []) if c["id"] != cat_id]
    # 해당 카테고리의 항목들을 미분류로
    for item in data["queue"]:
        if item.get("category") == cat_id:
            item.pop("category", None)
    _save_data(data)
    return jsonify({"ok": True})

@app.route("/api/categories/reorder", methods=["POST"])
def reorder_categories():
    """카테고리 순서 변경"""
    body = request.json
    id_order = body.get("ids", [])
    if not id_order:
        return jsonify({"error": "ids 필수"}), 400
    data = _load_data()
    id_map = {c["id"]: c for c in data.get("categories", [])}
    new_cats = [id_map[cid] for cid in id_order if cid in id_map]
    for c in data.get("categories", []):
        if c["id"] not in id_order:
            new_cats.append(c)
    data["categories"] = new_cats
    _save_data(data)
    return jsonify({"ok": True})

@app.route("/api/queue/<item_id>/category", methods=["POST"])
def set_item_category(item_id):
    """대기열 항목의 카테고리 설정"""
    body = request.json
    category = body.get("category")  # None이면 미분류
    data = _load_data()
    for item in data["queue"]:
        if item["id"] == item_id:
            if category:
                item["category"] = category
            else:
                item.pop("category", None)
            _save_data(data)
            return jsonify({"ok": True, "category": category})
    return jsonify({"error": "항목을 찾을 수 없습니다."}), 404

# ──────────────────────────────────────────────
# API - 재생 위치 기억
# ──────────────────────────────────────────────
@app.route("/api/playback/<item_id>", methods=["GET"])
def get_playback(item_id):
    data = _load_data()
    pb = data.get("playback", {}).get(item_id, {"position": 0})
    return jsonify(pb)

@app.route("/api/playback/<item_id>", methods=["POST"])
def save_playback(item_id):
    body = request.json
    data = _load_data()
    if "playback" not in data:
        data["playback"] = {}
    data["playback"][item_id] = {
        "position": body.get("position", 0),
        "updated_at": time.time(),
    }
    _save_data(data)
    return jsonify({"ok": True})

# ──────────────────────────────────────────────
# API - 히트맵 (자주 반복 구간)
# ──────────────────────────────────────────────
@app.route("/api/heatmap/<item_id>", methods=["GET"])
def get_heatmap(item_id):
    data = _load_data()
    hm = data.get("heatmaps", {}).get(item_id, {})
    return jsonify(hm)

@app.route("/api/heatmap/<item_id>", methods=["POST"])
def save_heatmap(item_id):
    """재생 중 현재 위치(초 단위)를 기록하여 히트맵을 구축합니다."""
    body = request.json
    second = int(body.get("second", 0))
    data = _load_data()
    if "heatmaps" not in data:
        data["heatmaps"] = {}
    if item_id not in data["heatmaps"]:
        data["heatmaps"][item_id] = {}
    key = str(second)
    data["heatmaps"][item_id][key] = data["heatmaps"][item_id].get(key, 0) + 1
    _save_data(data)
    return jsonify({"ok": True})

# ──────────────────────────────────────────────
# API - 영상 스트림 프록시
# ──────────────────────────────────────────────
@app.route("/api/stream")
def stream_video():
    """yt-dlp로 추출한 직접 URL을 프록시하여 브라우저에 전달합니다."""
    url = request.args.get("url", "")
    if not url:
        return "URL required", 400

    try:
        # 대기열에 저장된 stream_url이 있으면 즉시 사용 (재추출 불필요)
        uid = _url_id(url)
        data = _load_data()
        queue_item = next((q for q in data["queue"] if q["id"] == uid), None)
        stored_stream_url = queue_item.get("stream_url", "") if queue_item else ""
        stored_headers = queue_item.get("http_headers", {}) if queue_item else {}

        if stored_stream_url:
            video_url = stored_stream_url
            http_headers = stored_headers
            print(f"[스트림] 저장된 URL 사용 (즉시): {video_url[:80]}...")
        else:
            info = _extract_info(url)
            video_url = info.get("url")
            if not video_url:
                formats = info.get("formats", [])
                if formats:
                    best = formats[-1]
                    video_url = best.get("url")
            if not video_url:
                return "스트림 URL을 찾을 수 없습니다.", 404
            http_headers = info.get("http_headers", {})
            # 대기열에 stream_url 저장 (다음번 즉시 사용)
            if queue_item and video_url:
                queue_item["stream_url"] = video_url
                queue_item["http_headers"] = http_headers
                _save_data(data)
    except Exception as e:
        return f"추출 오류: {e}", 500

    # 헤더 구성 (Referer, Cookie 등)
    headers = {'User-Agent': USER_AGENT}
    if http_headers:
        headers.update(http_headers)

    # HLS(m3u8) 스트림인 경우: 캐시된 M3U8 즉시 반환, 없으면 가져와서 캐시
    if '.m3u8' in video_url:
        try:
            content = _fetch_and_cache_m3u8(video_url, headers)
            response_headers = {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'application/vnd.apple.mpegurl',
                'Cache-Control': 'max-age=300',
            }
            return Response(content, headers=response_headers)
        except Exception as e:
            # URL 만료 등으로 실패 → 재추출 시도
            if stored_stream_url:
                print(f"[스트림] M3U8 로드 실패 ({e}), 재추출...")
                try:
                    info = _extract_info(url, use_cache=False)
                    new_url = info.get("url", "")
                    if new_url:
                        if queue_item:
                            queue_item["stream_url"] = new_url
                            queue_item["http_headers"] = info.get("http_headers", {})
                            _save_data(data)
                        new_headers = {'User-Agent': USER_AGENT}
                        new_headers.update(info.get("http_headers", {}))
                        content = _fetch_and_cache_m3u8(new_url, new_headers)
                        response_headers = {
                            'Access-Control-Allow-Origin': '*',
                            'Content-Type': 'application/vnd.apple.mpegurl',
                            'Cache-Control': 'max-age=300',
                        }
                        return Response(content, headers=response_headers)
                except Exception as e2:
                    return f"재추출 실패: {e2}", 500
            return f"M3U8 프록시 오류: {e}", 500

    # Range 요청 지원
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        resp = requests.get(video_url, headers=headers, stream=True, timeout=30)
        excluded = {"content-encoding", "transfer-encoding", "connection"}
        response_headers = {
            k: v for k, v in resp.headers.items() if k.lower() not in excluded
        }
        response_headers["Access-Control-Allow-Origin"] = "*"

        return Response(
            stream_with_context(resp.iter_content(chunk_size=1024 * 64)),
            status=resp.status_code,
            headers=response_headers,
            content_type=resp.headers.get("Content-Type", "video/mp4"),
        )
    except Exception as e:
        return f"스트림 오류: {e}", 500

# ──────────────────────────────────────────────
# API - 영상 다운로드 (대기열 시스템, 최대 2개 동시)
# ──────────────────────────────────────────────
_download_status = {}  # id -> {status, progress, filename, error, title, url}
_download_queue = []   # [{uid, url, title}, ...] - 대기 중인 다운로드
_download_active = 0   # 현재 다운로드 중인 수
_download_lock = threading.Lock()
_MAX_CONCURRENT_DL = 1  # 1개씩 순차 다운로드 (안정성 + 속도 우선)

def _sanitize_filename(name: str) -> str:
    """파일명에 사용할 수 없는 문자 제거"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    return name[:200] if name else 'video'

def _process_download_queue():
    """대기열에서 다음 다운로드를 시작합니다."""
    global _download_active
    with _download_lock:
        while _download_active < _MAX_CONCURRENT_DL and _download_queue:
            item = _download_queue.pop(0)
            _download_active += 1
            t = threading.Thread(target=_do_download_worker, args=(item,), daemon=True)
            t.start()

def _do_download_worker(dl_item):
    """1개 영상 다운로드 실행 (순차, 동기)"""
    global _download_active
    uid = dl_item["uid"]
    url = dl_item["url"]
    title = dl_item["title"]
    out_filepath = None
    try:
        with _download_lock:
            _download_status[uid]["status"] = "downloading"
        print(f"[다운로드] 시작: {title[:60]}")

        # 다운로드 폴더 설정
        settings = _load_settings()
        dl_folder = settings.get("downloadFolder", "").strip()
        if dl_folder and os.path.isdir(dl_folder):
            out_dir = Path(dl_folder)
        else:
            out_dir = DOWNLOADS_DIR
        out_dir.mkdir(exist_ok=True)

        # 대기열에서 저장된 스트림 URL 확인
        data = _load_data()
        queue_item = next((q for q in data["queue"] if q["id"] == uid), None)
        stream_url = queue_item.get("stream_url", "") if queue_item else ""
        stored_headers = queue_item.get("http_headers", {}) if queue_item else {}

        # stream_url이 없으면 커스텀 도메인인 경우 재추출
        parsed = urllib.parse.urlparse(url)
        is_custom = any(d in parsed.netloc for d in CUSTOM_DOMAINS)
        if not stream_url and is_custom:
            print(f"  [다운로드] stream_url 없음 → 커스텀 추출기로 재추출")
            try:
                re_info = _custom_extract(url)
                stream_url = re_info.get("url", "")
                stored_headers = re_info.get("http_headers", {})
                if queue_item and stream_url:
                    queue_item["stream_url"] = stream_url
                    queue_item["http_headers"] = stored_headers
                    _save_data(data)
            except Exception as e:
                print(f"  [다운로드] 재추출 실패: {e}")

        # 파일명 설정
        safe_title = _sanitize_filename(title)
        out_template = str(out_dir / f"{safe_title}.%(ext)s")

        download_url = url
        if stream_url:
            download_url = stream_url
            opts = {
                "quiet": True,
                "no_warnings": True,
                "format": "best",
                "noplaylist": True,
                "skip_download": False,
                "outtmpl": out_template,
                # ── 속도 최적화 ──
                "concurrent_fragment_downloads": 4,      # 4개 프래그먼트 동시 다운로드
                "buffersize": 1024 * 256,                # 256KB 버퍼
                "http_chunk_size": 1024 * 1024 * 50,     # 50MB 청크
                "retries": 10,
                "fragment_retries": 10,
                "file_access_retries": 5,
                "extractor_retries": 3,
                "noprogress": True,
            }
            if stored_headers:
                opts["http_headers"] = stored_headers
            print(f"  [다운로드] {safe_title} - 저장된 스트림 URL 사용 (프래그먼트 x4)")
        else:
            opts = _ydl_opts(extract_only=False)
            opts["skip_download"] = False
            opts["outtmpl"] = out_template
            opts["concurrent_fragment_downloads"] = 4
            opts["buffersize"] = 1024 * 256
            opts["retries"] = 10
            opts["fragment_retries"] = 10

        def progress_hook(d):
            nonlocal out_filepath
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                speed = d.get("speed") or 0
                with _download_lock:
                    if total > 0:
                        _download_status[uid]["progress"] = round(downloaded / total * 100, 1)
                    if speed > 0:
                        _download_status[uid]["speed"] = speed
            elif d["status"] == "finished":
                out_filepath = d.get("filename", "")
                with _download_lock:
                    _download_status[uid]["progress"] = 100
                    _download_status[uid]["filename"] = out_filepath

        opts["progress_hooks"] = [progress_hook]

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([download_url])

        # 다운로드 완료 후 .part 임시 파일 정리
        _cleanup_temp_files(out_dir, safe_title)

        with _download_lock:
            _download_status[uid]["status"] = "done"
        print(f"  [다운로드] 완료: {title[:60]}")

    except Exception as e:
        print(f"  [다운로드] 오류: {title[:40]} — {e}")
        with _download_lock:
            _download_status[uid]["status"] = "error"
            _download_status[uid]["error"] = str(e)
    finally:
        with _download_lock:
            _download_active -= 1
        # 대기열 다음 처리
        _process_download_queue()


def _cleanup_temp_files(out_dir, safe_title):
    """다운로드 완료 후 .part, .ytdl 등 임시 파일을 정리합니다."""
    import glob
    patterns = [
        str(out_dir / f"{safe_title}*.part"),
        str(out_dir / f"{safe_title}*.part-Frag*"),
        str(out_dir / f"{safe_title}*.ytdl"),
        str(out_dir / f"{safe_title}*.temp"),
    ]
    for pattern in patterns:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                print(f"  [정리] 임시파일 삭제: {os.path.basename(f)}")
            except OSError:
                pass

@app.route("/api/download", methods=["POST"])
def start_download():
    """영상 다운로드를 대기열에 추가합니다."""
    body = request.json
    url = body.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL이 비어있습니다."}), 400

    uid = _url_id(url)
    if uid in _download_status and _download_status[uid].get("status") in ("downloading", "queued"):
        return jsonify({"error": "이미 다운로드 중/대기 중입니다.", "id": uid}), 409

    # 제목 가져오기
    data = _load_data()
    queue_item = next((q for q in data["queue"] if q["id"] == uid), None)
    title = queue_item.get("title", "video") if queue_item else "video"

    with _download_lock:
        _download_status[uid] = {
            "status": "queued", "progress": 0, "filename": "",
            "error": "", "title": title, "url": url, "speed": 0,
        }
        _download_queue.append({"uid": uid, "url": url, "title": title})
    _process_download_queue()

    return jsonify({"id": uid, "status": "queued", "title": title})

@app.route("/api/download/status/<uid>")
def download_status(uid):
    s = _download_status.get(uid, {"status": "unknown"})
    return jsonify(s)

@app.route("/api/download/all-status")
def all_download_status():
    """  모든 다운로드 상태 반환"""
    return jsonify(_download_status)

@app.route("/api/download/file/<uid>")
def download_file(uid):
    s = _download_status.get(uid)
    if not s or s["status"] != "done":
        return "파일이 준비되지 않았습니다.", 404
    filepath = s.get("filename", "")
    if filepath and os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return "파일을 찾을 수 없습니다.", 404

@app.route("/api/download/clear-done", methods=["POST"])
def clear_done_downloads():
    """완료/실패 다운로드 상태 정리"""
    to_remove = [uid for uid, s in _download_status.items()
                 if s.get("status") in ("done", "error")]
    for uid in to_remove:
        del _download_status[uid]
    return jsonify({"cleared": len(to_remove)})

# ──────────────────────────────────────────────
# API - 쿠키 상태
# ──────────────────────────────────────────────
@app.route("/api/cookies/status")
def cookies_status():
    exists = COOKIES_FILE.exists()
    size = COOKIES_FILE.stat().st_size if exists else 0
    cookie_count = 0
    cookie_errors = []
    if exists:
        try:
            from http.cookiejar import MozillaCookieJar
            cj = MozillaCookieJar(str(COOKIES_FILE))
            cj.load(ignore_discard=True, ignore_expires=True)
            cookie_count = len(cj)
        except Exception as e:
            cookie_errors.append(str(e))

    return jsonify({
        "exists": exists,
        "size": size,
        "count": cookie_count,
        "errors": cookie_errors,
        "path": str(COOKIES_FILE),
        "auto_extract": True,  # yt-dlp 내장 브라우저 쿠키 추출 항상 사용 가능
    })


@app.route("/api/debug", methods=["POST"])
def debug_url():
    """URL의 페이지를 가져와서 진단 정보를 반환합니다."""
    body = request.json
    url = body.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL이 비어있습니다."}), 400

    result = {
        "url": url,
        "cookie_file_exists": COOKIES_FILE.exists(),
        "cookie_count": 0,
        "browser_cookie_count": 0,
        "browser_cf_clearance": False,
        "method_used": "",
        "page_length": 0,
        "is_cloudflare_blocked": False,
        "title_found": "",
        "m3u8_found": None,
        "packer_found": False,
        "scripts_count": 0,
        "page_snippet": "",
        "modules": {
            "curl_cffi": False,
            "browser": "",
        },
        "error": None,
    }

    # 모듈 감지
    try:
        __import__('curl_cffi')
        result["modules"]["curl_cffi"] = True
    except ImportError:
        pass
    result["modules"]["browser"] = _get_browser() or "감지 안됨"

    # 쿠키 정보
    if COOKIES_FILE.exists():
        try:
            from http.cookiejar import MozillaCookieJar
            cj = MozillaCookieJar(str(COOKIES_FILE))
            cj.load(ignore_discard=True, ignore_expires=True)
            result["cookie_count"] = len(cj)
        except Exception as e:
            result["error"] = f"쿠키 파일 오류: {e}"
            return jsonify(result)

    # 브라우저 쿠키 확인 (yt-dlp cookie jar)
    cookie_jar, browser_name = _build_cookie_jar_from_browser()
    if cookie_jar and browser_name:
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        parts = domain.split('.')
        base = '.'.join(parts[-2:]) if len(parts) >= 2 else domain
        count = 0
        has_cf = False
        for cookie in cookie_jar:
            cd = cookie.domain.lstrip('.')
            if base in cd or cd in domain:
                count += 1
                if cookie.name == 'cf_clearance':
                    has_cf = True
        result["browser_cookie_count"] = count
        result["browser_cf_clearance"] = has_cf
        result["browser_name"] = browser_name

    # 페이지 가져오기
    try:
        page, session, method = _fetch_page_with_cf_bypass(url)
        result["method_used"] = method
        result["page_length"] = len(page)

        # Cloudflare 차단 감지
        result["is_cloudflare_blocked"] = _is_cf_blocked(page)

        # 페이지 앞부분
        result["page_snippet"] = page[:1500]

        # HTML 분석
        soup = BeautifulSoup(page, 'html.parser')
        h1 = soup.find('h1')
        if h1:
            result["title_found"] = h1.text.strip()[:100]
        else:
            title_tag = soup.find('title')
            if title_tag:
                result["title_found"] = title_tag.text.strip()[:100]

        # 스크립트 분석
        scripts = soup.find_all('script')
        result["scripts_count"] = len(scripts)

        for script in scripts:
            if not script.string:
                continue
            content = script.string

            # 일반 M3U8 검색
            m3u8_match = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", content)
            if m3u8_match and not result["m3u8_found"]:
                result["m3u8_found"] = m3u8_match.group(1)

            # P.A.C.K.E.R. 분석
            packer_match = re.search(
                r"eval\s*\(\s*function\s*\(p,\s*a,\s*c,\s*k,\s*e,\s*d\s*\)\s*\{.*?return\s+p}\s*\((.*)\)\)",
                content, re.DOTALL | re.IGNORECASE
            )
            if packer_match:
                result["packer_found"] = True
                args_str = packer_match.group(1).strip()

                # pcode 추출
                pcode_match = re.match(r"(['\"])(.*?)\1\s*,", args_str)
                if pcode_match:
                    quote = pcode_match.group(1)
                    pcode = pcode_match.group(2).replace(f"\\{quote}", quote)
                    result["packer_pcode_len"] = len(pcode)

                    # base, count
                    remaining = args_str[pcode_match.end():]
                    nums = re.findall(r'(\d+)', remaining)
                    base_n = int(nums[0]) if len(nums) >= 1 else 36
                    result["packer_base"] = base_n

                    # kstr 추출
                    kstr = ""
                    kstr_match = re.search(
                        r",\s*(['\"])((?:\\.|(?!\1)[^\\\r\n])*)\1\s*\.split\(\s*['\"]" + re.escape('|') + r"['\"]\s*\)",
                        args_str, re.VERBOSE
                    )
                    if kstr_match:
                        kq = kstr_match.group(1)
                        kstr = kstr_match.group(2).replace(f"\\{kq}", kq)
                    keywords = kstr.split('|') if kstr else []
                    result["packer_keywords_count"] = len(keywords)
                    result["packer_keywords_preview"] = keywords[:25]

                    # 언팩 시도
                    if kstr:
                        unpacked = _unpack_packer(pcode, base_n, 0, kstr)
                        if unpacked:
                            result["packer_unpacked_len"] = len(unpacked)
                            m3u8_up = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", unpacked)
                            if m3u8_up:
                                result["m3u8_found"] = m3u8_up.group(1)
                                result["m3u8_method"] = "unpack"

                        # 키워드 재구성 시도
                        if not result.get("m3u8_found"):
                            reconstructed = _reconstruct_m3u8_from_keywords(kstr)
                            if reconstructed:
                                result["m3u8_found"] = reconstructed
                                result["m3u8_method"] = "keyword_reconstruct"

        if not result["m3u8_found"]:
            m3u8_page = re.search(r"(https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)", page)
            if m3u8_page:
                result["m3u8_found"] = m3u8_page.group(1)

    except Exception as e:
        result["error"] = str(e)

    return jsonify(result)

# ──────────────────────────────────────────────
# API - 설정
# ──────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(_load_settings())

@app.route("/api/settings", methods=["PUT"])
def update_settings():
    body = request.json
    settings = _load_settings()
    for key in DEFAULT_SETTINGS:
        if key in body:
            settings[key] = body[key]
    _save_settings(settings)
    # 항상 위 설정은 즉시 적용
    if "alwaysOnTop" in body and _webview_window:
        try:
            _webview_window.on_top = body["alwaysOnTop"]
        except Exception:
            pass
    return jsonify(settings)

# ──────────────────────────────────────────────
# API - 항상 위
# ──────────────────────────────────────────────
@app.route("/api/window/ontop", methods=["POST"])
def toggle_ontop():
    body = request.json
    val = body.get("value", False)
    settings = _load_settings()
    settings["alwaysOnTop"] = val
    _save_settings(settings)
    if _webview_window:
        try:
            _webview_window.on_top = val
            return jsonify({"ok": True, "alwaysOnTop": val})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": True, "alwaysOnTop": val, "note": "브라우저 모드에서는 항상위 불가"})

# ──────────────────────────────────────────────
# API - 데이터 내보내기/가져오기
# ──────────────────────────────────────────────
@app.route("/api/data/export", methods=["GET"])
def export_data():
    data = _load_data()
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=streamplayer_backup.json'}
    )

@app.route("/api/data/import", methods=["POST"])
def import_data():
    try:
        if request.content_type and 'multipart' in request.content_type:
            f = request.files.get('file')
            if not f:
                return jsonify({"error": "파일이 없습니다."}), 400
            imported = json.loads(f.read().decode('utf-8'))
        else:
            imported = request.json
        if not isinstance(imported, dict):
            return jsonify({"error": "유효하지 않은 데이터 형식입니다."}), 400
        # 기존 데이터와 병합 (queue, playback, heatmaps, settings)
        data = _load_data()
        if "queue" in imported:
            # 기존 큐에 없는 항목만 추가
            existing_ids = {q["id"] for q in data.get("queue", [])}
            for item in imported["queue"]:
                if item.get("id") not in existing_ids:
                    data.setdefault("queue", []).append(item)
        if "playback" in imported:
            data.setdefault("playback", {}).update(imported["playback"])
        if "heatmaps" in imported:
            data.setdefault("heatmaps", {}).update(imported["heatmaps"])
        if "settings" in imported:
            data["settings"] = {**DEFAULT_SETTINGS, **imported["settings"]}
        _save_data(data)
        return jsonify({"ok": True, "queue_count": len(data.get("queue", []))})
    except Exception as e:
        return jsonify({"error": f"가져오기 실패: {str(e)}"}), 400

@app.route("/api/window/size", methods=["POST"])
def save_window_size():
    body = request.json
    settings = _load_settings()
    if body.get("width"):
        settings["windowWidth"] = body["width"]
    if body.get("height"):
        settings["windowHeight"] = body["height"]
    _save_settings(settings)
    return jsonify({"ok": True})

# ──────────────────────────────────────────────
# API - 브라우저 쿠키 직접 추출
# ──────────────────────────────────────────────
@app.route("/api/cookies/extract", methods=["POST"])
def extract_cookies_now():
    """브라우저에서 쿠키를 직접 추출하여 cookies.txt로 저장합니다."""
    global _detected_browser
    _detected_browser = None  # 캐시 초기화
    browser = _get_browser()
    if not browser:
        return jsonify({"ok": False, "error": "감지된 브라우저가 없습니다."}), 400

    try:
        # yt-dlp에 쿠키 추출 + 저장을 직접 시키기
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiesfrombrowser": (browser,),
            "cookiefile": str(COOKIES_FILE),  # 직접 저장
        }
        ydl = yt_dlp.YoutubeDL(opts)
        cookie_count = len(ydl.cookiejar)
        # yt-dlp는 cookiefile 옵션이 있으면 종료 시 자동 저장
        # 명시적으로 저장
        ydl.cookiejar.save(ignore_discard=True, ignore_expires=True)
        print(f"[쿠키 추출] {browser}에서 {cookie_count}개 쿠키 저장 완료")
        return jsonify({
            "ok": True,
            "browser": browser,
            "count": cookie_count,
            "path": str(COOKIES_FILE),
        })
    except Exception as e:
        # 다른 브라우저 시도
        for alt in ['edge', 'chromium', 'firefox', 'brave']:
            if alt == browser:
                continue
            try:
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "cookiesfrombrowser": (alt,),
                    "cookiefile": str(COOKIES_FILE),
                }
                ydl = yt_dlp.YoutubeDL(opts)
                cookie_count = len(ydl.cookiejar)
                ydl.cookiejar.save(ignore_discard=True, ignore_expires=True)
                print(f"[쿠키 추출] {alt}에서 {cookie_count}개 쿠키 저장 완료 (폴백)")
                return jsonify({
                    "ok": True,
                    "browser": alt,
                    "count": cookie_count,
                    "path": str(COOKIES_FILE),
                })
            except Exception:
                continue
        return jsonify({"ok": False, "error": f"쿠키 추출 실패: {str(e)}"}), 500

# ──────────────────────────────────────────────
# 자동 저장/백업 (주기적 + 종료 시)
# ──────────────────────────────────────────────
import atexit

def _periodic_backup():
    """5분마다 data.json을 자동 백업합니다."""
    import time as _time
    while True:
        _time.sleep(300)  # 5분
        try:
            data = _load_data()
            _save_data(data)
            print("  [자동백업] 주기적 백업 완료")
        except Exception as e:
            print(f"  [자동백업] 실패: {e}")

def _shutdown_save():
    """프로그램 종료 시 최종 저장을 수행합니다."""
    try:
        data = _load_data()
        _save_data(data)
        print("  [종료저장] 최종 저장 완료")
    except Exception as e:
        print(f"  [종료저장] 실패: {e}")

atexit.register(_shutdown_save)
# 백업 스레드 시작
threading.Thread(target=_periodic_backup, daemon=True, name="AutoBackup").start()

# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # 모듈 상태 확인
    mods = []
    for m in ["curl_cffi"]:
        try:
            __import__(m)
            mods.append(f"  ✓ {m}")
        except ImportError:
            mods.append(f"  ✗ {m} (미설치)")
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
        mods.append("  ✓ yt-dlp 브라우저 쿠키 추출")
    except ImportError:
        mods.append("  ✗ yt-dlp 브라우저 쿠키 추출 (yt-dlp 업데이트 필요)")
    print("=" * 50)
    print("  StreamPlayer 서버 시작")
    print(f"  http://localhost:5000")
    print(f"  쿠키: {'✓ cookies.txt 감지됨' if COOKIES_FILE.exists() else '브라우저에서 자동 추출'}")
    print(f"  다운로드 폴더: {DOWNLOADS_DIR}")
    print("  모듈:")
    for m in mods:
        print(m)
    print("=" * 50)
    # 백그라운드 사전 추출 스레드 시작
    threading.Thread(target=_background_preextract, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
