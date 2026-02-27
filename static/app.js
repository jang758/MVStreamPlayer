/**
 * StreamPlayer - 프론트엔드 앱 로직
 * 대기열 관리, 재생 위치 기억, 히트맵, 단축키, 설정
 */

(function () {
    'use strict';

    // ── DOM 요소 ──
    const $ = (sel) => document.querySelector(sel);
    const video = $('#videoPlayer');
    const overlay = $('#videoOverlay');
    const progressContainer = $('#progressContainer');
    const progressPlayed = $('#progressPlayed');
    const progressBuffered = $('#progressBuffered');
    const progressTooltip = $('#progressTooltip');
    const heatmapBar = $('#heatmapBar');
    const lastPositionMarker = $('#lastPositionMarker');
    const timeDisplay = $('#timeDisplay');
    const btnPlay = $('#btnPlay');
    const btnPrev = $('#btnPrev');
    const btnNext = $('#btnNext');
    const btnBack5 = $('#btnBack5');
    const btnBack10 = $('#btnBack10');
    const btnFwd5 = $('#btnFwd5');
    const btnFwd10 = $('#btnFwd10');
    const btnMute = $('#btnMute');
    const btnFullscreen = $('#btnFullscreen');
    const btnDownload = $('#btnDownload');
    const volumeSlider = $('#volumeSlider');
    const speedSelect = $('#speedSelect');
    const urlInput = $('#urlInput');
    const btnAdd = $('#btnAdd');
    const addStatus = $('#addStatus');
    const queueList = $('#queueList');
    const queueEmpty = $('#queueEmpty');
    const btnClearQueue = $('#btnClearQueue');
    const downloadPanel = $('#downloadPanel');
    const downloadList = $('#downloadList');
    const downloadPanelClose = $('#downloadPanelClose');
    const cookieStatus = $('#cookieStatus');
    const shortcutsToggle = $('#shortcutsToggle');
    const shortcutsPanel = $('#shortcutsPanel');
    const skipLeft = $('#skipLeft');
    const skipRight = $('#skipRight');
    const btnDiag = $('#btnDiag');
    const diagResult = $('#diagResult');
    const btnOnTop = $('#btnOnTop');
    const btnSearchWin = $('#btnSearch');
    const btnSettings = $('#btnSettings');
    const settingsOverlay = $('#settingsOverlay');
    const settingsClose = $('#settingsClose');
    const settingsSave = $('#settingsSave');
    const btnExport = $('#btnExport');
    const btnImport = $('#btnImport');
    const importFile = $('#importFile');
    const infoPanel = $('#infoPanel');
    const infoPanelTitle = $('#infoPanelTitle');
    const infoPanelBody = $('#infoPanelBody');
    const infoPanelClose = $('#infoPanelClose');
    const categoryTabs = $('#categoryTabs');
    const btnCatManage = $('#btnCatManage');
    const catModalOverlay = $('#catModalOverlay');
    const catModalClose = $('#catModalClose');
    const catNewName = $('#catNewName');
    const catNewColor = $('#catNewColor');
    const btnCatAdd = $('#btnCatAdd');
    const catManageList = $('#catManageList');
    const catDropdown = $('#catDropdown');
    const catDropdownList = $('#catDropdownList');
    const btnSelectMode = $('#btnSelectMode');
    const btnQueueTop = $('#btnQueueTop');
    const btnQueueBottom = $('#btnQueueBottom');
    const bulkActionBar = $('#bulkActionBar');
    const bulkCount = $('#bulkCount');
    const bulkSelectAll = $('#bulkSelectAll');
    const bulkMoveTop = $('#bulkMoveTop');
    const bulkMoveBottom = $('#bulkMoveBottom');
    const bulkMoveCat = $('#bulkMoveCat');
    const bulkDelete = $('#bulkDelete');
    const bulkCancel = $('#bulkCancel');
    const ctxMenu = $('#ctxMenu');
    const dlCounter = $('#dlCounter');
    const dlClearDone = $('#dlClearDone');
    const settingMaxDL = $('#settingMaxDL');
    const btnDedupe = $('#btnDedupe');

    // ── 상태 ──
    let queue = [];
    let currentItem = null;
    let currentIndex = -1;
    let heatmapData = {};
    let heatmapInterval = null;
    let savePositionInterval = null;
    let savedLastPosition = 0;
    let skipIndicatorTimeout = null;
    let hlsInstance = null;
    let isOnTop = false;

    // 다중 선택 상태
    let selectMode = false;
    let selectedIds = new Set();

    // 카테고리 상태
    let categories = [];
    let activeCategoryFilter = '__all__'; // '__all__' = 전체 보기

    // 설정 (서버에서 로드)
    let settings = {
        quality: 'best',
        downloadFolder: '',
        skipForward: 10,
        skipBackward: 10,
        skipForwardShift: 5,
        skipBackwardShift: 5,
        defaultVolume: 1.0,
        defaultSpeed: 1.0,
        autoplayNext: true,
        alwaysOnTop: false,
        windowWidth: 1400,
        windowHeight: 850,
        maxConcurrentDownloads: 2,
    };

    // ── 유틸 ──
    function formatTime(secs) {
        if (!secs || isNaN(secs)) return '0:00';
        const h = Math.floor(secs / 3600);
        const m = Math.floor((secs % 3600) / 60);
        const s = Math.floor(secs % 60);
        if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    async function api(url, opts = {}) {
        const res = await fetch(url, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
        });
        return res.json();
    }

    function showStatus(msg, type = '') {
        addStatus.textContent = msg;
        addStatus.className = 'add-status ' + type;
    }

    function showSkipIndicator(side, text) {
        const el = side === 'left' ? skipLeft : skipRight;
        el.querySelector('span').textContent = text;
        el.classList.add('show');
        clearTimeout(skipIndicatorTimeout);
        skipIndicatorTimeout = setTimeout(() => {
            skipLeft.classList.remove('show');
            skipRight.classList.remove('show');
        }, 500);
    }

    // ── 쿠키 상태 확인 ──
    async function checkCookies() {
        try {
            const data = await api('/api/cookies/status');
            const dot = cookieStatus.querySelector('.cookie-dot');
            const text = cookieStatus.querySelector('.cookie-text');
            if (data.auto_extract) {
                dot.className = 'cookie-dot active';
                text.textContent = '브라우저 쿠키 자동 추출 가능';
            } else if (data.exists && data.count > 0) {
                dot.className = 'cookie-dot active';
                text.textContent = `cookies.txt (${data.count}개)`;
            } else {
                dot.className = 'cookie-dot missing';
                text.textContent = '쿠키 없음';
            }
            // 클릭하면 쿠키 추출
            cookieStatus.style.cursor = 'pointer';
            cookieStatus.title = '클릭하여 브라우저 쿠키 추출';
            cookieStatus.onclick = extractCookiesNow;
        } catch {
            // ignore
        }
    }

    async function extractCookiesNow() {
        const text = cookieStatus.querySelector('.cookie-text');
        text.textContent = '쿠키 추출 중...';
        try {
            const res = await api('/api/cookies/extract', { method: 'POST' });
            if (res.ok) {
                const dot = cookieStatus.querySelector('.cookie-dot');
                dot.className = 'cookie-dot active';
                text.textContent = `✅ ${res.browser}에서 ${res.count}개 추출`;
                setTimeout(() => checkCookies(), 3000);
            } else {
                text.textContent = `❌ ${res.error}`;
                setTimeout(() => checkCookies(), 5000);
            }
        } catch (err) {
            text.textContent = `❌ 쿠키 추출 실패`;
            setTimeout(() => checkCookies(), 5000);
        }
    }

    // ── 대기열 ──
    async function loadQueue() {
        queue = await api('/api/queue');
        renderCategoryTabs();
        renderQueue();
    }

    // 다운로드 완료 ID 추적
    let downloadedIds = new Set();
    let selectedInfoId = null; // 클릭으로 선택된 아이템 ID

    function renderQueue() {
        // 카테고리 탭 업데이트
        if (categories.length > 0 || activeCategoryFilter !== '__all__') {
            renderCategoryTabs();
        }

        const filtered = getFilteredQueue();
        queueEmpty.style.display = filtered.length === 0 ? 'block' : 'none';
        if (filtered.length === 0 && queue.length > 0) {
            queueEmpty.innerHTML = '이 카테고리에 영상이 없습니다.';
        } else if (filtered.length === 0) {
            queueEmpty.innerHTML = '대기열이 비어있습니다.<br>URL을 추가해 주세요.';
        }

        // 기존 아이템 제거 (queueEmpty, infoPanel 제외)
        const existingItems = queueList.querySelectorAll('.queue-item');
        existingItems.forEach((el) => el.remove());

        filtered.forEach((item) => {
            const idx = queue.indexOf(item); // 원본 인덱스 (재생용)
            const el = document.createElement('div');
            let cls = 'queue-item';
            if (currentItem && currentItem.id === item.id) cls += ' active';
            if (downloadedIds.has(item.id)) cls += ' downloaded';
            el.className = cls;
            el.dataset.id = item.id;
            el.dataset.index = idx;
            el.draggable = true;  // 드래그 정렬

            // 카테고리 표시
            const cat = getCategoryById(item.category);
            const catIndicatorHtml = cat ? `<span class="cat-indicator" style="background:${cat.color}" title="${escapeHtml(cat.name)}"></span>` : '';
            const catLabel = cat ? cat.name : (categories.length > 0 ? '미분류' : '');
            const catBtnHtml = categories.length > 0 ? `<button class="cat-assign-btn" data-item-id="${item.id}" title="카테고리 변경"><span class="cat-dot" style="background:${cat ? cat.color : '#888'};width:6px;height:6px;border-radius:50%;display:inline-block;margin-right:2px"></span>${escapeHtml(catLabel)}</button>` : '';

            // 다중 선택 모드: 체크박스 + 이동 버튼
            const checkboxHtml = selectMode ? `<input type="checkbox" class="queue-checkbox" data-id="${item.id}" ${selectedIds.has(item.id) ? 'checked' : ''}>` : '';
            const moveHtml = `<div class="item-move-btns">
                <button class="move-btn move-top" data-id="${item.id}" title="맨 위로">⤒</button>
                <button class="move-btn move-bottom" data-id="${item.id}" title="맨 아래로">⤓</button>
            </div>`;

            el.innerHTML = `
                ${checkboxHtml}
                <div class="drag-handle" title="드래그하여 순서 변경">⠿</div>
                ${moveHtml}
                <div class="thumb" style="position:relative">
                    ${item.thumbnail ? `<img src="${item.thumbnail}" alt="" loading="lazy" onerror="this.style.display='none'">` : ''}
                    ${downloadedIds.has(item.id) ? '<span class="dl-badge">✅</span>' : ''}
                    ${catIndicatorHtml}
                </div>
                <div class="info">
                    <div class="title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
                    <div class="meta">${item.duration ? formatTime(item.duration) : ''}${catBtnHtml ? ' · ' + catBtnHtml : ''}</div>
                </div>
                <button class="delete-btn" data-id="${item.id}" title="삭제">✕</button>
            `;
            // 싱글 클릭/더블 클릭 구분 (타이머)
            let qClickTimer = null;
            el.addEventListener('click', (e) => {
                if (e.target.closest('.delete-btn') || e.target.closest('.drag-handle') || e.target.closest('.move-btn') || e.target.closest('.queue-checkbox')) return;
                if (selectMode) {
                    // 선택 모드에서는 클릭으로 체크 토글
                    const cb = el.querySelector('.queue-checkbox');
                    if (cb) { cb.checked = !cb.checked; toggleSelectItem(item.id, cb.checked); }
                    return;
                }
                if (qClickTimer) {
                    clearTimeout(qClickTimer);
                    qClickTimer = null;
                    return; // 더블클릭으로 처리됨
                }
                const capturedItem = item;
                qClickTimer = setTimeout(() => {
                    qClickTimer = null;
                    showItemInfo(capturedItem);
                }, 250);
            });
            // 더블 클릭 → 재생
            el.addEventListener('dblclick', (e) => {
                if (e.target.closest('.delete-btn') || selectMode) return;
                if (qClickTimer) {
                    clearTimeout(qClickTimer);
                    qClickTimer = null;
                }
                hideItemInfo();
                playItem(idx);
            });
            el.querySelector('.delete-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                deleteItem(item.id);
            });

            // 체크박스 이벤트
            const cb = el.querySelector('.queue-checkbox');
            if (cb) {
                cb.addEventListener('change', (e) => {
                    e.stopPropagation();
                    toggleSelectItem(item.id, cb.checked);
                });
            }

            // 개별 이동 버튼 (스크롤 위치 유지)
            el.querySelector('.move-top').addEventListener('click', async (e) => {
                e.stopPropagation();
                const scrollY = queueList.scrollTop;
                await api('/api/queue/move', { method: 'POST', body: JSON.stringify({ ids: [item.id], position: 'top' }) });
                await loadQueue();
                queueList.scrollTop = scrollY;
                showStatus('▲ 맨 위로 이동', 'success');
                setTimeout(() => showStatus(''), 1500);
            });
            el.querySelector('.move-bottom').addEventListener('click', async (e) => {
                e.stopPropagation();
                const scrollY = queueList.scrollTop;
                await api('/api/queue/move', { method: 'POST', body: JSON.stringify({ ids: [item.id], position: 'bottom' }) });
                await loadQueue();
                queueList.scrollTop = scrollY;
                showStatus('▼ 맨 아래로 이동', 'success');
                setTimeout(() => showStatus(''), 1500);
            });

            // 카테고리 지정 버튼
            const catBtn = el.querySelector('.cat-assign-btn');
            if (catBtn) {
                catBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showCatDropdown(item.id, catBtn);
                });
            }

            // 드래그 이벤트
            el.addEventListener('dragstart', (e) => {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', idx.toString());
                el.classList.add('dragging');
            });
            el.addEventListener('dragend', () => {
                el.classList.remove('dragging');
                queueList.querySelectorAll('.queue-item').forEach(i => i.classList.remove('drag-over-item'));
            });
            el.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                el.classList.add('drag-over-item');
            });
            el.addEventListener('dragleave', () => {
                el.classList.remove('drag-over-item');
            });
            el.addEventListener('drop', async (e) => {
                e.preventDefault();
                el.classList.remove('drag-over-item');
                const fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
                const toIdx = idx;
                if (fromIdx === toIdx) return;
                // 로컬 재정렬
                const moved = queue.splice(fromIdx, 1)[0];
                queue.splice(toIdx, 0, moved);
                renderQueue();
                // 서버에 저장
                const ids = queue.map(q => q.id);
                api('/api/queue/reorder', {
                    method: 'POST',
                    body: JSON.stringify({ ids }),
                }).catch(() => { });
            });

            queueList.appendChild(el);
        });

        // 재생 위치 배지 + 다운로드 완료 배지 로드
        queue.forEach(async (item) => {
            try {
                const pb = await api(`/api/playback/${item.id}`);
                if (pb.position > 0) {
                    const el = queueList.querySelector(`[data-id="${item.id}"] .thumb`);
                    if (el && !el.querySelector('.resume-badge')) {
                        const badge = document.createElement('span');
                        badge.className = 'resume-badge';
                        badge.textContent = formatTime(pb.position);
                        el.appendChild(badge);
                    }
                }
            } catch { /* ignore */ }
        });
    }

    // 영상 정보 패널 표시 (고정 DOM 요소 사용)
    function showItemInfo(item) {
        selectedInfoId = item.id;
        const variants = (item.variants || []).map(v =>
            v.resolution || `${Math.round((v.bandwidth || 0) / 1000)}kbps`
        ).join(', ');
        infoPanelTitle.textContent = item.title || '';
        infoPanelBody.innerHTML = `
            <div><strong>URL:</strong> <a href="#" class="info-open-site" data-url="${escapeHtml(item.url)}" style="color:var(--accent);word-break:break-all;cursor:pointer" title="사이트 창에서 열기">${escapeHtml(item.url)}</a></div>
            ${item.duration ? `<div><strong>길이:</strong> ${formatTime(item.duration)}</div>` : ''}
            ${variants ? `<div><strong>화질:</strong> ${variants}</div>` : ''}
            ${downloadedIds.has(item.id) ? '<div><strong>다운로드:</strong> ✅ 완료</div>' : ''}
            <div class="info-related-section">
                <div class="info-related-header">📎 관련 영상</div>
                <div class="info-related-list" id="infoRelatedList_${item.id}">
                    <span class="info-related-loading">로딩 중...</span>
                </div>
            </div>
        `;
        infoPanel.style.display = 'block';

        // 관련 영상 비동기 로드
        loadRelatedForInfoPanel(item);
    }

    async function loadRelatedForInfoPanel(item) {
        const listEl = document.getElementById(`infoRelatedList_${item.id}`);
        if (!listEl) return;

        try {
            const data = await api(`/api/related?url=${encodeURIComponent(item.url)}`);
            if (!data.related || data.related.length === 0) {
                listEl.innerHTML = '<span class="info-related-empty">관련 영상 없음</span>';
                return;
            }
            listEl.innerHTML = data.related.slice(0, 10).map(r => `
                <div class="info-related-item" data-url="${escapeHtml(r.url)}">
                    <img class="info-related-thumb" src="${escapeHtml(r.thumbnail || '')}" alt="" loading="lazy"
                         onerror="this.style.display='none'">
                    <div class="info-related-text">
                        <div class="info-related-title">${escapeHtml(r.title)}</div>
                        ${r.duration ? `<span class="info-related-dur">${escapeHtml(r.duration)}</span>` : ''}
                    </div>
                    <button class="info-related-add" data-url="${escapeHtml(r.url)}" title="대기열에 추가">+</button>
                </div>
            `).join('');
        } catch {
            listEl.innerHTML = '<span class="info-related-empty">로드 실패</span>';
        }
    }

    // 정보 패널 관련 영상 추가 버튼 + URL 사이트 창 열기 (이벤트 위임)
    infoPanelBody.addEventListener('click', async (e) => {
        // URL 클릭 → 사이트 창(pywebview 탭)으로 열기
        const siteLink = e.target.closest('.info-open-site');
        if (siteLink) {
            e.preventDefault();
            e.stopPropagation();
            const url = siteLink.dataset.url;
            if (!url) return;
            siteLink.style.opacity = '0.5';
            try {
                const res = await api('/api/open-tab', {
                    method: 'POST',
                    body: JSON.stringify({ url }),
                });
                if (res.ok) {
                    showStatus('🔗 사이트 창에서 열렸습니다.', 'info');
                    setTimeout(() => showStatus(''), 2000);
                } else {
                    // pywebview 미사용 환경: 브라우저로 폴백
                    window.open(url, '_blank');
                }
            } catch {
                window.open(url, '_blank');
            }
            siteLink.style.opacity = '1';
            return;
        }

        const addBtn = e.target.closest('.info-related-add');
        if (addBtn) {
            e.stopPropagation();
            const url = addBtn.dataset.url;
            if (!url) return;
            addBtn.disabled = true;
            addBtn.textContent = '⏳';
            try {
                const result = await api('/api/queue', {
                    method: 'POST',
                    body: JSON.stringify({ url }),
                });
                if (result.error) {
                    if (result.duplicate) {
                        addBtn.textContent = '✅';
                        addBtn.classList.add('added');
                        showStatus('⚠️ 이미 대기열에 있습니다.', 'error');
                    } else {
                        addBtn.textContent = '❌';
                        showStatus(`❌ ${result.error}`, 'error');
                    }
                    setTimeout(() => { addBtn.textContent = '+'; addBtn.disabled = false; }, 3000);
                    setTimeout(() => showStatus(''), 5000);
                } else {
                    addBtn.textContent = '✅';
                    addBtn.classList.add('added');
                    queue.push(result);
                    renderQueue();
                    showStatus(`✅ 추가: ${result.title || ''}`, 'success');
                    setTimeout(() => showStatus(''), 3000);
                }
            } catch {
                addBtn.textContent = '❌';
                setTimeout(() => { addBtn.textContent = '+'; addBtn.disabled = false; }, 2000);
            }
        }
    });

    function hideItemInfo() {
        selectedInfoId = null;
        infoPanel.style.display = 'none';
    }

    // 정보 패널 닫기 버튼
    infoPanelClose.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        hideItemInfo();
    });

    async function addToQueue() {
        const url = urlInput.value.trim();
        if (!url) return;

        // 클라이언트 측 중복 체크
        const isDuplicate = queue.some(item => item.url === url || item.url === url.split('?')[0]);
        if (isDuplicate) {
            showStatus('⚠️ 이미 대기열에 있는 URL입니다.', 'error');
            setTimeout(() => showStatus(''), 3000);
            return;
        }

        btnAdd.disabled = true;
        showStatus('⏳ 영상 정보를 가져오는 중...', '');

        try {
            const result = await api('/api/queue', {
                method: 'POST',
                body: JSON.stringify({ url }),
            });

            if (result.error) {
                if (result.duplicate) {
                    showStatus('⚠️ 이미 대기열에 있는 URL입니다.', 'error');
                } else {
                    showStatus(`❌ ${result.error}`, 'error');
                }
            } else {
                urlInput.value = '';
                showStatus('✅ 추가되었습니다.', 'success');
                await loadQueue();
                setTimeout(() => showStatus(''), 3000);
            }
        } catch (err) {
            showStatus(`❌ 오류: ${err.message}`, 'error');
        } finally {
            btnAdd.disabled = false;
        }
    }

    async function deleteItem(id) {
        await api(`/api/queue/${id}`, { method: 'DELETE' });
        if (currentItem && currentItem.id === id) {
            stopPlayback();
        }
        await loadQueue();
    }

    async function clearQueue() {
        if (!confirm('대기열을 전체 삭제하시겠습니까?')) return;
        await api('/api/queue/clear', { method: 'POST' });
        stopPlayback();
        await loadQueue();
    }

    // ── URL에서 영상 슬러그 추출 (로케일 접두 제거) ──
    function extractVideoSlug(url) {
        try {
            const u = new URL(url);
            const pathParts = u.pathname.split('/').filter(Boolean);
            // 로케일 접두어 제거 (ko, en, ja, zh 등 2글자 or 2-2글자)
            const slug = pathParts.length > 0 ? pathParts[pathParts.length - 1] : '';
            return slug.toLowerCase();
        } catch {
            return url.split('?')[0].toLowerCase();
        }
    }

    // ── 중복 URL 검토 모달 ──
    async function deduplicateQueue() {
        // 슬러그별로 그룹핑
        const slugMap = new Map(); // slug -> [items]
        for (const item of queue) {
            const slug = extractVideoSlug(item.url);
            if (!slug) continue;
            if (!slugMap.has(slug)) slugMap.set(slug, []);
            slugMap.get(slug).push(item);
        }

        // 2개 이상인 그룹만 추출
        const dupeGroups = [...slugMap.entries()].filter(([, items]) => items.length > 1);

        if (dupeGroups.length === 0) {
            showStatus('✅ 중복된 URL이 없습니다.', 'success');
            setTimeout(() => showStatus(''), 2000);
            return;
        }

        // 모달 생성
        const overlay = document.createElement('div');
        overlay.className = 'dedupe-overlay';

        let groupsHtml = '';
        let totalDupes = 0;
        for (const [slug, items] of dupeGroups) {
            groupsHtml += `<div class="dedupe-group">
                <div class="dedupe-group-header">🔁 "${slug}" — ${items.length}개</div>`;
            items.forEach((item, i) => {
                const isFirst = i === 0;
                if (!isFirst) totalDupes++;
                groupsHtml += `<div class="dedupe-item">
                    ${isFirst
                        ? '<span class="dedupe-item-keep">유지</span>'
                        : `<input type="checkbox" class="dedupe-cb" data-id="${item.id}" checked>`}
                    <img src="${item.thumbnail || ''}" alt="" onerror="this.style.display='none'">
                    <div class="dedupe-item-info">
                        <div class="dedupe-item-title">${escapeHtml(item.title || '제목 없음')}</div>
                        <div class="dedupe-item-url">${escapeHtml(item.url)}</div>
                    </div>
                </div>`;
            });
            groupsHtml += '</div>';
        }

        overlay.innerHTML = `<div class="dedupe-modal">
            <div class="dedupe-header">
                <span>🔁 중복 검토 — ${dupeGroups.length}그룹, ${totalDupes}개 중복</span>
                <button class="dedupe-close-btn">✕</button>
            </div>
            <div class="dedupe-body">${groupsHtml}</div>
            <div class="dedupe-footer">
                <span class="dedupe-count">선택: ${totalDupes}개 삭제 예정</span>
                <div style="display:flex;gap:8px">
                    <button class="dedupe-cancel">취소</button>
                    <button class="dedupe-delete">🗑 선택 삭제</button>
                </div>
            </div>
        </div>`;

        document.body.appendChild(overlay);

        // 이벤트
        const countLabel = overlay.querySelector('.dedupe-count');
        const deleteBtn = overlay.querySelector('.dedupe-delete');

        function updateCount() {
            const checked = overlay.querySelectorAll('.dedupe-cb:checked').length;
            countLabel.textContent = `선택: ${checked}개 삭제 예정`;
            deleteBtn.disabled = checked === 0;
        }

        overlay.querySelectorAll('.dedupe-cb').forEach(cb => {
            cb.addEventListener('change', updateCount);
        });

        overlay.querySelector('.dedupe-close-btn').addEventListener('click', () => overlay.remove());
        overlay.querySelector('.dedupe-cancel').addEventListener('click', () => overlay.remove());
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

        deleteBtn.addEventListener('click', async () => {
            const ids = [...overlay.querySelectorAll('.dedupe-cb:checked')].map(cb => cb.dataset.id);
            if (ids.length === 0) return;
            deleteBtn.disabled = true;
            deleteBtn.textContent = '⏳ 삭제 중...';
            try {
                await api('/api/queue/bulk-delete', {
                    method: 'POST',
                    body: JSON.stringify({ ids }),
                });
                overlay.remove();
                showStatus(`✅ ${ids.length}개 중복 삭제 완료.`, 'success');
                await loadQueue();
                setTimeout(() => showStatus(''), 3000);
            } catch (e) {
                showStatus(`❌ 삭제 오류: ${e.message}`, 'error');
                deleteBtn.textContent = '🗑 선택 삭제';
                deleteBtn.disabled = false;
            }
        });
    }

    // ── 썸네일 호버 원본 크기 미리보기 ──
    const thumbPreview = document.createElement('div');
    thumbPreview.id = 'thumbPreview';
    thumbPreview.innerHTML = '<img>';
    document.body.appendChild(thumbPreview);
    const thumbPreviewImg = thumbPreview.querySelector('img');

    if (queueList) {
        queueList.addEventListener('mouseover', (e) => {
            const img = e.target.closest('.queue-item .thumb img');
            if (!img) return;
            const src = img.src;
            if (!src) return;
            thumbPreviewImg.src = src;
            thumbPreview.style.display = 'block';
        });

        queueList.addEventListener('mousemove', (e) => {
            if (thumbPreview.style.display !== 'block') return;
            // 미리보기를 마우스 왼쪽에 표시
            const pw = 490, ph = 370;
            let x = e.clientX - pw - 20;
            let y = e.clientY - ph / 2;
            if (x < 10) x = e.clientX + 20;
            if (y < 10) y = 10;
            if (y + ph > window.innerHeight - 10) y = window.innerHeight - ph - 10;
            thumbPreview.style.left = x + 'px';
            thumbPreview.style.top = y + 'px';
        });

        queueList.addEventListener('mouseout', (e) => {
            const img = e.target.closest('.queue-item .thumb img');
            if (!img) return;
            thumbPreview.style.display = 'none';
        });
    }

    // ── 재생 ──
    async function playItem(index) {
        if (index < 0 || index >= queue.length) return;

        // 이전 영상 위치 저장
        if (currentItem && video.currentTime > 0) {
            await savePosition();
        }

        currentIndex = index;
        currentItem = queue[index];

        overlay.classList.add('hidden');

        // 이전 HLS 인스턴스 정리
        if (hlsInstance) {
            hlsInstance.destroy();
            hlsInstance = null;
        }
        // 프리뷰 스트림도 정리 (영상 변경 시)
        if (typeof destroyPreviewStream === 'function') destroyPreviewStream();

        // 스트림 URL 설정 (HLS.js 지원)
        const streamUrl = `/api/stream?url=${encodeURIComponent(currentItem.url)}`;

        if (Hls.isSupported()) {
            hlsInstance = new Hls({
                maxBufferLength: 4,         // 4초만 버퍼 후 재생 시작
                maxMaxBufferLength: 30,
                maxBufferSize: 30 * 1000 * 1000,
                startLevel: -1,             // 자동 화질
                autoStartLoad: true,
                lowLatencyMode: false,
                startFragPrefetch: true,
                enableWorker: true,
                testBandwidth: false,       // 대역폭 테스트 건너뛰기
                abrEwmaDefaultEstimate: 5000000, // 5Mbps 가정 (빠른 시작)
                manifestLoadingTimeOut: 15000,
                levelLoadingTimeOut: 15000,
                fragLoadingTimeOut: 30000,
            });
            hlsInstance.loadSource(streamUrl);
            hlsInstance.attachMedia(video);
            hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
                video.play().catch(() => { });
            });
            hlsInstance.on(Hls.Events.ERROR, (event, data) => {
                if (data.fatal) {
                    // HLS 실패 시 직접 src 폴백
                    console.warn('HLS error, falling back to direct src');
                    hlsInstance.destroy();
                    hlsInstance = null;
                    video.src = streamUrl;
                    video.play().catch(() => { });
                }
            });
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            // Safari 네이티브 HLS
            video.src = streamUrl;
        } else {
            // 일반 mp4 등
            video.src = streamUrl;
        }

        // 마지막 재생 위치 복원 (타이밍 문제 해결: 여러 이벤트에서 시도)
        try {
            const pb = await api(`/api/playback/${currentItem.id}`);
            if (pb.position > 0) {
                savedLastPosition = pb.position;
                const seekToSaved = () => {
                    if (savedLastPosition > 0 && savedLastPosition < video.duration - 2) {
                        video.currentTime = savedLastPosition;
                    }
                    showLastPositionMarker();
                };
                // 이미 메타데이터 로드됨
                if (video.readyState >= 1 && video.duration > 0) {
                    seekToSaved();
                } else {
                    // loadedmetadata 또는 canplay 중 먼저 발생하는 이벤트에서 복원
                    let restored = false;
                    const doRestore = () => {
                        if (restored) return;
                        restored = true;
                        video.removeEventListener('loadedmetadata', doRestore);
                        video.removeEventListener('canplay', doRestore);
                        seekToSaved();
                    };
                    video.addEventListener('loadedmetadata', doRestore);
                    video.addEventListener('canplay', doRestore);
                }
            } else {
                savedLastPosition = 0;
            }
        } catch { savedLastPosition = 0; }

        // 히트맵 로드
        loadHeatmap();

        video.play().catch(() => { });

        renderQueue();
        startTrackingIntervals();
    }

    function stopPlayback() {
        if (hlsInstance) {
            hlsInstance.destroy();
            hlsInstance = null;
        }
        video.pause();
        video.removeAttribute('src');
        video.load();
        currentItem = null;
        currentIndex = -1;
        overlay.classList.remove('hidden');
        btnPlay.textContent = '▶';
        clearTrackingIntervals();
        heatmapBar.innerHTML = '';
        lastPositionMarker.style.display = 'none';
        progressPlayed.style.width = '0';
        progressBuffered.style.width = '0';
        timeDisplay.textContent = '0:00 / 0:00';
    }

    function playNext() {
        if (queue.length === 0) return;
        const next = (currentIndex + 1) % queue.length;
        playItem(next);
    }

    function playPrev() {
        if (queue.length === 0) return;
        const prev = (currentIndex - 1 + queue.length) % queue.length;
        playItem(prev);
    }

    // ── 위치 저장 ──
    async function savePosition() {
        if (!currentItem || !video.currentTime) return;
        try {
            await api(`/api/playback/${currentItem.id}`, {
                method: 'POST',
                body: JSON.stringify({ position: video.currentTime }),
            });
        } catch { /* ignore */ }
    }

    // ── 히트맵 ──
    async function loadHeatmap() {
        if (!currentItem) return;
        try {
            heatmapData = await api(`/api/heatmap/${currentItem.id}`);
        } catch {
            heatmapData = {};
        }
        renderHeatmap();
    }

    function renderHeatmap() {
        heatmapBar.innerHTML = '';
        if (!video.duration || video.duration === Infinity) return;

        const keys = Object.keys(heatmapData);
        if (keys.length === 0) return;

        const maxCount = Math.max(...keys.map((k) => heatmapData[k]));
        if (maxCount <= 1) return;

        keys.forEach((sec) => {
            const count = heatmapData[sec];
            if (count <= 1) return;
            const ratio = count / maxCount;
            const left = (parseInt(sec) / video.duration) * 100;
            const width = Math.max((1 / video.duration) * 100, 0.3);

            const seg = document.createElement('div');
            seg.className = 'heatmap-segment';
            seg.style.left = left + '%';
            seg.style.width = width + '%';

            if (ratio > 0.7) seg.style.background = 'var(--heatmap-high)';
            else if (ratio > 0.35) seg.style.background = 'var(--heatmap-mid)';
            else seg.style.background = 'var(--heatmap-low)';

            heatmapBar.appendChild(seg);
        });
    }

    async function recordHeatmapTick() {
        if (!currentItem || video.paused || video.ended) return;
        const sec = Math.floor(video.currentTime);
        try {
            await api(`/api/heatmap/${currentItem.id}`, {
                method: 'POST',
                body: JSON.stringify({ second: sec }),
            });
            // 로컬 히트맵도 업데이트
            const key = String(sec);
            heatmapData[key] = (heatmapData[key] || 0) + 1;
            renderHeatmap();
        } catch { /* ignore */ }
    }

    function showLastPositionMarker() {
        if (!savedLastPosition || !video.duration) {
            lastPositionMarker.style.display = 'none';
            return;
        }
        const pct = (savedLastPosition / video.duration) * 100;
        lastPositionMarker.style.left = pct + '%';
        lastPositionMarker.style.display = 'block';
        lastPositionMarker.title = `마지막 재생: ${formatTime(savedLastPosition)}`;
    }

    // ── 인터벌 관리 ──
    function startTrackingIntervals() {
        clearTrackingIntervals();
        // 히트맵: 2초마다 기록
        heatmapInterval = setInterval(recordHeatmapTick, 2000);
        // 재생 위치: 5초마다 저장
        savePositionInterval = setInterval(savePosition, 5000);
    }

    function clearTrackingIntervals() {
        if (heatmapInterval) clearInterval(heatmapInterval);
        if (savePositionInterval) clearInterval(savePositionInterval);
        heatmapInterval = null;
        savePositionInterval = null;
    }

    // ── 비디오 UI 갱신 ──
    function updateProgress() {
        if (!video.duration || video.duration === Infinity) return;
        const pct = (video.currentTime / video.duration) * 100;
        progressPlayed.style.width = pct + '%';
        timeDisplay.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`;
    }

    function updateBuffered() {
        if (!video.duration || video.buffered.length === 0) return;
        const end = video.buffered.end(video.buffered.length - 1);
        progressBuffered.style.width = (end / video.duration) * 100 + '%';
    }

    // ── 진행 바 상호작용 ──
    let isSeeking = false;

    function seekFromEvent(e) {
        const rect = progressContainer.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        if (video.duration && isFinite(video.duration)) {
            video.currentTime = ratio * video.duration;
            updateProgress();
        }
    }

    progressContainer.addEventListener('mousedown', (e) => {
        isSeeking = true;
        seekFromEvent(e);
    });

    document.addEventListener('mousemove', (e) => {
        if (isSeeking) seekFromEvent(e);

        // 툴팁 표시
        const rect = progressContainer.getBoundingClientRect();
        if (e.clientX >= rect.left && e.clientX <= rect.right &&
            e.clientY >= rect.top && e.clientY <= rect.bottom) {
            const ratio = (e.clientX - rect.left) / rect.width;
            if (video.duration && isFinite(video.duration)) {
                const hoverTime = ratio * video.duration;
                // 시간 텍스트 업데이트
                let timeLabel = progressTooltip.querySelector('.pt-time');
                if (!timeLabel) {
                    timeLabel = document.createElement('span');
                    timeLabel.className = 'pt-time';
                    progressTooltip.appendChild(timeLabel);
                }
                timeLabel.textContent = formatTime(hoverTime);
                progressTooltip.style.left = (ratio * 100) + '%';
                // 캨버스 프레임 미리보기
                updateFramePreview(hoverTime);
            }
        }
    });

    document.addEventListener('mouseup', () => { isSeeking = false; });

    // ── 비디오 이벤트 ──
    video.addEventListener('timeupdate', updateProgress);
    video.addEventListener('progress', updateBuffered);
    video.addEventListener('loadedmetadata', () => {
        updateProgress();
        showLastPositionMarker();
        renderHeatmap();
    });

    video.addEventListener('play', () => { btnPlay.textContent = '⏸'; });
    video.addEventListener('pause', () => { btnPlay.textContent = '▶'; });

    video.addEventListener('ended', () => {
        btnPlay.textContent = '▶';
        savePosition();
        // 다음 영상 자동 재생 (설정에 따라)
        if (settings.autoplayNext && queue.length > 1) {
            setTimeout(playNext, 1000);
        }
    });

    // 영상 클릭: 재생/멈춤 (더블클릭: 전체화면)
    let clickTimer = null;
    video.addEventListener('click', (e) => {
        // 더블클릭과 구분하기 위해 200ms 대기
        if (clickTimer) {
            clearTimeout(clickTimer);
            clickTimer = null;
            return; // 더블클릭 판정 → 무시
        }
        clickTimer = setTimeout(() => {
            clickTimer = null;
            if (video.paused) video.play().catch(() => { });
            else video.pause();
        }, 200);
    });
    video.addEventListener('dblclick', (e) => {
        if (clickTimer) {
            clearTimeout(clickTimer);
            clickTimer = null;
        }
        toggleFullscreen();
    });

    // ── 버튼 이벤트 ──
    btnPlay.addEventListener('click', () => {
        if (video.paused) video.play().catch(() => { });
        else video.pause();
    });

    btnBack5.addEventListener('click', () => { skip(-settings.skipForwardShift); });
    btnBack10.addEventListener('click', () => { skip(-settings.skipForward); });
    btnFwd5.addEventListener('click', () => { skip(settings.skipForwardShift); });
    btnFwd10.addEventListener('click', () => { skip(settings.skipForward); });
    btnPrev.addEventListener('click', playPrev);
    btnNext.addEventListener('click', playNext);

    btnMute.addEventListener('click', () => {
        video.muted = !video.muted;
        btnMute.textContent = video.muted ? '🔇' : '🔊';
    });

    volumeSlider.addEventListener('input', () => {
        video.volume = parseFloat(volumeSlider.value);
        video.muted = false;
        btnMute.textContent = video.volume === 0 ? '🔇' : '🔊';
        // 볼륨 자동 저장
        clearTimeout(volumeSlider._saveTimeout);
        volumeSlider._saveTimeout = setTimeout(() => {
            settings.defaultVolume = video.volume;
            api('/api/settings', {
                method: 'PUT',
                body: JSON.stringify(settings),
            }).catch(() => { });
        }, 500);
    });

    speedSelect.addEventListener('change', () => {
        video.playbackRate = parseFloat(speedSelect.value);
    });

    btnFullscreen.addEventListener('click', toggleFullscreen);

    // ── 구간 다운로드 (Bandicut-style) ──
    const clipPanel = $('#clipPanel');
    const clipStart = $('#clipStart');
    const clipEnd = $('#clipEnd');
    const clipStatus = $('#clipStatus');
    const clipDownloadBtn = $('#clipDownload');
    const clipDuration = $('#clipDuration');
    const clipRangeBar = $('#clipRangeBar');
    const clipRangeFill = $('#clipRangeFill');
    const clipMarkerStart = $('#clipMarkerStart');
    const clipMarkerEnd = $('#clipMarkerEnd');
    const btnClip = $('#btnClip');

    let clipStartSec = 0, clipEndSec = 0;

    function formatTimeHMS(sec) {
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = Math.floor(sec % 60);
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function updateClipUI() {
        clipStart.value = formatTimeHMS(clipStartSec);
        clipEnd.value = formatTimeHMS(clipEndSec);
        const dur = Math.max(0, clipEndSec - clipStartSec);
        const durMin = Math.floor(dur / 60);
        const durS = Math.floor(dur % 60);
        clipDuration.textContent = durMin > 0 ? `${durMin}분 ${durS}초` : `${durS}초`;
        // 범위 바 업데이트
        if (video.duration && isFinite(video.duration) && video.duration > 0) {
            const startPct = (clipStartSec / video.duration) * 100;
            const endPct = (clipEndSec / video.duration) * 100;
            clipMarkerStart.style.left = startPct + '%';
            clipMarkerEnd.style.left = endPct + '%';
            clipRangeFill.style.left = startPct + '%';
            clipRangeFill.style.width = (endPct - startPct) + '%';
        }
    }

    if (btnClip && clipPanel) {
        btnClip.addEventListener('click', () => {
            const isHidden = clipPanel.style.display === 'none';
            clipPanel.style.display = isHidden ? 'block' : 'none';
            if (isHidden && video.duration && isFinite(video.duration)) {
                clipEndSec = Math.floor(video.duration);
                updateClipUI();
            }
        });

        $('#clipClose').addEventListener('click', () => { clipPanel.style.display = 'none'; });

        $('#clipSetStart').addEventListener('click', () => {
            clipStartSec = Math.floor(video.currentTime || 0);
            updateClipUI();
        });

        $('#clipSetEnd').addEventListener('click', () => {
            clipEndSec = Math.floor(video.currentTime || 0);
            updateClipUI();
        });

        // 입력 필드 → 초 동기화
        clipStart.addEventListener('change', () => {
            clipStartSec = parseTimeToSeconds(clipStart.value);
            updateClipUI();
        });
        clipEnd.addEventListener('change', () => {
            clipEndSec = parseTimeToSeconds(clipEnd.value);
            updateClipUI();
        });

        // 드래그 마커
        function setupMarkerDrag(marker, isStart) {
            let dragging = false;
            marker.addEventListener('mousedown', (e) => { dragging = true; e.preventDefault(); });
            document.addEventListener('mousemove', (e) => {
                if (!dragging || !video.duration) return;
                const rect = clipRangeBar.getBoundingClientRect();
                const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                const sec = Math.floor(ratio * video.duration);
                if (isStart) { clipStartSec = Math.min(sec, clipEndSec); }
                else { clipEndSec = Math.max(sec, clipStartSec); }
                updateClipUI();
            });
            document.addEventListener('mouseup', () => { dragging = false; });
        }
        setupMarkerDrag(clipMarkerStart, true);
        setupMarkerDrag(clipMarkerEnd, false);

        // 범위 바 클릭 → 가장 가까운 마커 이동
        clipRangeBar.addEventListener('click', (e) => {
            if (!video.duration) return;
            const rect = clipRangeBar.getBoundingClientRect();
            const ratio = (e.clientX - rect.left) / rect.width;
            const sec = Math.floor(ratio * video.duration);
            const distStart = Math.abs(sec - clipStartSec);
            const distEnd = Math.abs(sec - clipEndSec);
            if (distStart < distEnd) { clipStartSec = sec; }
            else { clipEndSec = sec; }
            if (clipStartSec > clipEndSec) [clipStartSec, clipEndSec] = [clipEndSec, clipStartSec];
            updateClipUI();
        });

        // 다운로드
        clipDownloadBtn.addEventListener('click', async () => {
            if (!currentItem) { clipStatus.textContent = '❌ 영상을 먼저 재생하세요'; return; }
            if (clipEndSec <= clipStartSec) {
                clipStatus.textContent = '❌ 종료 시간이 시작 시간보다 커야 합니다';
                return;
            }

            clipDownloadBtn.disabled = true;
            clipStatus.textContent = '⏳ 준비 중...';

            try {
                const result = await api('/api/clip-download', {
                    method: 'POST',
                    body: JSON.stringify({
                        url: currentItem.url,
                        start: clipStartSec,
                        end: clipEndSec,
                        title: currentItem.title || 'clip',
                    }),
                });

                if (result.error) {
                    clipStatus.textContent = `❌ ${result.error}`;
                    clipDownloadBtn.disabled = false;
                    return;
                }

                const clipId = result.id;
                const pollInterval = setInterval(async () => {
                    try {
                        const st = await api(`/api/clip-status/${clipId}`);
                        switch (st.status) {
                            case 'preparing':
                            case 'extracting':
                                clipStatus.textContent = '⏳ 스트림 추출 중...';
                                break;
                            case 'downloading':
                                clipStatus.textContent = '⬇️ 다운로드 중...';
                                break;
                            case 'done':
                                clearInterval(pollInterval);
                                const sizeMB = st.size ? (st.size / 1024 / 1024).toFixed(1) : '?';
                                clipStatus.textContent = `✅ 완료! (${sizeMB}MB)`;
                                clipDownloadBtn.disabled = false;
                                break;
                            case 'error':
                                clearInterval(pollInterval);
                                clipStatus.textContent = `❌ ${(st.error || '오류').substring(0, 60)}`;
                                clipDownloadBtn.disabled = false;
                                break;
                        }
                    } catch { /* ignore */ }
                }, 2000);
            } catch (err) {
                clipStatus.textContent = `❌ ${err.message}`;
                clipDownloadBtn.disabled = false;
            }
        });
    }

    function parseTimeToSeconds(timeStr) {
        const parts = timeStr.split(':').map(Number);
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + (parts[2] || 0);
        if (parts.length === 2) return parts[0] * 60 + (parts[1] || 0);
        return parts[0] || 0;
    }

    btnAdd.addEventListener('click', addToQueue);
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') addToQueue();
    });

    btnClearQueue.addEventListener('click', clearQueue);
    if (btnDedupe) btnDedupe.addEventListener('click', deduplicateQueue);

    shortcutsToggle.addEventListener('click', () => {
        shortcutsPanel.classList.toggle('show');
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.shortcuts-info')) {
            shortcutsPanel.classList.remove('show');
        }
    });

    // ── 다운로드 (대기열 시스템) ──
    btnDownload.addEventListener('click', async () => {
        if (!currentItem) return;

        try {
            const result = await api('/api/download', {
                method: 'POST',
                body: JSON.stringify({ url: currentItem.url }),
            });

            if (result.error) {
                showStatus(`❌ ${result.error}`, 'error');
                setTimeout(() => showStatus(''), 3000);
                return;
            }

            showStatus(`⬇️ 다운로드 대기열에 추가: ${result.title || ''}`, 'success');
            setTimeout(() => showStatus(''), 3000);

            // 다운로드 진행 표시 시작
            startDownloadPolling(result.id);
        } catch (err) {
            showStatus(`❌ ${err.message}`, 'error');
        }
    });

    // 다운로드 상태 폴링 (다중 동시 지원)
    let downloadPolls = {};

    function startDownloadPolling(uid) {
        if (downloadPolls[uid]) return;

        downloadPanel.style.display = 'block';

        downloadPolls[uid] = setInterval(async () => {
            try {
                const allStatus = await api('/api/download/all-status');
                renderDownloadList(allStatus);

                const s = allStatus[uid];
                if (!s) return;

                if (s.status === 'done') {
                    clearInterval(downloadPolls[uid]);
                    delete downloadPolls[uid];
                    downloadedIds.add(uid);
                    renderQueue();
                    renderDownloadList(allStatus);
                    // 파일 다운로드 트리거
                    const a = document.createElement('a');
                    a.href = `/api/download/file/${uid}`;
                    a.download = '';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                } else if (s.status === 'error') {
                    clearInterval(downloadPolls[uid]);
                    delete downloadPolls[uid];
                    renderDownloadList(allStatus);
                }
            } catch {
                clearInterval(downloadPolls[uid]);
                delete downloadPolls[uid];
            }
        }, 1500);
    }

    function renderDownloadList(allStatus) {
        const entries = Object.entries(allStatus);
        const active = entries.filter(([, s]) => s.status === 'downloading' || s.status === 'queued');
        const done = entries.filter(([, s]) => s.status === 'done');
        const errors = entries.filter(([, s]) => s.status === 'error');

        // 카운터 업데이트
        if (dlCounter) {
            if (active.length > 0) {
                dlCounter.textContent = `(${active.length}개 진행중)`;
            } else if (done.length > 0 || errors.length > 0) {
                dlCounter.textContent = `(완료 ${done.length} / 실패 ${errors.length})`;
            } else {
                dlCounter.textContent = '';
            }
        }

        if (active.length === 0 && Object.keys(downloadPolls).length === 0) {
            if (done.length > 0 || errors.length > 0) {
                downloadList.innerHTML = entries.map(([id, s]) => _renderDlItem(id, s)).join('');
                setTimeout(() => { downloadPanel.style.display = 'none'; }, 8000);
            } else {
                downloadPanel.style.display = 'none';
            }
            return;
        }

        downloadList.innerHTML = entries.map(([id, s]) => _renderDlItem(id, s)).join('');
        downloadPanel.style.display = 'block';
    }

    function _renderDlItem(id, s) {
        const title = (s.title || id).substring(0, 50);
        const pct = s.progress || 0;
        let statusIcon = '';
        let barColor = 'var(--accent)';
        let extraClass = '';
        let statusText = pct + '%';

        if (s.status === 'done') {
            statusIcon = '✅';
            barColor = '#4caf50';
            extraClass = 'dl-done';
            statusText = '완료';
        } else if (s.status === 'error') {
            statusIcon = '❌';
            barColor = '#f44336';
            extraClass = 'dl-error';
            statusText = '실패';
        } else if (s.status === 'downloading') {
            statusIcon = '⬇️';
            // 속도 표시
            const speed = s.speed || 0;
            if (speed > 0) {
                if (speed > 1024 * 1024) {
                    statusText = pct + '% · ' + (speed / 1024 / 1024).toFixed(1) + ' MB/s';
                } else if (speed > 1024) {
                    statusText = pct + '% · ' + (speed / 1024).toFixed(0) + ' KB/s';
                } else {
                    statusText = pct + '% · ' + speed.toFixed(0) + ' B/s';
                }
            }
        } else {
            statusIcon = '⏳';
            extraClass = 'dl-queued';
            statusText = '대기중';
        }

        return `<div class="dl-item ${extraClass}">
            <div class="dl-item-header">
                <span class="dl-item-icon">${statusIcon}</span>
                <span class="dl-item-title">${title}</span>
                <span class="dl-item-pct">${statusText}</span>
            </div>
            <div class="dl-item-bar">
                <div class="dl-item-fill" style="width:${s.status === 'done' ? 100 : pct}%;background:${barColor}"></div>
            </div>
        </div>`;
    }

    // 다운로드 패널 닫기
    downloadPanelClose.addEventListener('click', () => {
        downloadPanel.style.display = 'none';
    });

    // 완료 항목 지우기
    if (dlClearDone) {
        dlClearDone.addEventListener('click', async () => {
            try {
                await api('/api/download/clear-done', { method: 'POST' });
                const allStatus = await api('/api/download/all-status');
                renderDownloadList(allStatus);
            } catch { /* ignore */ }
        });
    }

    // ── 우클릭 컨텍스트 메뉴 ──
    let ctxTargetItem = null;

    if (queueList && ctxMenu) {
        queueList.addEventListener('contextmenu', (e) => {
            const qItem = e.target.closest('.queue-item');
            if (!qItem) return;
            e.preventDefault();

            const idx = parseInt(qItem.dataset.index);
            ctxTargetItem = queue[idx];
            if (!ctxTargetItem) return;

            // 동적 메뉴 생성
            let menuHtml = `
                <div class="ctx-item" data-action="play">▶ 재생</div>
                <div class="ctx-item" data-action="download">⬇️ 다운로드</div>
                <div class="ctx-item" data-action="openSite">🌐 사이트 방문</div>
            `;
            // 카테고리 빠른 이동
            if (categories.length > 0) {
                menuHtml += `<div class="ctx-sep"></div>`;
                for (const cat of categories) {
                    const isCurrent = ctxTargetItem.category === cat.id;
                    menuHtml += `<div class="ctx-item ${isCurrent ? 'ctx-current' : ''}" data-action="moveCat" data-cat-id="${cat.id}"><span class="ctx-cat-dot" style="background:${cat.color}"></span> ${escapeHtml(cat.name)}${isCurrent ? ' ✓' : ''}</div>`;
                }
                menuHtml += `<div class="ctx-item" data-action="moveCat" data-cat-id=""><span class="ctx-cat-dot" style="background:#888"></span> 미분류</div>`;
            }
            menuHtml += `
                <div class="ctx-sep"></div>
                <div class="ctx-item ctx-danger" data-action="delete">🗑 삭제</div>
            `;
            ctxMenu.innerHTML = menuHtml;

            ctxMenu.style.display = 'block';
            // 위치 결정 (화면 밖으로 넘어가지 않게)
            let x = e.clientX, y = e.clientY;
            const mw = ctxMenu.offsetWidth, mh = ctxMenu.offsetHeight;
            if (x + mw > window.innerWidth) x = window.innerWidth - mw - 4;
            if (y + mh > window.innerHeight) y = window.innerHeight - mh - 4;
            ctxMenu.style.left = x + 'px';
            ctxMenu.style.top = y + 'px';
        });

        // 메뉴 항목 클릭
        ctxMenu.addEventListener('click', async (e) => {
            const action = e.target.dataset.action;
            if (!action || !ctxTargetItem) return;
            ctxMenu.style.display = 'none';

            const item = ctxTargetItem;
            ctxTargetItem = null;

            switch (action) {
                case 'play': {
                    const idx = queue.findIndex(q => q.id === item.id);
                    if (idx >= 0) playItem(idx);
                    break;
                }
                case 'download': {
                    try {
                        const result = await api('/api/download', {
                            method: 'POST',
                            body: JSON.stringify({ url: item.url }),
                        });
                        if (result.error) {
                            showStatus(`❌ ${result.error}`, 'error');
                        } else {
                            showStatus(`⬇️ 다운로드: ${result.title || ''}`, 'success');
                            startDownloadPolling(result.id);
                        }
                        setTimeout(() => showStatus(''), 3000);
                    } catch (err) {
                        showStatus(`❌ ${err.message}`, 'error');
                    }
                    break;
                }
                case 'openSite': {
                    try {
                        await api('/api/open-search', {
                            method: 'POST',
                            body: JSON.stringify({ url: item.url }),
                        });
                    } catch {
                        window.open(item.url, '_blank');
                    }
                    break;
                }
                case 'delete': {
                    if (confirm(`"${item.title}" 삭제?`)) {
                        deleteItem(item.id);
                    }
                    break;
                }
                case 'moveCat': {
                    const catId = e.target.closest('.ctx-item')?.dataset.catId || '';
                    try {
                        await api(`/api/queue/${item.id}/category`, {
                            method: 'POST',
                            body: JSON.stringify({ category: catId || null }),
                        });
                        // 로컬 업데이트
                        const qItem = queue.find(q => q.id === item.id);
                        if (qItem) qItem.category = catId || undefined;
                        renderQueue();
                        const catName = catId ? (categories.find(c => c.id === catId)?.name || '') : '미분류';
                        showStatus(`🏷️ ${catName}(으)로 이동`, 'success');
                        setTimeout(() => showStatus(''), 2000);
                    } catch { /* ignore */ }
                    break;
                }
            }
        });

        // 메뉴 바깥 클릭 시 닫기
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.ctx-menu')) {
                ctxMenu.style.display = 'none';
            }
        });
    }

    // ── 스킵 ──
    function skip(seconds) {
        if (!video.duration) return;
        video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seconds));
        if (seconds < 0) showSkipIndicator('left', `${seconds}초`);
        else showSkipIndicator('right', `+${seconds}초`);
    }

    // ── 전체화면 ──
    function toggleFullscreen() {
        const container = $('#videoContainer');
        if (!document.fullscreenElement) {
            container.requestFullscreen().catch(() => { });
        } else {
            document.exitFullscreen().catch(() => { });
        }
    }

    // ── 키보드 단축키 ──
    document.addEventListener('keydown', (e) => {
        // 입력 필드에서는 무시
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

        switch (e.key) {
            case ' ':
                e.preventDefault();
                if (video.paused) video.play().catch(() => { });
                else video.pause();
                break;
            case 'ArrowLeft':
                e.preventDefault();
                skip(e.shiftKey ? -settings.skipForwardShift : -settings.skipForward);
                break;
            case 'ArrowRight':
                e.preventDefault();
                skip(e.shiftKey ? settings.skipForwardShift : settings.skipForward);
                break;
            case 'ArrowUp':
                e.preventDefault();
                video.volume = Math.min(1, video.volume + 0.05);
                volumeSlider.value = video.volume;
                // 볼륨 자동 저장
                clearTimeout(volumeSlider._saveTimeout);
                volumeSlider._saveTimeout = setTimeout(() => {
                    settings.defaultVolume = video.volume;
                    api('/api/settings', { method: 'PUT', body: JSON.stringify(settings) }).catch(() => { });
                }, 1000);
                break;
            case 'ArrowDown':
                e.preventDefault();
                video.volume = Math.max(0, video.volume - 0.05);
                volumeSlider.value = video.volume;
                // 볼륨 자동 저장
                clearTimeout(volumeSlider._saveTimeout);
                volumeSlider._saveTimeout = setTimeout(() => {
                    settings.defaultVolume = video.volume;
                    api('/api/settings', { method: 'PUT', body: JSON.stringify(settings) }).catch(() => { });
                }, 1000);
                break;
            case 'm':
            case 'M':
                video.muted = !video.muted;
                btnMute.textContent = video.muted ? '🔇' : '🔊';
                break;
            case 'f':
            case 'F':
                toggleFullscreen();
                break;
            case 'N':
                if (e.shiftKey) playNext();
                break;
            case 'P':
                if (e.shiftKey) playPrev();
                break;
            case ',':
                // 이전 프레임 (1/30초)
                if (video.paused) video.currentTime = Math.max(0, video.currentTime - 1 / 30);
                break;
            case '.':
                // 다음 프레임
                if (video.paused) video.currentTime = Math.min(video.duration, video.currentTime + 1 / 30);
                break;
        }
    });

    // ── 페이지 나갈 때 위치 저장 ──
    window.addEventListener('beforeunload', () => {
        if (currentItem && video.currentTime > 0) {
            // 동기 저장 (beacon)
            navigator.sendBeacon(
                `/api/playback/${currentItem.id}`,
                new Blob([JSON.stringify({ position: video.currentTime })], { type: 'application/json' })
            );
        }
        // 마지막 재생 항목 + 스크롤 위치 저장
        try {
            localStorage.setItem('sp_last_item', currentItem ? currentItem.id : '');
            localStorage.setItem('sp_last_scroll', queueList ? String(queueList.scrollTop) : '0');
        } catch { /* ignore */ }
    });

    // ── HTML 이스케이프 ──
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    // ── 진단 버튼 ──
    if (btnDiag) {
        btnDiag.addEventListener('click', async () => {
            const url = urlInput.value.trim();
            if (!url) {
                diagResult.style.display = 'block';
                diagResult.innerHTML = '<span class="diag-err">URL을 먼저 입력하세요.</span>';
                return;
            }
            diagResult.style.display = 'block';
            diagResult.innerHTML = '<span class="diag-label">진단 중...</span>';
            btnDiag.disabled = true;
            try {
                const res = await fetch('/api/debug', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url }),
                });
                const d = await res.json();
                if (d.error) {
                    diagResult.innerHTML = `<span class="diag-err">오류: ${escapeHtml(d.error)}</span>`;
                    return;
                }
                let html = '';
                // 모듈 상태
                if (d.modules) {
                    html += `<div><span class="diag-label">모듈:</span> `;
                    const mods = [];
                    for (const [name, ok] of Object.entries(d.modules)) {
                        mods.push(`<span class="${ok ? 'diag-ok' : 'diag-err'}">${name} ${ok ? '✓' : '✗'}</span>`);
                    }
                    html += mods.join(' &nbsp; ') + '</div>';
                }
                // 접근 방식
                if (d.method_used) {
                    html += `<div><span class="diag-label">접근 방식:</span> ${escapeHtml(d.method_used)}</div>`;
                }
                // 브라우저 쿠키
                html += `<div><span class="diag-label">브라우저 쿠키:</span> `;
                if (d.browser_cookie_count > 0) {
                    const bname = d.browser_name ? ` (${d.browser_name})` : '';
                    html += `<span class="diag-ok">${d.browser_cookie_count}개 자동 추출${bname}</span>`;
                    if (d.browser_cf_clearance) {
                        html += ` <span class="diag-ok">cf_clearance ✓</span>`;
                    } else {
                        html += ` <span class="diag-warn">cf_clearance 없음 → 사이트 방문 필요</span>`;
                    }
                } else {
                    html += `<span class="diag-warn">없음 (Chrome/Edge에서 사이트 방문 필요)</span>`;
                }
                html += '</div>';
                // cookies.txt
                html += `<div><span class="diag-label">cookies.txt:</span> `;
                if (d.cookie_count > 0) {
                    html += `<span class="diag-ok">${d.cookie_count}개</span>`;
                } else if (d.cookie_file_exists) {
                    html += `<span class="diag-warn">파일 있으나 쿠키 0개</span>`;
                } else {
                    html += `<span class="diag-warn">없음</span>`;
                }
                html += '</div>';
                // Cloudflare
                html += `<div><span class="diag-label">Cloudflare 차단:</span> `;
                if (d.is_cloudflare_blocked) {
                    html += `<span class="diag-err">차단됨</span>`;
                } else {
                    html += `<span class="diag-ok">통과 ✓</span>`;
                }
                html += '</div>';
                // 페이지 길이
                html += `<div><span class="diag-label">페이지 크기:</span> ${(d.page_length || 0).toLocaleString()} 바이트</div>`;
                // 제목
                if (d.title_found) {
                    html += `<div><span class="diag-label">제목:</span> ${escapeHtml(d.title_found)}</div>`;
                }
                // 스크립트 수
                html += `<div><span class="diag-label">스크립트:</span> ${d.scripts_count || 0}개</div>`;
                // PACKER
                html += `<div><span class="diag-label">P.A.C.K.E.R.:</span> `;
                if (d.packer_found) {
                    html += `<span class="diag-ok">발견됨</span>`;
                    if (d.packer_keywords_count) {
                        html += ` (keywords: ${d.packer_keywords_count}개, base: ${d.packer_base || '?'})`;
                    }
                } else {
                    html += `<span class="diag-warn">없음</span>`;
                }
                html += '</div>';
                // Keywords preview
                if (d.packer_keywords_preview && d.packer_keywords_preview.length > 0) {
                    html += `<div><span class="diag-label">키워드 미리보기:</span> <span style="font-size:11px;color:#aaa">[${d.packer_keywords_preview.map(k => escapeHtml(k)).join(', ')}]</span></div>`;
                }
                // M3U8
                html += `<div><span class="diag-label">M3U8 URL:</span> `;
                if (d.m3u8_found) {
                    html += `<span class="diag-ok">발견됨</span>`;
                    if (d.m3u8_method) {
                        html += ` <span style="color:#8be9fd">(${d.m3u8_method})</span>`;
                    }
                    html += `<div style="font-size:11px;color:#ccc;word-break:break-all;margin-top:2px">${escapeHtml(d.m3u8_found)}</div>`;
                } else {
                    html += `<span class="diag-err">없음</span>`;
                }
                html += '</div>';
                // 페이지 내용 미리보기
                if (d.page_snippet) {
                    html += `<div style="margin-top:8px"><span class="diag-label">페이지 미리보기:</span>`;
                    html += `<pre style="max-height:120px;overflow:auto;font-size:11px;background:#1a1a2e;padding:6px;border-radius:4px;margin-top:4px;white-space:pre-wrap;word-break:break-all">${escapeHtml(d.page_snippet)}</pre></div>`;
                }
                diagResult.innerHTML = html;
            } catch (err) {
                diagResult.innerHTML = `<span class="diag-err">진단 실패: ${escapeHtml(err.message)}</span>`;
            } finally {
                btnDiag.disabled = false;
            }
        });
    }

    // ── 설정 관리 ──
    async function loadSettings() {
        try {
            settings = await api('/api/settings');
            applySettings();
        } catch { /* ignore */ }
    }

    function applySettings() {
        // 볼륨
        video.volume = settings.defaultVolume || 1.0;
        volumeSlider.value = video.volume;

        // 속도
        video.playbackRate = settings.defaultSpeed || 1.0;
        speedSelect.value = String(settings.defaultSpeed || 1.0);

        // 항상 위
        isOnTop = settings.alwaysOnTop || false;
        updateOnTopButton();

        // 건너뛰기 버튼 텍스트 업데이트
        btnBack10.textContent = `⏴${settings.skipForward || 10}`;
        btnFwd10.textContent = `${settings.skipForward || 10}⏵`;
        btnBack5.textContent = `⏴${settings.skipForwardShift || 5}`;
        btnFwd5.textContent = `${settings.skipForwardShift || 5}⏵`;
    }

    function updateOnTopButton() {
        if (isOnTop) {
            btnOnTop.classList.add('active');
            btnOnTop.title = '항상 위 ON';
        } else {
            btnOnTop.classList.remove('active');
            btnOnTop.title = '항상 위 OFF';
        }
    }

    // 설정 모달 열기/닫기
    btnSettings.addEventListener('click', () => {
        // 현재 설정값으로 폼 채우기
        $('#settingQuality').value = settings.quality || 'best';
        $('#settingDownloadFolder').value = settings.downloadFolder || '';
        $('#settingSkipForward').value = settings.skipForward || 10;
        $('#settingSkipShift').value = settings.skipForwardShift || 5;
        $('#settingVolume').value = Math.round((settings.defaultVolume || 1.0) * 100);
        $('#settingVolumeLabel').textContent = Math.round((settings.defaultVolume || 1.0) * 100) + '%';
        $('#settingSpeed').value = String(settings.defaultSpeed || 1.0);
        $('#settingAutoplay').checked = settings.autoplayNext !== false;
        $('#settingOnTop').checked = settings.alwaysOnTop || false;
        if (settingMaxDL) {
            settingMaxDL.value = settings.maxConcurrentDownloads || 2;
            const lbl = $('#settingMaxDLLabel');
            if (lbl) lbl.textContent = (settings.maxConcurrentDownloads || 2) + '개';
        }

        // 현재 영상의 화질 variant 정보 표시
        const vi = $('#variantsInfo');
        if (currentItem && currentItem.variants && currentItem.variants.length > 0) {
            vi.textContent = '사용 가능: ' + currentItem.variants.map(v =>
                v.resolution || `${Math.round(v.bandwidth / 1000)}kbps`
            ).join(', ');
        } else {
            vi.textContent = '';
        }

        settingsOverlay.classList.add('show');
    });

    settingsClose.addEventListener('click', () => {
        settingsOverlay.classList.remove('show');
    });

    settingsOverlay.addEventListener('click', (e) => {
        if (e.target === settingsOverlay) settingsOverlay.classList.remove('show');
    });

    // 볼륨 슬라이더 라벨 업데이트
    const settingVolInput = $('#settingVolume');
    if (settingVolInput) {
        settingVolInput.addEventListener('input', () => {
            $('#settingVolumeLabel').textContent = settingVolInput.value + '%';
        });
    }

    if (settingMaxDL) {
        settingMaxDL.addEventListener('input', () => {
            const lbl = $('#settingMaxDLLabel');
            if (lbl) lbl.textContent = settingMaxDL.value + '개';
        });
    }

    // 설정 저장
    settingsSave.addEventListener('click', async () => {
        const newSettings = {
            quality: $('#settingQuality').value,
            downloadFolder: $('#settingDownloadFolder').value.trim(),
            skipForward: parseInt($('#settingSkipForward').value) || 10,
            skipBackward: parseInt($('#settingSkipForward').value) || 10,
            skipForwardShift: parseInt($('#settingSkipShift').value) || 5,
            skipBackwardShift: parseInt($('#settingSkipShift').value) || 5,
            defaultVolume: parseInt($('#settingVolume').value) / 100,
            defaultSpeed: parseFloat($('#settingSpeed').value) || 1.0,
            autoplayNext: $('#settingAutoplay').checked,
            alwaysOnTop: $('#settingOnTop').checked,
            maxConcurrentDownloads: settingMaxDL ? parseInt(settingMaxDL.value) || 2 : 2,
        };

        try {
            settings = await api('/api/settings', {
                method: 'PUT',
                body: JSON.stringify(newSettings),
            });
            applySettings();
            settingsOverlay.classList.remove('show');
            showStatus('✅ 설정이 저장되었습니다.', 'success');
            setTimeout(() => showStatus(''), 2000);
        } catch (err) {
            showStatus('❌ 설정 저장 실패: ' + err.message, 'error');
        }
    });

    // ── 검색 창 열기 (MissAV 사이트 탐색 창) ──
    btnSearchWin.addEventListener('click', async () => {
        try {
            const res = await api('/api/open-search', { method: 'POST' });
            if (res.ok) {
                showStatus('🔍 MissAV 탐색 창이 열렸습니다.', 'info');
                setTimeout(() => showStatus(''), 2000);
            } else {
                // pywebview 미사용 환경: 팝업 창으로 열기
                window.open('https://missav.ws', 'StreamPlayerBrowse', 'width=1100,height=800,menubar=no,toolbar=no');
            }
        } catch {
            // 서버 연결 실패 시에도 팝업으로 시도
            window.open('https://missav.ws', 'StreamPlayerBrowse', 'width=1100,height=800,menubar=no,toolbar=no');
        }
    });

    // ── 항상 위 토글 ──
    btnOnTop.addEventListener('click', async () => {
        isOnTop = !isOnTop;
        updateOnTopButton();
        try {
            await api('/api/window/ontop', {
                method: 'POST',
                body: JSON.stringify({ value: isOnTop }),
            });
        } catch { /* ignore */ }
    });

    // ── 내보내기/가져오기 ──
    btnExport.addEventListener('click', () => {
        // 내보내기 전 현재 위치 저장
        if (currentItem && video.currentTime > 0) {
            navigator.sendBeacon(
                `/api/playback/${currentItem.id}`,
                new Blob([JSON.stringify({ position: video.currentTime })], { type: 'application/json' })
            );
        }
        // 약간의 지연 후 다운로드 (위치 저장 대기)
        setTimeout(() => {
            window.location.href = '/api/data/export';
        }, 300);
    });

    btnImport.addEventListener('click', () => {
        importFile.click();
    });

    importFile.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/data/import', {
                method: 'POST',
                body: formData,
            });
            const result = await res.json();
            if (result.ok) {
                showStatus(`✅ 가져오기 완료 (대기열: ${result.queue_count}개)`, 'success');
                await loadQueue();
                await loadSettings();
                setTimeout(() => showStatus(''), 3000);
            } else {
                showStatus(`❌ ${result.error}`, 'error');
            }
        } catch (err) {
            showStatus(`❌ 가져오기 실패: ${err.message}`, 'error');
        }
        importFile.value = '';
    });

    // ── 자동 저장 (창 크기) ──
    let windowSaveTimeout = null;
    window.addEventListener('resize', () => {
        clearTimeout(windowSaveTimeout);
        windowSaveTimeout = setTimeout(() => {
            navigator.sendBeacon(
                '/api/window/size',
                new Blob([JSON.stringify({
                    width: window.outerWidth || window.innerWidth,
                    height: window.outerHeight || window.innerHeight,
                })], { type: 'application/json' })
            );
        }, 1000);
    });

    // ── 드래그 앤 드롭 URL 추가 ──
    const dropTarget = document.body;
    ['dragenter', 'dragover'].forEach(evt => {
        dropTarget.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            document.body.classList.add('drag-over');
        });
    });
    ['dragleave', 'drop'].forEach(evt => {
        dropTarget.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            document.body.classList.remove('drag-over');
        });
    });
    dropTarget.addEventListener('drop', async (e) => {
        // URL 추출: 텍스트/uri-list 또는 text/plain
        let droppedUrl = '';
        if (e.dataTransfer.types.includes('text/uri-list')) {
            droppedUrl = e.dataTransfer.getData('text/uri-list').trim();
        } else if (e.dataTransfer.types.includes('text/plain')) {
            droppedUrl = e.dataTransfer.getData('text/plain').trim();
        }
        // URL인지 검증
        if (droppedUrl && (droppedUrl.startsWith('http://') || droppedUrl.startsWith('https://'))) {
            // 첫 번째 줄만 사용 (여러 줄일 수 있음)
            droppedUrl = droppedUrl.split('\n')[0].trim();
            urlInput.value = droppedUrl;
            showStatus('⏳ 드롭된 URL 추가 중...', '');
            await addToQueue();
        }
    });

    // ── 외부 추가 감지 (탐색 창에서 추가 시 반영, 포커스 시에만) ──
    setInterval(async () => {
        if (document.hidden) return;  // 비활성 탭이면 스킵
        try {
            const serverQueue = await api('/api/queue');
            if (serverQueue.length !== queue.length) {
                queue = serverQueue;
                renderCategoryTabs();
                renderQueue();
            }
        } catch { /* ignore */ }
    }, 5000);

    // ──────────────────────────────────────────
    // 대기열 관리 — 스크롤, 다중 선택, 벌크 액션
    // ──────────────────────────────────────────

    // 스크롤 버튼
    btnQueueTop.addEventListener('click', () => { queueList.scrollTo({ top: 0, behavior: 'smooth' }); });
    btnQueueBottom.addEventListener('click', () => { queueList.scrollTo({ top: queueList.scrollHeight, behavior: 'smooth' }); });

    // 다중 선택 모드 토글
    btnSelectMode.addEventListener('click', () => {
        selectMode = !selectMode;
        selectedIds.clear();
        btnSelectMode.classList.toggle('active', selectMode);
        bulkActionBar.style.display = selectMode ? 'flex' : 'none';
        updateBulkCount();
        renderQueue();
    });

    function toggleSelectItem(id, checked) {
        if (checked) selectedIds.add(id);
        else selectedIds.delete(id);
        updateBulkCount();
    }

    function updateBulkCount() {
        bulkCount.textContent = selectedIds.size + '개 선택';
    }

    // 전체 선택
    bulkSelectAll.addEventListener('click', () => {
        const filtered = getFilteredQueue();
        if (selectedIds.size === filtered.length) {
            selectedIds.clear();
        } else {
            filtered.forEach(item => selectedIds.add(item.id));
        }
        updateBulkCount();
        renderQueue();
    });

    // 맨 위로 이동
    bulkMoveTop.addEventListener('click', async () => {
        if (selectedIds.size === 0) return;
        await api('/api/queue/move', { method: 'POST', body: JSON.stringify({ ids: [...selectedIds], position: 'top' }) });
        showStatus(`▲ ${selectedIds.size}개 맨 위로 이동`, 'success');
        selectedIds.clear(); updateBulkCount();
        await loadQueue();
        setTimeout(() => showStatus(''), 2000);
    });

    // 맨 아래로 이동
    bulkMoveBottom.addEventListener('click', async () => {
        if (selectedIds.size === 0) return;
        await api('/api/queue/move', { method: 'POST', body: JSON.stringify({ ids: [...selectedIds], position: 'bottom' }) });
        showStatus(`▼ ${selectedIds.size}개 맨 아래로 이동`, 'success');
        selectedIds.clear(); updateBulkCount();
        await loadQueue();
        setTimeout(() => showStatus(''), 2000);
    });

    // 카테고리 일괄 변경
    bulkMoveCat.addEventListener('click', (e) => {
        if (selectedIds.size === 0) return;
        // 기존 catDropdown 재활용
        const rect = bulkMoveCat.getBoundingClientRect();
        catDropdown.style.top = (rect.bottom + 4) + 'px';
        catDropdown.style.left = Math.min(rect.left, window.innerWidth - 160) + 'px';
        catDropdown.style.display = 'block';

        let html = `<div class="cat-dropdown-item" data-item="__bulk__" data-cat="">
            <span class="cat-dd-dot" style="background:#888"></span> 미분류
        </div>`;
        categories.forEach(cat => {
            html += `<div class="cat-dropdown-item" data-item="__bulk__" data-cat="${cat.id}">
                <span class="cat-dd-dot" style="background:${cat.color}"></span> ${escapeHtml(cat.name)}
            </div>`;
        });
        catDropdownList.innerHTML = html;

        catDropdownList.querySelectorAll('.cat-dropdown-item').forEach(el => {
            el.addEventListener('click', async () => {
                const catId = el.dataset.cat || null;
                catDropdown.style.display = 'none';
                await api('/api/queue/bulk-category', { method: 'POST', body: JSON.stringify({ ids: [...selectedIds], category: catId }) });
                showStatus(`📂 ${selectedIds.size}개 카테고리 변경`, 'success');
                selectedIds.clear(); selectMode = false;
                btnSelectMode.classList.remove('active');
                bulkActionBar.style.display = 'none';
                await loadQueue();
                setTimeout(() => showStatus(''), 2000);
            });
        });
    });

    // 일괄 삭제
    bulkDelete.addEventListener('click', async () => {
        if (selectedIds.size === 0) return;
        if (!confirm(`선택한 ${selectedIds.size}개 항목을 삭제하시겠습니까?`)) return;
        await api('/api/queue/bulk-delete', { method: 'POST', body: JSON.stringify({ ids: [...selectedIds] }) });
        showStatus(`🗑️ ${selectedIds.size}개 삭제됨`, 'success');
        selectedIds.clear(); selectMode = false;
        btnSelectMode.classList.remove('active');
        bulkActionBar.style.display = 'none';
        // 현재 재생 중인 항목이 삭제되었으면 정지
        if (currentItem && selectedIds.has(currentItem.id)) stopPlayback();
        await loadQueue();
        setTimeout(() => showStatus(''), 2000);
    });

    // 선택 취소
    bulkCancel.addEventListener('click', () => {
        selectedIds.clear();
        selectMode = false;
        btnSelectMode.classList.remove('active');
        bulkActionBar.style.display = 'none';
        renderQueue();
    });

    // ──────────────────────────────────────────
    // 카테고리 관리
    // ──────────────────────────────────────────

    async function loadCategories() {
        try {
            categories = await api('/api/categories');
        } catch { categories = []; }
        renderCategoryTabs();
    }

    function renderCategoryTabs() {
        // 기존 동적 탭 제거 (전체 탭은 유지)
        categoryTabs.querySelectorAll('.cat-tab:not([data-cat="__all__"])').forEach(t => t.remove());
        const allTab = categoryTabs.querySelector('[data-cat="__all__"]');

        // 전체 탭 카운트
        const totalCount = queue.length;
        allTab.innerHTML = `전체 <span class="cat-count">${totalCount}</span>`;
        if (activeCategoryFilter === '__all__') allTab.classList.add('active');
        else allTab.classList.remove('active');

        // 미분류 카운트
        const uncatCount = queue.filter(i => !i.category).length;
        if (categories.length > 0 && uncatCount > 0) {
            const uncatTab = document.createElement('button');
            uncatTab.className = 'cat-tab' + (activeCategoryFilter === '__none__' ? ' active' : '');
            uncatTab.dataset.cat = '__none__';
            uncatTab.innerHTML = `미분류 <span class="cat-count">${uncatCount}</span>`;
            uncatTab.addEventListener('click', () => { activeCategoryFilter = '__none__'; renderCategoryTabs(); renderQueue(); });
            categoryTabs.appendChild(uncatTab);
        }

        // 각 카테고리 탭
        categories.forEach(cat => {
            const count = queue.filter(i => i.category === cat.id).length;
            const tab = document.createElement('button');
            tab.className = 'cat-tab' + (activeCategoryFilter === cat.id ? ' active' : '');
            tab.dataset.cat = cat.id;
            tab.innerHTML = `<span class="cat-dot" style="background:${cat.color}"></span>${escapeHtml(cat.name)} <span class="cat-count">${count}</span>`;
            tab.addEventListener('click', () => { activeCategoryFilter = cat.id; renderCategoryTabs(); renderQueue(); });
            categoryTabs.appendChild(tab);
        });

        // 전체 탭 클릭
        allTab.onclick = () => { activeCategoryFilter = '__all__'; renderCategoryTabs(); renderQueue(); };
    }

    function getFilteredQueue() {
        if (activeCategoryFilter === '__all__') return queue;
        if (activeCategoryFilter === '__none__') return queue.filter(i => !i.category);
        return queue.filter(i => i.category === activeCategoryFilter);
    }

    function getCategoryById(catId) {
        return categories.find(c => c.id === catId) || null;
    }

    // 카테고리 지정 드롭다운
    function showCatDropdown(itemId, anchorEl) {
        const rect = anchorEl.getBoundingClientRect();
        catDropdown.style.top = (rect.bottom + 4) + 'px';
        catDropdown.style.left = Math.min(rect.left, window.innerWidth - 160) + 'px';
        catDropdown.style.display = 'block';

        const item = queue.find(i => i.id === itemId);
        const currentCat = item ? item.category : null;

        let html = `<div class="cat-dropdown-item ${!currentCat ? 'active' : ''}" data-item="${itemId}" data-cat="">
            <span class="cat-dd-dot" style="background:#888"></span> 미분류
        </div>`;
        categories.forEach(cat => {
            html += `<div class="cat-dropdown-item ${currentCat === cat.id ? 'active' : ''}" data-item="${itemId}" data-cat="${cat.id}">
                <span class="cat-dd-dot" style="background:${cat.color}"></span> ${escapeHtml(cat.name)}
            </div>`;
        });
        catDropdownList.innerHTML = html;

        // 이벤트
        catDropdownList.querySelectorAll('.cat-dropdown-item').forEach(el => {
            el.addEventListener('click', async () => {
                const catId = el.dataset.cat || null;
                catDropdown.style.display = 'none';
                try {
                    await api(`/api/queue/${itemId}/category`, {
                        method: 'POST',
                        body: JSON.stringify({ category: catId }),
                    });
                    // 로컬 상태 업데이트
                    const qi = queue.find(i => i.id === itemId);
                    if (qi) {
                        if (catId) qi.category = catId;
                        else delete qi.category;
                    }
                    renderCategoryTabs();
                    renderQueue();
                } catch { /* ignore */ }
            });
        });
    }

    // 바깥 클릭 시 드롭다운 닫기
    document.addEventListener('click', (e) => {
        if (catDropdown.style.display !== 'none' && !catDropdown.contains(e.target) && !e.target.closest('.cat-assign-btn')) {
            catDropdown.style.display = 'none';
        }
    });

    // ── 카테고리 관리 모달 ──
    btnCatManage.addEventListener('click', () => {
        catModalOverlay.classList.add('show');
        renderCatManageList();
    });
    catModalClose.addEventListener('click', () => { catModalOverlay.classList.remove('show'); });
    catModalOverlay.addEventListener('click', (e) => { if (e.target === catModalOverlay) catModalOverlay.classList.remove('show'); });

    btnCatAdd.addEventListener('click', async () => {
        const name = catNewName.value.trim();
        if (!name) return;
        const color = catNewColor.value;
        try {
            const cat = await api('/api/categories', {
                method: 'POST',
                body: JSON.stringify({ name, color }),
            });
            if (cat.error) { showStatus('❌ ' + cat.error, 'error'); return; }
            categories.push(cat);
            catNewName.value = '';
            renderCatManageList();
            renderCategoryTabs();
            renderQueue();
        } catch { /* ignore */ }
    });
    catNewName.addEventListener('keydown', (e) => { if (e.key === 'Enter') btnCatAdd.click(); });

    function renderCatManageList() {
        if (categories.length === 0) {
            catManageList.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:12px;text-align:center;">카테고리가 없습니다.<br>위에서 추가해 주세요.</div>';
            return;
        }
        catManageList.innerHTML = categories.map(cat => {
            const count = queue.filter(i => i.category === cat.id).length;
            return `
                <div class="cat-list-item" data-cat-id="${cat.id}">
                    <span class="cat-li-dot" style="background:${cat.color}"></span>
                    <span class="cat-li-name">${escapeHtml(cat.name)}</span>
                    <span class="cat-li-count">${count}개</span>
                    <div class="cat-li-actions">
                        <button class="cat-li-btn cat-rename" data-id="${cat.id}" title="이름 변경">✏️</button>
                        <button class="cat-li-btn danger cat-delete" data-id="${cat.id}" title="삭제">🗑️</button>
                    </div>
                </div>`;
        }).join('');

        // 이름 변경 버튼
        catManageList.querySelectorAll('.cat-rename').forEach(btn => {
            btn.addEventListener('click', async () => {
                const catId = btn.dataset.id;
                const cat = getCategoryById(catId);
                if (!cat) return;
                const newName = prompt('새 이름:', cat.name);
                if (!newName || !newName.trim()) return;
                try {
                    const updated = await api(`/api/categories/${catId}`, {
                        method: 'PUT',
                        body: JSON.stringify({ name: newName.trim() }),
                    });
                    if (!updated.error) {
                        cat.name = updated.name;
                        renderCatManageList();
                        renderCategoryTabs();
                        renderQueue();
                    }
                } catch { /* ignore */ }
            });
        });

        // 삭제 버튼
        catManageList.querySelectorAll('.cat-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                const catId = btn.dataset.id;
                const cat = getCategoryById(catId);
                if (!cat) return;
                if (!confirm(`"${cat.name}" 카테고리를 삭제하시겠습니까?\n항목은 미분류로 이동됩니다.`)) return;
                try {
                    await api(`/api/categories/${catId}`, { method: 'DELETE' });
                    categories = categories.filter(c => c.id !== catId);
                    queue.forEach(i => { if (i.category === catId) delete i.category; });
                    if (activeCategoryFilter === catId) activeCategoryFilter = '__all__';
                    renderCatManageList();
                    renderCategoryTabs();
                    renderQueue();
                } catch { /* ignore */ }
            });
        });
    }

    // ── 초기화 ──
    loadSettings().then(async () => {
        checkCookies();
        await loadCategories();
        await loadQueue();

        // 마지막 재생 항목 복원
        try {
            const lastItemId = localStorage.getItem('sp_last_item');
            const lastScroll = parseInt(localStorage.getItem('sp_last_scroll') || '0');
            if (lastItemId) {
                const idx = queue.findIndex(q => q.id === lastItemId);
                if (idx >= 0) {
                    playItem(idx);
                } else if (queueList) {
                    queueList.scrollTop = lastScroll;
                }
            } else if (queueList) {
                queueList.scrollTop = lastScroll;
            }
        } catch { /* ignore */ }
    });

    // ── 프로그레스 바 프레임 미리보기 (정확한 프레임) ──
    const frameCanvas = document.createElement('canvas');
    frameCanvas.width = 160;
    frameCanvas.height = 90;
    frameCanvas.style.cssText = 'border-radius:3px;display:block;';
    const frameCtx = frameCanvas.getContext('2d');
    let frameInserted = false;
    let lastFrameTime = -1;

    // 숨겨진 프리뷰 비디오 (별도 HLS 인스턴스)
    const previewVideo = document.createElement('video');
    previewVideo.muted = true;
    previewVideo.preload = 'auto';
    previewVideo.style.cssText = 'position:absolute;width:0;height:0;pointer-events:none;opacity:0;';
    document.body.appendChild(previewVideo);
    let previewHls = null;
    let previewStreamUrl = null;
    let previewSeekTimer = null;
    let previewReady = false;

    // 프리뷰 HLS 인스턴스 설정 (메인 영상 변경 시)
    function setupPreviewStream(streamUrl) {
        if (previewStreamUrl === streamUrl && previewHls) return;
        destroyPreviewStream();
        previewStreamUrl = streamUrl;
        previewReady = false;

        if (typeof Hls !== 'undefined' && Hls.isSupported()) {
            previewHls = new Hls({
                maxBufferLength: 2,
                maxMaxBufferLength: 5,
                maxBufferSize: 5 * 1000 * 1000,
                startLevel: 0, // 최저 화질 (빠른 로딩)
                autoStartLoad: true,
                enableWorker: false,
            });
            previewHls.loadSource(streamUrl);
            previewHls.attachMedia(previewVideo);
            previewHls.on(Hls.Events.MANIFEST_PARSED, () => {
                previewReady = true;
            });
            previewHls.on(Hls.Events.ERROR, (event, data) => {
                if (data.fatal) {
                    previewReady = false;
                    destroyPreviewStream();
                }
            });
        } else if (previewVideo.canPlayType('application/vnd.apple.mpegurl')) {
            previewVideo.src = streamUrl;
            previewVideo.addEventListener('loadedmetadata', () => { previewReady = true; }, { once: true });
        }
    }

    function destroyPreviewStream() {
        if (previewHls) {
            previewHls.destroy();
            previewHls = null;
        }
        previewVideo.removeAttribute('src');
        previewVideo.load();
        previewStreamUrl = null;
        previewReady = false;
        lastFrameTime = -1;
    }

    function updateFramePreview(time) {
        if (!video.duration || video.duration === Infinity) return;
        if (!currentItem) return;

        // 툴팁에 캔버스 삽입
        if (!frameInserted) {
            progressTooltip.insertBefore(frameCanvas, progressTooltip.firstChild);
            frameInserted = true;
        }

        // 프리뷰 스트림 초기화 (아직 안 됐으면)
        const streamUrl = `/api/stream?url=${encodeURIComponent(currentItem.url)}`;
        setupPreviewStream(streamUrl);

        if (!previewReady) {
            // 로딩 중 표시
            frameCtx.fillStyle = '#1a1a1a';
            frameCtx.fillRect(0, 0, 160, 90);
            frameCtx.fillStyle = '#888';
            frameCtx.font = '11px sans-serif';
            frameCtx.textAlign = 'center';
            frameCtx.fillText('로딩...', 80, 50);
            return;
        }

        // 1초 단위로만 seek (성능)
        const roundedTime = Math.round(time);
        if (roundedTime === lastFrameTime) return;
        lastFrameTime = roundedTime;

        // 디바운스: 300ms 후에 seek
        clearTimeout(previewSeekTimer);
        previewSeekTimer = setTimeout(() => {
            previewVideo.currentTime = roundedTime;
        }, 300);
    }

    // seeked 이벤트에서 프레임 캡처
    previewVideo.addEventListener('seeked', () => {
        try {
            if (previewVideo.videoWidth > 0) {
                frameCtx.drawImage(previewVideo, 0, 0, frameCanvas.width, frameCanvas.height);
            }
        } catch { /* ignore */ }
    });
})();
