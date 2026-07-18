/* Drama.uz — izoh (comment) yordamchilari [V2B-T1 -> alohida faylga ajratildi].
 *
 * Ilgari player.js (reels) ichida edi -> klassik sahifa va movie_reviews
 * sahifasida prepareReply/toggleReviewText MAVJUD EMAS edi (tugmalar o'lik).
 * Umumiy IDlar: #rCommentForm, #replyIndicator(+Name), ro'yxat #rCommentList.
 * afterRequest reset ham shu yerda — inline <script> emas (CSP) [P10-T1].
 */
(function () {
'use strict';

window.prepareReply = function (name, id) {
    /* [V2B-T1] Javob rejimi: parent input to'ldiriladi, HTMX target shu
       threadning reply-konteyneriga buriladi (server chuqurlik-1'ni kafolatlaydi) */
    const form = document.getElementById('rCommentForm');
    if (!form) return;
    form.querySelector('input[name="parent"]').value = id;
    form.setAttribute('hx-target', '#replies-' + id);
    form.setAttribute('hx-swap', 'beforeend');
    const ind = document.getElementById('replyIndicator');
    if (ind) {
        const nameEl = document.getElementById('replyIndicatorName');
        if (nameEl) nameEl.textContent = name + ' ga javob yozilmoqda';
        ind.style.display = 'flex';
    }
    const text = form.querySelector('textarea[name="text"]');
    if (text) text.focus();
};

window.cancelReply = function () {
    /* Javob rejimidan chiqish — forma default (root-izoh) holatiga qaytadi */
    const form = document.getElementById('rCommentForm');
    if (!form) return;
    form.querySelector('input[name="parent"]').value = '';
    form.setAttribute('hx-target', '#rCommentList');
    form.setAttribute('hx-swap', 'afterbegin');
    const ind = document.getElementById('replyIndicator');
    if (ind) ind.style.display = 'none';
};
window.resetCommentTarget = window.cancelReply;

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

/* Yuborilgach: forma reset + javob-rejimdan chiqish (defer -> DOM tayyor) */
const form = document.getElementById('rCommentForm');
if (form) {
    form.addEventListener('htmx:afterRequest', function (e) {
        if (e.target === form) { form.reset(); window.cancelReply(); }
    });
}
})();
