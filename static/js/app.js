/* Drama.uz — Alpine komponentlari [P5-T1].
 *
 * Alpine CSP build ishlatiladi (CSP'da 'unsafe-eval' YO'Q — P10-T1):
 * x-data inline ifoda EMAS, faqat shu yerda Alpine.data() bilan
 * registratsiya qilingan komponent nomiga ishora qiladi:
 *
 *   <div x-data="dropdown">
 *     <button @click="toggle">Ochish</button>
 *     <div x-show="open" x-cloak @click.outside="close">...</div>
 *   </div>
 *
 * Bu fayl alpine-csp.min.js dan OLDIN yuklanishi shart (ikkalasi defer —
 * hujjat tartibi saqlanadi).
 */
document.addEventListener('alpine:init', () => {
    /* Umumiy ochil-yopil: dropdown, menyu, akkordeon */
    Alpine.data('dropdown', () => ({
        open: false,
        toggle() { this.open = !this.open; },
        close() { this.open = false; },
    }));

    /* Modal / bottom-sheet (body scroll qulflanadi) */
    Alpine.data('modal', () => ({
        open: false,
        show() {
            this.open = true;
            document.body.style.overflow = 'hidden';
        },
        hide() {
            this.open = false;
            document.body.style.overflow = '';
        },
    }));

    /* Mobil qidiruv paneli: ochilganda inputga fokus (x-ref="input") */
    Alpine.data('searchBar', () => ({
        open: false,
        toggle() {
            this.open = !this.open;
            if (this.open) {
                this.$nextTick(() => {
                    if (this.$refs.input) this.$refs.input.focus();
                });
            }
        },
        close() { this.open = false; },
    }));
});
