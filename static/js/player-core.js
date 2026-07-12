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

    return {
        prevEp: prevEp,
        nextEp: nextEp,
        epUrl: function (num) { return BASE_URL + '?episode=' + num; },
        hls: function () { return hlsInst; },
        saveProgress: saveProgress,
        fallbackToMp4: fallbackToMp4,
    };
};
