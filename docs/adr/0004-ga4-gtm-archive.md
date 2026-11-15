# ADR 0004: GA4/GTM saytga ulanmaydi — Metrica + CF Web Analytics yetarli

- **Holat:** Taklif qilindi (Proposed — egasi tasdig'i kutilmoqda; A varianti)
- **Sana:** 2026-11-15
- **Vazifa:** R3-T1 (`road_dramauz_tasks.json`)

## Kontekst

2026-11-14 analitika auditi (kod + jonli network tekshiruvi) aniqladi:

- Saytda faqat **Yandex Metrica 101193995** (1 sahifa = 1 hit, dublikatsiz)
  va **CF Web Analytics** (2026-11-14 da qo'shilgan) ishlaydi.
- Google akkauntda **GA4 `G-KSPF9LB6Y3`** (0 ma'lumot, tegi saytda yo'q) va
  **5 ta GTM konteyner** (jumladan eski `www.drama.uz` davri) yotibdi —
  HECH BIRI saytga ulanmagan.
- Bu "o'lik" obyektlar chalkashlik manbai: "Данные не получены" bannerlari,
  "qaysi asbob nechta sanayapti" xavotiri, eski domen konteynerlari.

## Variantlar

**A — arxivlash (TAVSIYA):** GA4 property va GTM konteynerlarni arxivlash /
o'chirish. Metrica (batafsil RU/UZ bozor analitikasi, goals, webvisor
imkoniyati) + CF (cookie'siz, yengil) joriy ehtiyojni to'liq yopadi.
Afzallik: nol chalkashlik, nol qo'shimcha JS, CSP o'zgarmaydi.
Kamchilik: Google Ads remarketing/konversiya kuzatuvi kerak bo'lsa, GA4'ni
keyin qaytadan ochish kerak (bu arzon — yangi property 10 daqiqa).

**B — GA4'ni to'g'ri o'rnatish:** gtag'ni GTM'siz to'g'ridan `base.html`ga +
CSP'ga `googletagmanager.com`/`google-analytics.com`. FAQAT Google Ads
kampaniyalari rejalashtirilsa oqlanadi. Hozir reja yo'q; uchinchi analitika
qatlam = qo'shimcha JS og'irligi + yana bitta "raqamlar nega farq qiladi"
manbai.

## Qaror

**A** — GA4 property va GTM konteynerlar arxivlanadi, saytga hech narsa
qo'shilmaydi. (Egasi Google Ads boshlashga qaror qilsa, B'ga qaytish shu
ADR'ni bekor qiluvchi yangi ADR bilan rasmiylashtiriladi.)

## Oqibatlar

- Egasi (yoki agent, brauzer ulanganda) Google Analytics/Tag Manager
  kabinetlarida: GA4 property → Admin → "Move to Trash" (35 kun ichida
  qaytarib bo'ladi); har GTM konteyner → Admin → arxiv/o'chirish.
- Kod o'zgarmaydi: saytda GA4/GTM izi allaqachon yo'q.
- Hisobot odatlari `docs/ops/analytics.md`da (Metrica users + CF solishtirish).
