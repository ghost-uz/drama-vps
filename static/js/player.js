/* Drama.uz — reels pleyer [P5-T2].
 *
 * movie_detail.html dagi inline skriptdan ko'chirilgan (CSP/kesh uchun) va
 * kengaytirilgan: resume (WatchProgress), progressni saqlash (10s + yopilishda
 * sendBeacon), tugaganda avto-keyingi qism, imzoli URL muddati o'tsa xavfsiz
 * playback API'dan yangilash [P2-T4/P4-T1], 'm' mute tugmasi.
 *
 * Ma'lumot manbai: #reelsData JSON (server gating'dan o'tgan imzoli URL'lar).
 */
(function () {
'use strict';

/* ─────────────────────────────────────────────────────────
   CONFIG — Django data JSON orqali yuklash
───────────────────────────────────────────────────────── */
const dataEl = document.getElementById('reelsData');
if (!dataEl) return; /* boshqa sahifa — pleyer kerak emas */

const _d         = JSON.parse(dataEl.textContent);
const ALL_EPS    = _d.episodes;
const CUR_EP_NUM = _d.currentEp;
const USE_BUNNY  = _d.useBunny;
const SRC_HLS    = _d.srcHls;
const SRC_720    = _d.src720;
const SRC_1080   = _d.src1080;
const IS_AUTH    = _d.isAuth;
const LOGIN_URL  = _d.loginUrl;
const RESUME_POS   = _d.resumePos || 0;
const PROGRESS_URL = _d.progressUrl || '';
const PLAYBACK_API = _d.playbackApi || '';
const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
const BASE_URL   = window.location.pathname;
const curIdx     = ALL_EPS.indexOf(CUR_EP_NUM);
const prevEpNum  = curIdx > 0                ? ALL_EPS[curIdx - 1] : null;
const nextEpNum  = curIdx < ALL_EPS.length-1 ? ALL_EPS[curIdx + 1] : null;
let   curQual    = '720p';
let   hlsInst    = null;

/* ─────────────────────────────────────────────────────────
   DOM REFS
───────────────────────────────────────────────────────── */
const app        = document.getElementById('reelsApp');
const video      = document.getElementById('mainVideo');
const loader     = document.getElementById('rLoader');
const progress   = document.getElementById('rProgress');
const progressWr = document.getElementById('rProgressWrap');
const flashIcon  = document.getElementById('rFlashIcon');
const flashI     = document.getElementById('rFlashI');
const likeCircle = document.getElementById('likeCircle');
const tapToPlay  = document.getElementById('tapToPlay');
const controlEls = document.querySelectorAll('.controls-ui');

if (!app) return;

/* ─────────────────────────────────────────────────────────
   CONTROLS AUTO-HIDE  (TikTok uslubi)
───────────────────────────────────────────────────────── */
let ctrlHideTimer = null;
let ctrlVisible   = true;

function showControls() {
    ctrlVisible = true;
    controlEls.forEach(el => el.classList.remove('hidden-ui'));
    clearTimeout(ctrlHideTimer);
    if (video && !video.paused) {
        ctrlHideTimer = setTimeout(hideControls, 3000);
    }
}

function hideControls() {
    if (document.querySelector('.r-sheet.open')) return;
    ctrlVisible = false;
    controlEls.forEach(el => el.classList.add('hidden-ui'));
}

showControls();

/* ─────────────────────────────────────────────────────────
   SWIPE NAVIGATION
───────────────────────────────────────────────────────── */
let swipeStartY = 0, swipeStartT = 0;
let mouseStartY = 0, mouseDown  = false;

function navigate(dir) {
    const epNum = dir === 'next' ? nextEpNum : prevEpNum;
    if (!epNum) return;

    const cls = dir === 'next' ? 'slide-up' : 'slide-down';
    app.classList.add(cls);
    setTimeout(() => {
        window.location.href = BASE_URL + '?episode=' + epNum;
    }, 270);
}

app.addEventListener('touchstart', (e) => {
    swipeStartY = e.touches[0].clientY;
    swipeStartT = Date.now();
}, { passive: true });

app.addEventListener('touchend', (e) => {
    if (tapToPlay && !tapToPlay.classList.contains('hide')) return;
    const dy = swipeStartY - e.changedTouches[0].clientY;
    const dt = Date.now() - swipeStartT;
    if (Math.abs(dy) > 70 && dt < 450) {
        navigate(dy > 0 ? 'next' : 'prev');
    } else {
        showControls();
    }
}, { passive: true });

app.addEventListener('mousedown', (e) => {
    if (e.target.closest('.r-topbar, .r-actions, .r-bottom-info, .r-sheet, .r-sheet-backdrop, #libraryModal, .r-progress, #rLoader, #tapToPlay')) return;
    mouseStartY = e.clientY;
    mouseDown   = true;
});
document.addEventListener('mouseup', (e) => {
    if (!mouseDown) return;
    const dy = mouseStartY - e.clientY;
    mouseDown = false;
    if (Math.abs(dy) > 80) navigate(dy > 0 ? 'next' : 'prev');
});

/* ─────────────────────────────────────────────────────────
   XAVFSIZ PLAYBACK API — imzoli URL muddati o'tsa yangilash [P5-T2]
   (token 4 soat amal qiladi [P4-T1]; uzoq sessiyada network-fatal
   xatoda bir marta yangi URL so'raladi)
───────────────────────────────────────────────────────── */
let refreshTried = false;
async function refreshPlaybackUrl() {
    if (!PLAYBACK_API || refreshTried) return null;
    refreshTried = true;
    try {
        const resp = await fetch(PLAYBACK_API, { credentials: 'same-origin' });
        if (!resp.ok) return null;
        const data = await resp.json();
        return data.hls_url || null;
    } catch (_) {
        return null;
    }
}

function fallbackToMp4() {
    if (hlsInst) { hlsInst.destroy(); hlsInst = null; }
    if (SRC_720) video.src = SRC_720;
}

/* ─────────────────────────────────────────────────────────
   HLS.JS INIT — Bunny Stream adaptive streaming
───────────────────────────────────────────────────────── */
function initHls() {
    if (!video || !SRC_HLS) return;
    if (typeof Hls === 'undefined') {
        if (SRC_720) video.src = SRC_720;
        return;
    }
    if (Hls.isSupported()) {
        hlsInst = new Hls({ enableWorker: true, lowLatencyMode: false });
        hlsInst.loadSource(SRC_HLS);
        hlsInst.attachMedia(video);
        hlsInst.on(Hls.Events.ERROR, function (_, data) {
            if (!data.fatal) return;
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                /* Token muddati o'tgan bo'lishi mumkin — API'dan yangi imzoli URL */
                refreshPlaybackUrl().then((fresh) => {
                    if (fresh && hlsInst) {
                        const pos = video.currentTime;
                        hlsInst.loadSource(fresh);
                        hlsInst.startLoad();
                        video.addEventListener('loadedmetadata', () => {
                            video.currentTime = pos;
                        }, { once: true });
                    } else {
                        fallbackToMp4();
                    }
                });
                return;
            }
            fallbackToMp4();
        });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        /* Safari — native HLS qo'llab-quvvatlaydi */
        video.src = SRC_HLS;
    } else if (SRC_720) {
        video.src = SRC_720;
    }
}

if (USE_BUNNY) initHls();

/* ─────────────────────────────────────────────────────────
   RESUME — to'xtagan joydan davom etish (WatchProgress) [P5-T2]
───────────────────────────────────────────────────────── */
if (video && RESUME_POS > 5) {
    video.addEventListener('loadedmetadata', () => {
        /* Deyarli tugagan joyga qaytarmaymiz (boshidan ko'rish tabiiyroq) */
        if (video.duration && RESUME_POS < video.duration * 0.95) {
            video.currentTime = RESUME_POS;
        }
    }, { once: true });
}

/* ─────────────────────────────────────────────────────────
   PROGRESSNI SAQLASH — har 10s + pauza + sahifa yopilishida [P5-T2]
   (drama:save_watch_progress, P1-T3; faqat login foydalanuvchi)
───────────────────────────────────────────────────────── */
let lastSavedPos = -1;

function buildProgressForm(completed) {
    const form = new FormData();
    form.append('position_seconds', String(Math.floor(video.currentTime || 0)));
    form.append('duration_seconds', String(Math.floor(video.duration || 0)));
    if (completed) form.append('completed', '1');
    form.append('csrfmiddlewaretoken', CSRF);
    return form;
}

function saveProgress(useBeacon, completed) {
    if (!IS_AUTH || !PROGRESS_URL || !video || !video.duration) return;
    const pos = Math.floor(video.currentTime);
    if (!completed && !useBeacon && Math.abs(pos - lastSavedPos) < 5) return;
    lastSavedPos = pos;
    const form = buildProgressForm(completed);
    if (useBeacon && navigator.sendBeacon) {
        navigator.sendBeacon(PROGRESS_URL, form);
    } else {
        fetch(PROGRESS_URL, {
            method: 'POST', body: form, credentials: 'same-origin', keepalive: true,
        }).catch(() => {});
    }
}

if (video) {
    setInterval(() => {
        if (!video.paused && !video.ended) saveProgress(false, false);
    }, 10000);
    video.addEventListener('pause', () => saveProgress(false, false));
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') saveProgress(true, false);
    });

    /* ─── AVTO-KEYINGI QISM: tugaganda [P5-T2] ─── */
    video.addEventListener('ended', () => {
        saveProgress(true, true); /* completed=1 — beacon bilan, navigatsiyada yo'qolmaydi */
        if (nextEpNum) navigate('next');
        else showControls();
    });
}

/* ─────────────────────────────────────────────────────────
   VIDEO PLAYER LOGIC
───────────────────────────────────────────────────────── */
if (video) {
    /* Loader */
    video.addEventListener('waiting', () => loader.classList.add('on'));
    video.addEventListener('playing', () => loader.classList.remove('on'));
    video.addEventListener('canplay', () => loader.classList.remove('on'));

    /* Controls: pauza — doim ko'rinsin; ijro — 3 sek da yashirilsin */
    video.addEventListener('pause',  () => { clearTimeout(ctrlHideTimer); showControls(); });
    video.addEventListener('play',    () => { showControls(); });
    video.addEventListener('playing', () => { showControls(); });

    /* Progress */
    video.addEventListener('timeupdate', () => {
        if (!video.duration) return;
        progress.style.width = (video.currentTime / video.duration * 100) + '%';
    });

    /* Click — single tap (controls toggle), double tap seek */
    let lastTap = 0;
    video.addEventListener('click', (e) => {
        const now = Date.now();
        if (now - lastTap < 280) {
            const half = video.clientWidth / 2;
            if (e.offsetX < half) { video.currentTime -= 10; showSeek('L'); }
            else                  { video.currentTime += 10; showSeek('R'); }
            lastTap = 0;
            return;
        }
        lastTap = now;
        setTimeout(() => {
            if (Date.now() - lastTap >= 260) {
                if (!ctrlVisible) { showControls(); }
                else              { togglePlay(); }
            }
        }, 280);
    });

    /* Keyboard [P5-T2: + m (mute)] */
    document.addEventListener('keydown', (e) => {
        if (['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) return;
        showControls();
        if (e.key === ' ' || e.key === 'k') { e.preventDefault(); togglePlay(); }
        if (e.key === 'ArrowLeft')  { video.currentTime -= 10; showSeek('L'); }
        if (e.key === 'ArrowRight') { video.currentTime += 10; showSeek('R'); }
        if (e.key === 'ArrowDown')  { e.preventDefault(); navigate('next'); }
        if (e.key === 'ArrowUp')    { e.preventDefault(); navigate('prev'); }
        if (e.key === 'f')          { toggleFullscreen(); }
        if (e.key === 'm')          { video.muted = !video.muted; }
    });

    /* Progress bar seek */
    let seeking = false;
    function seekTo(clientX) {
        const rect = progressWr.getBoundingClientRect();
        const r = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
        video.currentTime = r * video.duration;
    }
    progressWr.addEventListener('mousedown', (e) => { seeking = true; seekTo(e.clientX); e.stopPropagation(); });
    document.addEventListener('mousemove',  (e) => { if (seeking) seekTo(e.clientX); }, { passive: true });
    document.addEventListener('mouseup',    ()  => { seeking = false; }, { passive: true });
    progressWr.addEventListener('touchstart', (e) => { showControls(); seekTo(e.touches[0].clientX); }, { passive: true });
}

function togglePlay() {
    if (!video) return;
    if (video.paused) { video.play();  flashPlay('play');  }
    else              { video.pause(); flashPlay('pause'); }
}

/* ─── TAP TO PLAY ───────────────────────────────────────── */
window.startPlay = function () {
    tapToPlay.classList.add('hide');
    if (!video) return;
    video.muted = false;
    const p = video.play();
    if (p && typeof p.catch === 'function') {
        p.catch(() => {
            video.muted = true;
            video.play();
        });
    }
};

function flashPlay(type) {
    flashI.className = type === 'play' ? 'fas fa-play' : 'fas fa-pause';
    flashIcon.classList.remove('pop');
    void flashIcon.offsetWidth;
    flashIcon.classList.add('pop');
}

function showSeek(side) {
    const el = document.getElementById('seek' + side);
    if (!el) return;
    el.classList.remove('pop');
    void el.offsetWidth;
    el.classList.add('pop');
}

/* ─────────────────────────────────────────────────────────
   QUALITY SWITCH
   — Bunny (HLS) da: Auto ↔ FHD sifat darajasi
   — Eski (MP4) da: 720p ↔ 1080p URL almashtirish
───────────────────────────────────────────────────────── */
window.switchQuality = function () {
    if (!video) return;
    const btn = document.getElementById('rQualBtn');

    if (hlsInst) {
        const levels = hlsInst.levels;
        if (hlsInst.currentLevel === -1) {
            const fhdIdx = levels.findIndex(l => l.height >= 1080);
            hlsInst.currentLevel = fhdIdx >= 0 ? fhdIdx : levels.length - 1;
            if (btn) btn.textContent = 'FHD';
        } else {
            hlsInst.currentLevel = -1;
            if (btn) btn.textContent = 'HD';
        }
        return;
    }

    const time = video.currentTime;
    const wasPaused = video.paused;
    curQual = curQual === '720p' ? '1080p' : '720p';
    video.src = curQual === '1080p' ? SRC_1080 : SRC_720;
    loader.classList.add('on');
    video.load();
    video.addEventListener('loadedmetadata', () => {
        video.currentTime = time;
        if (!wasPaused) video.play();
        loader.classList.remove('on');
        if (btn) btn.textContent = curQual === '1080p' ? 'FHD' : 'HD';
    }, { once: true });
};

/* ─────────────────────────────────────────────────────────
   FULLSCREEN
───────────────────────────────────────────────────────── */
function toggleFullscreen() {
    if (!document.fullscreenElement) {
        app.requestFullscreen && app.requestFullscreen();
    } else {
        document.exitFullscreen && document.exitFullscreen();
    }
}

/* ─────────────────────────────────────────────────────────
   BOTTOM SHEETS
───────────────────────────────────────────────────────── */
window.openSheet = function (id) {
    closeAllSheets();
    document.getElementById(id).classList.add('open');
    document.getElementById('sheetBackdrop').classList.add('open');
    if (video && !video.paused) video.pause();
    clearTimeout(ctrlHideTimer);
    showControls();
};
window.closeSheet = function (id) {
    document.getElementById(id).classList.remove('open');
    const anyOpen = document.querySelector('.r-sheet.open');
    if (!anyOpen) {
        document.getElementById('sheetBackdrop').classList.remove('open');
        showControls();
    }
};
window.closeAllSheets = function () {
    document.querySelectorAll('.r-sheet').forEach(s => s.classList.remove('open'));
    document.getElementById('sheetBackdrop').classList.remove('open');
    showControls();
};

/* ─────────────────────────────────────────────────────────
   LIKE
───────────────────────────────────────────────────────── */
let liked = false;
window.doLike = function () {
    if (!IS_AUTH) { window.location.href = LOGIN_URL; return; }
    liked = !liked;
    likeCircle.classList.toggle('is-liked', liked);
    likeCircle.style.transform = 'scale(1.25)';
    setTimeout(() => { likeCircle.style.transform = ''; }, 200);
    document.getElementById('likeLabel').textContent = liked ? 'Yoqdi ❤' : 'Yoqdi';
};

/* ─────────────────────────────────────────────────────────
   BOOKMARK / LIBRARY
───────────────────────────────────────────────────────── */
window.doBookmark = function () {
    if (!IS_AUTH) { window.location.href = LOGIN_URL; return; }
    const modal = document.getElementById('libraryModal');
    if (modal) { modal.classList.add('open'); if (video && !video.paused) video.pause(); }
};
window.closeLibrary = function () {
    const modal = document.getElementById('libraryModal');
    if (modal) modal.classList.remove('open');
};
document.addEventListener('click', (e) => {
    const modal = document.getElementById('libraryModal');
    if (modal && e.target === modal) closeLibrary();
});

/* ─────────────────────────────────────────────────────────
   COMMENT HELPERS (htmx uchun)
───────────────────────────────────────────────────────── */
window.prepareReply = function (name, id) {
    /* Eski funksiya bilan moslik */
};
window.resetCommentTarget = function () {};
window.toggleReviewText = function (btn) {
    const wrap      = btn.parentElement;
    const shortText = wrap.querySelector('.comment-short-text');
    const fullText  = wrap.querySelector('.comment-full-text');
    const isHidden  = fullText.classList.contains('hidden');
    shortText.classList.toggle('hidden', isHidden);
    fullText.classList.toggle('hidden', !isHidden);
    btn.innerHTML = isHidden
        ? `Qisqartirish <i class="fas fa-chevron-up ml-1"></i>`
        : `Batafsil o'qish <i class="fas fa-chevron-down ml-1"></i>`;
};

/* ─────────────────────────────────────────────────────────
   AUTO-SCROLL ACTIVE EPISODE INTO VIEW (sheet ochilganda)
───────────────────────────────────────────────────────── */
const episodeSheet = document.getElementById('episodeSheet');
if (episodeSheet) {
    episodeSheet.addEventListener('transitionend', (e) => {
        if (e.propertyName !== 'transform') return;
        if (!episodeSheet.classList.contains('open')) return;
        const activeBtn = document.querySelector('.r-ep-btn.active');
        if (activeBtn) activeBtn.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
}

})();
