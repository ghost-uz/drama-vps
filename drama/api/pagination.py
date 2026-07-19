"""API pagination [P9-T3].

Cheksiz o'sadigan ro'yxatlar (izohlar) uchun CursorPagination:
- OFFSET yo'q — chuqur "sahifa"larda ham indeks bo'ylab range-scan (tez);
- yangi yozuv qo'shilganda sahifa siljimaydi (dublikat/tushib-qolish yo'q);
- javobda `count` YO'Q — katta jadvalda COUNT(*) so'rovi ham tejaladi.

Katalog (movies) PageNumber'da QOLADI: filter/qidiruv-relevantlik, umumiy son
va ixtiyoriy sahifaga sakrash kerak — bular cursor bilan mos emas.
"""

from rest_framework.pagination import CursorPagination


class ReviewCursorPagination(CursorPagination):
    page_size = 20
    # -created_at asosiy; -pk tiebreak — bir soniya ichida bir nechta izohda
    # ham deterministik tartib (cursor chegarasi buzilmaydi)
    ordering = ("-created_at", "-pk")
