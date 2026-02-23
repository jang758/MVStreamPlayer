/**
 * StreamPlayer 검색 창 - 프론트엔드 로직
 * MissAV 영상 검색, 관련 영상 표시, 플레이어 대기열 추가
 */
(function () {
    'use strict';

    const $ = sel => document.querySelector(sel);
    const searchInput = $('#searchInput');
    const btnSearch = $('#btnSearch');
    const sortSelect = $('#sortSelect');
    const searchStatus = $('#searchStatus');
    const resultsContainer = $('#resultsContainer');
    const resultsEmpty = $('#resultsEmpty');
    const pagination = $('#pagination');
    const btnPrevPage = $('#btnPrevPage');
    const btnNextPage = $('#btnNextPage');
    const pageInfo = $('#pageInfo');
    const relatedOverlay = $('#relatedOverlay');
    const relatedTitle = $('#relatedTitle');
    const relatedInfo = $('#relatedInfo');
    const relatedList = $('#relatedList');
    const relatedClose = $('#relatedClose');

    let currentQuery = '';
    let currentPage = 1;
    let isSearching = false;
    let addedUrls = new Set(); // 이미 추가한 URL 추적

    // ── API 호출 ──
    async function api(url, opts = {}) {
        const resp = await fetch(url, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
        });
        return resp.json();
    }

    function escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }

    function showStatus(msg, type = '') {
        searchStatus.textContent = msg;
        searchStatus.className = 'search-status' + (type ? ` status-${type}` : '');
    }

    // ── 검색 실행 ──
    async function doSearch(query, page = 1) {
        if (!query.trim()) return;
        if (isSearching) return;

        isSearching = true;
        currentQuery = query.trim();
        currentPage = page;
        showStatus('🔍 검색 중...', 'loading');

        try {
            const sort = sortSelect.value;
            const params = new URLSearchParams({ q: currentQuery, page });
            if (sort) params.set('sort', sort);

            const data = await api(`/api/search?${params}`);

            if (data.error) {
                showStatus(`❌ ${data.error}`, 'error');
                return;
            }

            renderResults(data.results);
            updatePagination(data.page, data.has_next);

            if (data.results.length > 0) {
                showStatus(`✅ "${currentQuery}" → ${data.results.length}개 결과 (${page}페이지)`, 'success');
            } else {
                showStatus(`검색 결과가 없습니다: "${currentQuery}"`, 'empty');
            }
        } catch (err) {
            showStatus(`❌ 검색 오류: ${err.message}`, 'error');
        } finally {
            isSearching = false;
        }
    }

    // ── 검색 결과 렌더링 ──
    function renderResults(results) {
        // resultsEmpty 제거
        resultsEmpty.style.display = results.length === 0 ? '' : 'none';

        // 기존 카드 제거
        const oldCards = resultsContainer.querySelectorAll('.video-card');
        oldCards.forEach(c => c.remove());

        results.forEach(item => {
            const card = document.createElement('div');
            card.className = 'video-card';
            const isAdded = addedUrls.has(item.url);

            card.innerHTML = `
                <div class="card-thumb-wrap">
                    <img class="card-thumb" src="${escapeHtml(item.thumbnail || '')}" alt="${escapeHtml(item.title)}" loading="lazy"
                         onerror="this.style.background='#333'">
                    ${item.duration ? `<span class="card-duration">${escapeHtml(item.duration)}</span>` : ''}
                </div>
                <div class="card-info">
                    <div class="card-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
                    <div class="card-actions">
                        <button type="button" class="btn-card-add ${isAdded ? 'added' : ''}" data-url="${escapeHtml(item.url)}" title="${isAdded ? '추가됨' : '대기열에 추가'}">
                            ${isAdded ? '✅ 추가됨' : '+ 추가'}
                        </button>
                        <button type="button" class="btn-card-related" data-url="${escapeHtml(item.url)}" data-title="${escapeHtml(item.title)}" title="관련 영상 보기">
                            📎 관련
                        </button>
                    </div>
                </div>
            `;
            resultsContainer.appendChild(card);
        });
    }

    // ── 페이지네이션 ──
    function updatePagination(page, hasNext) {
        pagination.style.display = 'flex';
        btnPrevPage.disabled = page <= 1;
        btnNextPage.disabled = !hasNext;
        pageInfo.textContent = `${page}페이지`;
    }

    // ── 대기열에 추가 ──
    async function addToQueue(url, btnEl) {
        if (addedUrls.has(url)) return;

        btnEl.disabled = true;
        btnEl.textContent = '⏳ 추가 중...';

        try {
            const result = await api('/api/queue', {
                method: 'POST',
                body: JSON.stringify({ url }),
            });

            if (result.error) {
                btnEl.textContent = '❌ 실패';
                showStatus(`❌ ${result.error}`, 'error');
                setTimeout(() => {
                    btnEl.textContent = '+ 추가';
                    btnEl.disabled = false;
                }, 2000);
                return;
            }

            addedUrls.add(url);
            btnEl.textContent = '✅ 추가됨';
            btnEl.classList.add('added');
            showStatus(`✅ 대기열에 추가: ${result.title || url}`, 'success');
        } catch (err) {
            btnEl.textContent = '❌ 오류';
            showStatus(`❌ ${err.message}`, 'error');
            setTimeout(() => {
                btnEl.textContent = '+ 추가';
                btnEl.disabled = false;
            }, 2000);
        }
    }

    // ── 관련 영상 패널 ──
    async function showRelated(url, title) {
        relatedOverlay.style.display = 'flex';
        relatedTitle.textContent = `관련 영상: ${title}`;
        relatedInfo.innerHTML = `<a href="${escapeHtml(url)}" class="related-url">${escapeHtml(url)}</a>`;
        relatedList.innerHTML = '<div class="loading-spinner">🔄 관련 영상 로딩 중...</div>';

        try {
            const data = await api(`/api/related?url=${encodeURIComponent(url)}`);

            if (!data.related || data.related.length === 0) {
                relatedList.innerHTML = '<div class="related-empty">관련 영상을 찾을 수 없습니다.</div>';
                return;
            }

            relatedList.innerHTML = '';
            data.related.forEach(item => {
                const isAdded = addedUrls.has(item.url);
                const el = document.createElement('div');
                el.className = 'related-item';
                el.innerHTML = `
                    <img class="related-thumb" src="${escapeHtml(item.thumbnail || '')}" alt="" loading="lazy"
                         onerror="this.style.display='none'">
                    <div class="related-item-info">
                        <div class="related-item-title">${escapeHtml(item.title)}</div>
                        ${item.duration ? `<span class="related-item-dur">${escapeHtml(item.duration)}</span>` : ''}
                    </div>
                    <button class="btn-card-add btn-sm ${isAdded ? 'added' : ''}" data-url="${escapeHtml(item.url)}" title="${isAdded ? '추가됨' : '대기열에 추가'}">
                        ${isAdded ? '✅' : '+'}
                    </button>
                `;
                relatedList.appendChild(el);
            });
        } catch (err) {
            relatedList.innerHTML = `<div class="related-empty">❌ 오류: ${err.message}</div>`;
        }
    }

    // ── 이벤트 바인딩 ──
    btnSearch.addEventListener('click', () => doSearch(searchInput.value));
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch(searchInput.value);
    });

    sortSelect.addEventListener('change', () => {
        if (currentQuery) doSearch(currentQuery, 1);
    });

    btnPrevPage.addEventListener('click', () => {
        if (currentPage > 1) doSearch(currentQuery, currentPage - 1);
    });
    btnNextPage.addEventListener('click', () => {
        doSearch(currentQuery, currentPage + 1);
    });

    // 결과 카드 버튼 (이벤트 위임 — 동적 생성된 버튼에도 동작)
    resultsContainer.addEventListener('click', (e) => {
        const addBtn = e.target.closest('.btn-card-add');
        if (addBtn) {
            e.preventDefault();
            e.stopPropagation();
            const url = addBtn.dataset.url;
            if (url && !addBtn.disabled) addToQueue(url, addBtn);
            return;
        }

        const relBtn = e.target.closest('.btn-card-related');
        if (relBtn) {
            e.preventDefault();
            e.stopPropagation();
            const url = relBtn.dataset.url;
            const title = relBtn.dataset.title || '';
            if (url) showRelated(url, title);
            return;
        }

        // 카드 클릭 시 (버튼 외 영역) → 대기열에 추가
        const card = e.target.closest('.video-card');
        if (card) {
            const btn = card.querySelector('.btn-card-add');
            if (btn && !btn.disabled && !btn.classList.contains('added')) {
                const url = btn.dataset.url;
                if (url) addToQueue(url, btn);
            }
        }
    });

    // 관련 영상 패널 이벤트
    relatedClose.addEventListener('click', () => {
        relatedOverlay.style.display = 'none';
    });
    relatedOverlay.addEventListener('click', (e) => {
        if (e.target === relatedOverlay) {
            relatedOverlay.style.display = 'none';
        }
    });

    // 관련 영상 패널 내 추가 버튼 (이벤트 위임)
    relatedList.addEventListener('click', (e) => {
        const addBtn = e.target.closest('.btn-card-add');
        if (addBtn) {
            const url = addBtn.dataset.url;
            if (url) addToQueue(url, addBtn);
        }
    });

    // 이미 추가된 URL 목록 로드
    async function loadExistingQueue() {
        try {
            const queue = await api('/api/queue');
            queue.forEach(item => addedUrls.add(item.url));
        } catch { /* ignore */ }
    }
    loadExistingQueue();

})();
