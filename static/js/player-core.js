/* Drama.uz — pleyer YADROSI (umumiy qatlam) [klassik-pleyer].
 *
 * Reels (player.js) va klassik (player-classic.js) pleyerlarning UMUMIY
 * jangovar qismi [P5-T2]: HLS init (fatal network xatoda imzoli URL'ni
 * playback API'dan yangilash [P4-T1] + MP4 fallback), resume (WatchProgress),
 * progressni saqlash (10s interval + pauza + yashirilganda sendBeacon +
 * tugaganda completed=1), qism-navigatsiya hisoblari.
 * UI (tugmalar, overlay, sheet) — har pleyerning o'z faylida.
 *
 * data (d): episodes[], currentEp, useBunny, srcHls, src720, src1080,
 * isAuth, resumePos, progressUrl, playbackApi.
 */
window.DramaPlayerCore = function (video, d, opts) {
    'use strict';
    opts = opts || {};

    const ALL_EPS = d.episodes || [];
    const idx = ALL_EPS.indexOf(d.currentEp);
    const prevEp = idx > 0 ? ALL_EPS[idx - 1] : null;
    const nextEp = idx >= 0 && idx < ALL_EPS.length - 1 ? ALL_EPS[idx + 1] : null;
    const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    const BASE_URL = window.location.pathname;

    let hlsInst = null;
    let refreshTried = false;
    let lastSavedPos = -1;

    /* Imzoli URL muddati o'tsa — playback API'dan BIR marta yangisi [P5-T2] */
    async function refreshPlaybackUrl() {
        if (!d.playbackApi || refreshTried) return null;
        refreshTried = true;
        try {
            const resp = await fetch(d.playbackApi, { credentials: 'same-origin' });
            if (!resp.ok) return null;
            const data = await resp.json();
            return data.hls_url || null;
        } catch (_) {
            return null;
        }
    }

    function fallbackToMp4() {
        if (hlsInst) { hlsInst.destroy(); hlsInst = null; }
        if (d.src720) video.src = d.src720;
    }

    function initHls() {
        if (!video || !d.srcHls) return;
        if (typeof Hls === 'undefined') {
            if (d.src720) video.src = d.src720;
            return;
        }
        if (Hls.isSupported()) {
            hlsInst = new Hls({ enableWorker: true, lowLatencyMode: false });
            hlsInst.loadSource(d.srcHls);
            hlsInst.attachMedia(video);
            hlsInst.on(Hls.Events.ERROR, function (_, data) {
                if (!data.fatal) return;
                if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                    /* Token muddati o'tgan bo'lishi mumkin — yangi imzoli URL */
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
            video.src = d.srcHls; /* Safari — nativ HLS */
        } else if (d.src720) {
            video.src = d.src720;
        }
    }

    /* RESUME — to'xtagan joydan; deyarli tugaganiga qaytarmaymiz [P5-T2] */
    if (video && (d.resumePos || 0) > 5) {
        video.addEventListener('loadedmetadata', () => {
            if (video.duration && d.resumePos < video.duration * 0.95) {
                video.currentTime = d.resumePos;
            }
        }, { once: true });
    }

    /* PROGRESSNI SAQLASH — 10s + pauza + yashirilganda + tugaganda [P5-T2] */
    function buildProgressForm(completed) {
        const form = new FormData();
        form.append('position_seconds', String(Math.floor(video.currentTime || 0)));
        form.append('duration_seconds', String(Math.floor(video.duration || 0)));
        if (completed) form.append('completed', '1');
        form.append('csrfmiddlewaretoken', CSRF);
        return form;
    }

    function saveProgress(useBeacon, completed) {
        if (!d.isAuth || !d.progressUrl || !video || !video.duration) return;
        const pos = Math.floor(video.currentTime);
        if (!completed && !useBeacon && Math.abs(pos - lastSavedPos) < 5) return;
        lastSavedPos = pos;
        const form = buildProgressForm(completed);
        if (useBeacon && navigator.sendBeacon) {
            navigator.sendBeacon(d.progressUrl, form);
        } else {
            fetch(d.progressUrl, {
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
        video.addEventListener('ended', () => {
            saveProgress(true, true); /* completed=1 — beacon, navigatsiyada yo'qolmaydi */
            if (opts.onEnded) opts.onEnded(nextEp);
        });
    }

    if (d.useBunny) initHls();

    /* ── Subtitrlar [V2E-T1] ─────────────────────────────────
       <track> ro'yxati DOM'dan; tanlov localStorage (drama:subLang).
       Cycle: off -> 1-til -> 2-til -> ... -> off. textTracks metadata
       yuklangach tayyor bo'ladi — saqlangan tanlov loadedmetadata'da ham
       qayta qo'llanadi. */
    var SUB_KEY = 'drama:subLang';

    function subTracks() {
        return video ? Array.prototype.slice.call(video.textTracks) : [];
    }

    function applySubtitle(lang) {
        subTracks().forEach(function (t) {
            t.mode = (lang && t.language === lang) ? 'showing' : 'hidden';
        });
    }

    function currentSubtitle() {
        var showing = subTracks().filter(function (t) { return t.mode === 'showing'; })[0];
        return showing ? showing.language : '';
    }

    function setSubtitle(lang) {
        /* To'g'ridan-to'g'ri tanlash (menyu/sheet) — '' = o'chiq */
        applySubtitle(lang);
        try { localStorage.setItem(SUB_KEY, lang || ''); } catch (e) { /* private mode */ }
        return lang || '';
    }

    function cycleSubtitle() {
        var langs = subTracks().map(function (t) { return t.language; });
        if (!langs.length) return '';
        var cur = currentSubtitle();
        var idx = langs.indexOf(cur);
        var next = cur === '' ? langs[0] : (idx + 1 < langs.length ? langs[idx + 1] : '');
        applySubtitle(next);
        try { localStorage.setItem(SUB_KEY, next); } catch (e) { /* private mode */ }
        return next;
    }

    function restoreSubtitle() {
        try {
            var saved = localStorage.getItem(SUB_KEY);
            if (saved) applySubtitle(saved);
        } catch (e) { /* private mode */ }
    }

    if (video) {
        restoreSubtitle();
        video.addEventListener('loadedmetadata', restoreSubtitle);
    }

    /* ── Pleyer sozlamalari persist [V2E-T4] ──────────────────
       Tezlik/sifat/ovoz localStorage'da — qurilmada eslab qolinadi.
       Sifat PREFERENSIYASI (string) yadroda saqlanadi; uni QO'LLASH
       pleyerga xos (reels auto/fhd, klassik auto/1080/720) — shuning
       uchun pleyer restore paytida o'z applyQuality'sini chaqiradi. */
    var SPEED_KEY = 'drama:speed';
    var QUAL_KEY = 'drama:quality';
    var VOL_KEY = 'drama:volume';
    var MUTED_KEY = 'drama:muted';

    function setSpeed(rate) {
        if (video) {
            video.playbackRate = rate;
            video.preservesPitch = true; /* audio pitch normal (AC) */
        }
        try { localStorage.setItem(SPEED_KEY, String(rate)); } catch (e) { /* private */ }
    }
    function currentSpeed() { return video ? video.playbackRate : 1; }
    function restoreSpeed() {
        try {
            var s = parseFloat(localStorage.getItem(SPEED_KEY));
            if (s && s > 0 && video) { video.playbackRate = s; video.preservesPitch = true; }
        } catch (e) { /* private */ }
    }

    function setQualityPref(val) {
        try { localStorage.setItem(QUAL_KEY, val); } catch (e) { /* private */ }
    }
    function qualityPref() {
        try { return localStorage.getItem(QUAL_KEY) || ''; } catch (e) { return ''; }
    }

    function saveVolume() {
        if (!video) return;
        try {
            localStorage.setItem(VOL_KEY, String(video.volume));
            localStorage.setItem(MUTED_KEY, video.muted ? '1' : '0');
        } catch (e) { /* private */ }
    }
    function restoreVolume() {
        if (!video) return;
        try {
            var v = parseFloat(localStorage.getItem(VOL_KEY));
            if (!isNaN(v) && v >= 0 && v <= 1) video.volume = v;
            if (localStorage.getItem(MUTED_KEY) === '1') video.muted = true;
        } catch (e) { /* private */ }
    }

    if (video) {
        restoreSpeed();
        video.addEventListener('loadedmetadata', restoreSpeed);
    }

    /* ── Intro-skip + avto-keyingi countdown [V2E-T2] ─────────
       Umumiy mantiq (reels + klassik): UI elementlarini pleyer beradi.
       - skip tugma faqat [introStart, introEnd) oralig'ida ko'rinadi
       - keyingi qism bo'lsa, 15s qolganda overlay + jonli sanoq
       - Bekor -> shu sahifa-sessiyasida avto-keyingi O'CHADI
       Marker'siz qismlarda hech narsa qilinmaydi (AC-3). */
    function setupMarkers(opts) {
        var autoNextOff = false;
        var iStart = d.introStart, iEnd = d.introEnd;
        var overlayOn = false;

        if (opts.skipBtn && video && iStart != null && iEnd != null) {
            opts.skipBtn.addEventListener('click', function () {
                video.currentTime = iEnd;
                opts.skipBtn.classList.remove('on');
            });
        }
        if (opts.nextCancelBtn) {
            opts.nextCancelBtn.addEventListener('click', function () {
                autoNextOff = true;
                overlayOn = false;
                if (opts.nextOverlay) opts.nextOverlay.classList.remove('open');
            });
        }
        if (video) {
            video.addEventListener('timeupdate', function () {
                var t = video.currentTime;
                if (opts.skipBtn && iStart != null && iEnd != null) {
                    opts.skipBtn.classList.toggle('on', t >= iStart && t < iEnd);
                }
                if (opts.nextOverlay && nextEp && !autoNextOff && video.duration) {
                    var left = Math.ceil(video.duration - t);
                    var show = left <= 15 && left > 0;
                    if (show && opts.nextCountEl) opts.nextCountEl.textContent = left;
                    if (show !== overlayOn) {
                        overlayOn = show;
                        opts.nextOverlay.classList.toggle('open', show);
                    }
                }
            });
        }
        return {
            autoNextCancelled: function () { return autoNextOff; },
        };
    }

    return {
        prevEp: prevEp,
        nextEp: nextEp,
        setupMarkers: setupMarkers,
        cycleSubtitle: cycleSubtitle,
        setSubtitle: setSubtitle,
        currentSubtitle: currentSubtitle,
        setSpeed: setSpeed,
        currentSpeed: currentSpeed,
        setQualityPref: setQualityPref,
        qualityPref: qualityPref,
        saveVolume: saveVolume,
        restoreVolume: restoreVolume,
        epUrl: function (num) { return BASE_URL + '?episode=' + num; },
        hls: function () { return hlsInst; },
        saveProgress: saveProgress,
        fallbackToMp4: fallbackToMp4,
    };
};
