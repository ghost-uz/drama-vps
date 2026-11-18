// player-core.js audio-trek mantig'i [audio-track] — bog'liqliksiz Node testi.
//
//   node --test jstests/player_core_audio.test.mjs   (pytest: drama/test_player_audio_js.py)
//
// HAQIQIY static/js/player-core.js vm kontekstida ishga tushiriladi; hls.js
// o'rniga uning audio API'sini (audioTracks, audioTrack, hodisalar) takrorlovchi
// soxta Hls. Brauzer/codec kerak emas — mantiq deterministik sinaladi.
//
// Regressiya manbai (2026-11-18, "Millerning qizi"): teglanmagan faylda Bunny
// ikkala trekka LANGUAGE="en" qo'ydi -> ikkala band "Inglizcha", ikkalasi bir
// vaqtda "faol", tanlov qayta-parse'da (token yangilanishi) 1-trekka qaytardi.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const SRC = readFileSync(new URL('../static/js/player-core.js', import.meta.url), 'utf8');
const EVENTS = {
    ERROR: 'hlsError',
    AUDIO_TRACKS_UPDATED: 'hlsAudioTracksUpdated',
    AUDIO_TRACK_SWITCHED: 'hlsAudioTrackSwitched',
};
// vm-realm massivlari boshqa prototipga ega — solishtirishdan oldin oddiy JSON
const plain = (x) => JSON.parse(JSON.stringify(x));

function makeEnv({ uiLang = 'uz', saved = null } = {}) {
    const store = new Map(saved ? [['drama:audioLang', saved]] : []);
    const handlers = {};
    let inst = null;

    class FakeHls {
        static isSupported() { return true; }
        constructor() { this.audioTracks = []; this._track = 0; inst = this; }
        loadSource() {}
        attachMedia() {}
        startLoad() {}
        destroy() {}
        on(ev, cb) { (handlers[ev] = handlers[ev] || []).push(cb); }
        get audioTrack() { return this._track; }
        set audioTrack(v) { this._track = v; fire(EVENTS.AUDIO_TRACK_SWITCHED); }
    }
    FakeHls.Events = EVENTS;
    FakeHls.ErrorTypes = { NETWORK_ERROR: 'networkError' };

    function fire(ev) { (handlers[ev] || []).forEach((cb) => cb()); }

    const win = { location: { pathname: '/millerning-qizi/' }, Hls: FakeHls };
    const ctx = vm.createContext({
        window: win,
        document: {
            querySelector: () => null,
            addEventListener() {},
            documentElement: { lang: uiLang },
        },
        localStorage: {
            getItem: (k) => (store.has(k) ? store.get(k) : null),
            setItem: (k, v) => store.set(k, String(v)),
        },
        navigator: {},
        setInterval: () => 0,
        fetch: () => Promise.reject(new Error('tarmoq yo\'q')),
        FormData: class {},
        console,
        Hls: FakeHls,
    });
    vm.runInContext(SRC, ctx);

    const video = { addEventListener() {}, textTracks: [], playbackRate: 1, volume: 1, muted: false };
    const core = win.DramaPlayerCore(video, { useBunny: true, srcHls: 'x.m3u8', episodes: [] }, {});
    let last = null;
    core.onAudioTracks((list, key) => { last = { list: plain(list), key }; });

    return {
        core,
        store,
        hls: () => inst,
        last: () => last,
        // Manifest parse'i: hls.js ro'yxatni to'ldiradi, DEFAULT=YES trekda turadi
        load(tracks, defaultIdx = 0) {
            inst.audioTracks = tracks;
            inst._track = defaultIdx;
            fire(EVENTS.AUDIO_TRACKS_UPDATED);
        },
        // Imzoli URL yangilangach loadSource: hls.js standart trekka QAYTADI
        reparse(defaultIdx = 0) {
            inst._track = defaultIdx;
            fire(EVENTS.AUDIO_TRACKS_UPDATED);
        },
    };
}

const UNTAGGED = [{ lang: 'en', name: 'Audio' }, { lang: 'en', name: 'Audio 1' }];

test('takroriy til: neytral "N-ovoz" yorliqlari va yagona faol band', () => {
    const env = makeEnv();
    env.load(UNTAGGED);
    const { list, key } = env.last();
    assert.deepEqual(list.map((t) => t.label), ['1-ovoz', '2-ovoz']);
    assert.equal(new Set(list.map((t) => t.key)).size, 2, 'keylar noyob bo\'lishi shart');
    assert.equal(list.filter((t) => t.key === key).length, 1, 'faqat BITTA band faol');
});

test('takroriy til: 2-ovoz tanlovi qayta-parse (token yangilanishi)dan keyin saqlanadi', () => {
    const env = makeEnv();
    env.load(UNTAGGED);
    env.core.setAudioTrack(1);
    assert.equal(env.hls().audioTrack, 1);
    env.reparse(0);
    assert.equal(env.hls().audioTrack, 1, 'tanlov 1-trekka qaytib ketmasligi kerak');
    const { list, key } = env.last();
    assert.equal(list.find((t) => t.key === key).id, 1);
});

test('takroriy tildagi tanlov qurilma afzalligiga yozilmaydi', () => {
    const env = makeEnv({ saved: 'uz' });
    env.load(UNTAGGED);
    env.core.setAudioTrack(1);
    assert.equal(env.store.get('drama:audioLang'), 'uz');
});

test('saqlangan til takroriy bo\'lsa avto-tanlanmaydi — Bunny DEFAULT qoladi', () => {
    const env = makeEnv({ saved: 'en', uiLang: 'en' });
    env.load(UNTAGGED, 0);
    assert.equal(env.hls().audioTrack, 0);
});

test('aniq tillar: eski xulq — UI tili avto-tanlanadi, tanlov saqlanadi', () => {
    const env = makeEnv({ uiLang: 'uz' });
    env.load([{ lang: 'en', name: 'English' }, { lang: 'uz', name: 'Uzbek' }], 0);
    assert.equal(env.hls().audioTrack, 1, 'o\'zbekcha interfeysda uz trek tanlanadi');
    const { list, key } = env.last();
    assert.deepEqual(list.map((t) => t.label), ['Inglizcha', 'O\'zbekcha']);
    assert.deepEqual(list.map((t) => t.key), ['en', 'uz']);
    assert.equal(key, 'uz');
    env.core.setAudioTrack(0);
    assert.equal(env.store.get('drama:audioLang'), 'en');
});

test('3 harfli (ISO 639-2) va "und" kodlari', () => {
    const env = makeEnv({ uiLang: 'ru' });
    env.load([
        { lang: 'uzb', name: 'Audio' },
        { lang: 'eng', name: 'Audio 1' },
        { lang: 'und', name: 'Audio 2' },
    ]);
    const { list } = env.last();
    assert.deepEqual(list.map((t) => t.label), ['O\'zbekcha', 'Inglizcha', '3-ovoz']);
    assert.deepEqual(list.map((t) => t.key), ['uz', 'en', '#3']);
});

test('prototip xossasi nomli til kodi yorliqni buzmaydi', () => {
    // eski kod: AUDIO_LABELS['constructor'] -> Object funksiyasi yorliq bo'lardi
    const env = makeEnv();
    env.load([{ lang: 'constructor', name: '' }, { lang: 'uz', name: '' }]);
    const { list } = env.last();
    assert.deepEqual(list.map((t) => t.label), ['CONSTRUCTOR', 'O\'zbekcha']);
});
