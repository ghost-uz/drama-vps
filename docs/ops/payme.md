# Payme integratsiyasi (P7-T2)

Payme orqali Coin sotib olish. Coin faqat wallet ledger orqali qo'shiladi
(idempotent) — qo'lda chek (`TopUpRequest`) zaxira variant sifatida qoladi.

## Sozlash (`.env`)

```
PAYME_MERCHANT_ID=<kabinetdagi merchant id>
PAYME_KEY=<merchant kaliti — webhook Basic-auth paroli>
PAYME_CHECKOUT_URL=https://checkout.paycom.uz   # sandbox: checkout.test.paycom.uz
```

`PAYME_KEY` bo'sh bo'lsa webhook BARCHA chaqiruvni `-32504` (ruxsatsiz)
qaytaradi — xavfsiz default (dev/test).

## Payme kabineti

1. **Endpoint URL**: `https://<domain>/billing/payme/webhook/`
2. **Hisobvaraq (account) maydoni**: `order_id` (buyurtma UUID'i shu maydonda
   uzatiladi).
3. **Avtorizatsiya**: Payme har so'rovda HTTP Basic yuboradi (login `Paycom`,
   parol = `PAYME_KEY`).

## Oqim

1. Foydalanuvchi `/billing/checkout/` da summa kiritadi → `Order` (CREATED)
   yaratiladi → Payme checkout sahifasiga redirect.
2. Payme JSON-RPC chaqiradi: `CheckPerformTransaction` → `CreateTransaction`
   (`provider_state=1`) → `PerformTransaction` (`state=2`, Coin ledger orqali
   kreditlanadi) yoki `CancelTransaction` (`-1`/`-2`, to'langan bo'lsa refund).
3. Barcha metod idempotent — Payme takror chaqirsa ikkinchi kredit bermaydi
   (`select_for_update` + holat-gvardi + `services.mark_paid`).

## Sandbox test

Payme "Merchant test" (kassa test suite) `/billing/payme/webhook/` ga
JSON-RPC yuboradi. Lokal ekvivalenti: `billing/tests.py` (22 test — auth,
Check/Create/Perform/Cancel, idempotentlik, ledger).

## Click qo'shish (kelajak, P7-T3/keyingi)

`Order.Provider.CLICK` allaqachon mavjud; `billing/providers/click.py` +
`services.mark_paid`/`mark_canceled` (o'zgarmaydi — provider-neytral) bilan
ulanadi. Ledger turi `CoinTransaction.Type.CLICK` tayyor.
