# Click integratsiyasi (V2F-T1)

Click orqali Coin sotib olish. Coin FAQAT wallet ledger orqali qo'shiladi
(`billing.services.mark_paid`, idempotent) — Payme bilan bir xil yadro. Qo'lda
chek (`TopUpRequest`) zaxira variant sifatida qoladi.

Click Payme'dan farqli: JSON-RPC emas, **ikkita form-encoded callback**
(Prepare + Complete), imzo `md5(sign_string)`.

## Sozlash (`.env`)

```
CLICK_SERVICE_ID=<kabinetdagi Service ID>
CLICK_MERCHANT_ID=<Merchant ID>
CLICK_SECRET_KEY=<Merchant SECRET KEY — sign_string md5 uchun>
CLICK_CHECKOUT_URL=https://my.click.uz/services/pay   # standart
```

`CLICK_SECRET_KEY` bo'sh bo'lsa har ikkala callback BARCHA imzoni `-1`
(SIGN CHECK FAILED) bilan rad etadi — xavfsiz default (dev/test).

## Click kabineti (merchant.click.uz)

1. **Prepare URL**: `https://<domain>/billing/click/prepare/`
2. **Complete URL**: `https://<domain>/billing/click/complete/`
3. **Service ID / Merchant ID / SECRET KEY**: `.env` ga yoziladi.

⚠️ Bu URL'lar til-neytral (prefikssiz) — i18n_patterns ichida bo'lsa ham
default til (uz) prefikssiz ishlaydi; `/en/billing/...` ATAYLAB ishlatilmaydi.

## Imzo (`sign_string`)

- **Prepare**: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time)`
- **Complete**: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + merchant_prepare_id + amount + action + sign_time)`

Qiymatlar string sifatida, ajratgichsiz ulanadi. Solishtiruv constant-time
(`hmac.compare_digest`). `merchant_trans_id` = bizning `Order` UUID'i.

## Oqim

1. Foydalanuvchi `/billing/checkout/` da summa + **Click** tanlaydi →
   `Order` (CREATED, provider=click) → Click to'lov sahifasiga redirect
   (`transaction_param=<order_id>`).
2. **Prepare** (action=0): buyurtma tekshiriladi (mavjud, CREATED, summa mos) →
   `provider_txn_id=click_trans_id`, `provider_state=1` → `merchant_prepare_id`
   (order UUID'dan CRC32) qaytariladi.
3. **Complete** (action=1): imzo + prepare_id + summa tekshiriladi →
   Click `error<0` bo'lsa buyurtma bekor (refund agar to'langan bo'lsa); aks
   holda `services.mark_paid` (Coin ledger orqali, `provider_state=2`).

## Error kodlari (javob `error` maydoni)

| Kod | Ma'no |
|----:|-------|
| 0 | Muvaffaqiyat |
| -1 | SIGN CHECK FAILED (imzo noto'g'ri) |
| -2 | Noto'g'ri summa |
| -4 | Allaqachon to'langan |
| -5 | Buyurtma topilmadi |
| -6 | Tranzaksiya/prepare topilmadi yoki prepare_id mos emas |
| -8 | So'rovdagi xato (ichki) |
| -9 | Tranzaksiya bekor qilingan |

## Idempotentlik

- Double-callback xavfsiz: `mark_paid` `select_for_update` + holat-gvardi bilan
  bir marta kredit beradi. Complete qayta kelsa `error=0` (muvaffaqiyat)
  qaytadi, qayta kredit YO'Q.
- Prepare qayta kelsa o'sha `merchant_prepare_id` qaytadi.

## Sandbox / test

`billing/test_click.py` to'liq oqimni imzo-hisoblab simulyatsiya qiladi
(prepare→complete→refund, imzo-rad, idempotentlik). Real tarmoq shart emas.

## Xavfsizlik eslatmasi

- `md5` bu yerda kriptografik hash EMAS — Click protokoli talab qiladigan imzo
  algoritmi (bandit `S324` noqa bilan belgilangan).
- Coin kreditlash yagona nuqta `services.mark_paid` — bu modul faqat
  protokol/imzo adapteri, kredit mantig'iga tegmaydi.
