/* Drama.uz — KLASSIK 16:9 pleyer UI [klassik-pleyer].
 *
 * Yadro (HLS + imzoli-URL yangilash + resume + progress + ended) —
 * static/js/player-core.js. Bu faylda faqat klassik UI: boshqaruv paneli
 * (seek+bufer, ovoz, tezlik, sifat, PiP, fullscreen), klaviatura,
 * avto-yashirinish, keyingi-qism countdown overlay.
 * Ma'lumot manbai: #classicData JSON (reelsData bilan bir xil shakl).
 */
(function () {
'use strict';

const dataEl = document.getElementById('classicData');
if (!dataEl) return;
const d = JSON.parse(dataEl.textContent);

const wrap  = document.getElementById('cpWrap');
const video = document.getElementById('cpVideo');
if (!wrap || !video) return; /* qulflangan yoki embed rejim */

const els = {};
['cpPlay','cpBigPlay','cpMute','cpVol','cpTime','cpSeek','cpPlayed','cpBuffered',
 'cpSpeedBtn','cpSpeedMenu','cpQualBtn','cpQualMenu','cpPip','cpFs','cpLoader',
 'cpNextBtn','cpNextOverlay','cpNextCount','cpNextCancel'].forEach(id => {
    els[id] = document.getElementById(id);
});

/* ── YADRO ── */
const core = window.DramaPlayerCore(video, d, { onEnded: onEnded });

/* ── Vaqt formati ── */
function fmt(s) {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const mm = String(m).padStart(2, '0'), ss = String(sec).padStart(2, '0');
    return h ? h + ':' + mm + ':' + ss : m + ':' + ss;
}

/* ── Play / pause ── */
function togglePlay() { if (video.paused) video.play(); else video.pause(); }
els.cpPlay.addEventListener('click', togglePlay);
els.cpBigPlay.addEventListener('click', togglePlay);
video.addEventListener('click', togglePlay);
video.addEventListener('dblclick', toggleFs);
video.addEventListener('play',  () => {
    wrap.classList.remove('cp-paused');
    els.cpPlay.querySelector('i').className = 'fas fa-pause';
    scheduleHide();
});
video.addEventListener('pause', () => {
    wrap.classList.add('cp-paused');
    els.cpPlay.querySelector('i').className = 'fas fa-play';
    showControls();
});
wrap.classList.add('cp-paused'); /* boshlanish: poster + katta play */

/* ── Loader ── */
video.addEventListener('waiting', () => els.cpLoader.classList.add('on'));
['playing', 'canplay'].forEach(ev =>
    video.addEventListener(ev, () => els.cpLoader.classList.remove('on')));

/* ── Seek + bufer ── */
let seeking = false;
function seekTo(clientX) {
    const rect = els.cpSeek.getBoundingClientRect();
    const r = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
    if (video.duration) video.currentTime = r * video.duration;
}
els.cpSeek.addEventListener('mousedown', (e) => { seeking = true; seekTo(e.clientX); });
document.addEventListener('mousemove', (e) => { if (seeking) seekTo(e.clientX); }, { passive: true });
document.addEventListener('mouseup', () => { seeking = false; }, { passive: true });
els.cpSeek.addEventListener('touchstart', (e) => seekTo(e.touches[0].clientX), { passive: true });
els.cpSeek.addEventListener('touchmove',  (e) => seekTo(e.touches[0].clientX), { passive: true });

video.addEventListener('timeupdate', () => {
    if (!video.duration) return;
    els.cpPlayed.style.width = (video.currentTime / video.duration * 100) + '%';
    els.cpTime.textContent = fmt(video.currentTime) + ' / ' + fmt(video.duration);
});
video.addEventListener('progress', () => {
    if (!video.duration || !video.buffered.length) return;
    els.cpBuffered.style.width =
        (video.buffered.end(video.buffered.length - 1) / video.duration * 100) + '%';
});
video.addEventListener('loadedmetadata', () => {
    els.cpTime.textContent = fmt(0) + ' / ' + fmt(video.duration);
});

/* ── Ovoz ── */
els.cpMute.addEventListener('click', () => { video.muted = !video.muted; });
els.cpVol.addEventListener('input', () => {
    video.volume = els.cpVol.value / 100;
    video.muted = els.cpVol.value === '0';
});
video.addEventListener('volumechange', () => {
    els.cpMute.querySelector('i').className =
        video.muted || video.volume === 0 ? 'fas fa-volume-mute'
        : video.volume < 0.5 ? 'fas fa-volume-down' : 'fas fa-volume-up';
    els.cpVol.value = video.muted ? 0 : Math.round(video.volume * 100);
});

/* ── Popover menyular (tezlik / sifat) ── */
function bindMenu(btn, menu) {
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeMenus(menu);
        menu.classList.toggle('open');
    });
}
function closeMenus(except) {
    [els.cpSpeedMenu, els.cpQualMenu, document.getElementById('cpSubMenu')].forEach(m => {
        if (m && m !== except) m.classList.remove('open');
    });
}
document.addEventListener('click', () => closeMenus());
bindMenu(els.cpSpeedBtn, els.cpSpeedMenu);
bindMenu(els.cpQualBtn, els.cpQualMenu);

function markActive(menu, item) {
    menu.querySelectorAll('.active').forEach(el => el.classList.remove('active'));
    item.classList.add('active');
}

/* ── Tezlik [V2E-T4 yo'lida] ── */
els.cpSpeedMenu.addEventListener('click', (e) => {
    const item = e.target.closest('[data-speed]');
    if (!item) return;
    video.playbackRate = parseFloat(item.dataset.speed);
    els.cpSpeedBtn.textContent = item.dataset.speed + 'x';
    markActive(els.cpSpeedMenu, item);
    els.cpSpeedMenu.classList.remove('open');
});

/* ── Sifat: HLS darajasi (auto/cap) yoki MP4 URL almashtirish ── */
let mp4Qual = '720';
els.cpQualMenu.addEventListener('click', (e) => {
    const item = e.target.closest('[data-qual]');
    if (!item) return;
    const q = item.dataset.qual;
    const hls = core.hls();
    if (hls) {
        if (q === 'auto') {
            hls.currentLevel = -1;
        } else {
            const target = parseInt(q, 10);
            let best = -1;
            hls.levels.forEach((l, i) => {
                if (l.height <= target && (best < 0 || l.height > hls.levels[best].height)) best = i;
            });
            hls.currentLevel = best >= 0 ? best : hls.levels.length - 1;
        }
    } else if (q !== 'auto' && q !== mp4Qual) {
        const src = q === '1080' ? d.src1080 : d.src720;
        if (src) {
            mp4Qual = q;
            const t = video.currentTime, wasPaused = video.paused;
            els.cpLoader.classList.add('on');
            video.src = src;
            video.load();
            video.addEventListener('loadedmetadata', () => {
                video.currentTime = t;
                if (!wasPaused) video.play();
                els.cpLoader.classList.remove('on');
            }, { once: true });
        }
    }
    els.cpQualBtn.textContent = q === 'auto' ? 'Avto' : q + 'p';
    markActive(els.cpQualMenu, item);
    els.cpQualMenu.classList.remove('open');
});

/* ── PiP / Fullscreen ── */
if (els.cpPip) {
    if (!document.pictureInPictureEnabled) {
        els.cpPip.style.display = 'none';
    } else {
        els.cpPip.addEventListener('click', () => {
            if (document.pictureInPictureElement) document.exitPictureInPicture();
            else video.requestPictureInPicture().catch(() => {});
        });
    }
}
function toggleFs() {
    if (!document.fullscreenElement) {
        wrap.requestFullscreen && wrap.requestFullscreen();
    } else {
        document.exitFullscreen && document.exitFullscreen();
    }
}
els.cpFs.addEventListener('click', toggleFs);
document.addEventListener('fullscreenchange', () => {
    els.cpFs.querySelector('i').className =
        document.fullscreenElement ? 'fas fa-compress' : 'fas fa-expand';
});

/* ── Boshqaruv avto-yashirinish ── */
let hideTimer = null;
function showControls() {
    wrap.classList.remove('cp-idle');
    scheduleHide();
}
function scheduleHide() {
    clearTimeout(hideTimer);
    if (!video.paused) hideTimer = setTimeout(() => wrap.classList.add('cp-idle'), 2600);
}
['mousemove', 'touchstart'].forEach(ev => wrap.addEventListener(ev, showControls, { passive: true }));
wrap.addEventListener('mouseleave', () => { if (!video.paused) wrap.classList.add('cp-idle'); });

/* ── Klaviatura ── */
document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    if (e.key === ' ' || e.key === 'k') { e.preventDefault(); togglePlay(); }
    else if (e.key === 'ArrowLeft')  { video.currentTime -= 5; }
    else if (e.key === 'ArrowRight') { video.currentTime += 5; }
    else if (e.key === 'ArrowUp')   { e.preventDefault(); video.volume = Math.min(1, video.volume + 0.1); video.muted = false; }
    else if (e.key === 'ArrowDown') { e.preventDefault(); video.volume = Math.max(0, video.volume - 0.1); }
    else if (e.key === 'f') { toggleFs(); }
    else if (e.key === 'm') { video.muted = !video.muted; }
    else return;
    showControls();
});

/* ── Keyingi qism: tugma + tugaganda countdown overlay ── */
if (els.cpNextBtn) {
    if (!core.nextEp) els.cpNextBtn.style.display = 'none';
    else els.cpNextBtn.addEventListener('click', () => {
        window.location.href = core.epUrl(core.nextEp);
    });
}
/* [V2E-T2] Countdown endi 15s OLDIN boshlanadi (yadro setupMarkers) —
   eski "tugagach 5s" interval o'rnini bosdi. Bekor -> avto-keyingi o'chadi. */
const markers = core.setupMarkers({
    skipBtn: document.getElementById('cpSkipIntro'),
    nextOverlay: els.cpNextOverlay,
    nextCountEl: els.cpNextCount,
    nextCancelBtn: els.cpNextCancel,
});

function onEnded(nextEp) {
    wrap.classList.add('cp-paused');
    showControls();
    if (els.cpNextOverlay) els.cpNextOverlay.classList.remove('open');
    if (!nextEp || markers.autoNextCancelled()) return;
    window.location.href = core.epUrl(nextEp);
}

/* ── Subtitr MENYU [V2E-T1 UX] — speed/sifat menyulari bilan bir naqsh ── */
(function () {
    const subBtn = document.getElementById('cpSubBtn');
    const subMenu = document.getElementById('cpSubMenu');
    if (!subBtn || !subMenu) return; /* subtitrsiz qism — template'da yo'q */
    bindMenu(subBtn, subMenu);
    subMenu.addEventListener('click', (e) => {
        const item = e.target.closest('[data-sub]');
        if (!item) return;
        const lang = core.setSubtitle(item.dataset.sub);
        subBtn.textContent = lang ? lang.toUpperCase() : 'CC';
        markActive(subMenu, item);
        subMenu.classList.remove('open');
    });
    video.addEventListener('loadedmetadata', () => {
        const l = core.currentSubtitle();
        subBtn.textContent = l ? l.toUpperCase() : 'CC';
        const target = subMenu.querySelector('[data-sub="' + l + '"]') ||
                       subMenu.querySelector('[data-sub=""]');
        if (target) markActive(subMenu, target);
    });
})();

})();
