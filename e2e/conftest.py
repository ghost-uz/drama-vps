"""E2E-only pytest sozlamalari [P11-T4 barqarorlik].

Playwright'ning standart `expect`/navigatsiya/harakat timeout'i 5s. Umumiy (shared)
CI runner'larida HTMX so'rov + navigatsiya vaqti o'zgaruvchan yuk ostida ba'zan shundan
oshadi -> `expect(...)` assertion timeout -> nightly e2e job'i "flaky" qizil bo'ladi
(hech qanday kod o'zgarmasa ham; rerun'da o'tadi).

Timeout'ni 15s ga ko'taramiz: HAQIQIY regressiya baribir yiqiladi (kutish emas, xato),
lekin runner jitter'i yutiladi. Ikkinchi himoya qatlami — CI'da `--reruns` (pytest-
rerunfailures): faqat yiqilgan e2e testni qayta yuritadi.

Fixture faqat `page`'dan foydalanadigan (ya'ni e2e) testlar uchun ishlaydi; oddiy
`pytest` (unit/coverage) e2e'ni skip qiladi -> bu fixture ham, brauzer ham ochilmaydi.
"""

import pytest
from playwright.sync_api import expect


@pytest.fixture(autouse=True)
def _e2e_generous_timeouts(page):
    """Har e2e test uchun Playwright timeout'larini 5s -> 15s ga ko'taradi.

    `page.set_default_timeout` — harakat (click/fill/wait) uchun; `expect.set_options`
    — assertion (`expect(locator).to_...`) uchun (bu ikkisi alohida timeout'lar).
    """
    page.set_default_timeout(15_000)
    page.set_default_navigation_timeout(15_000)
    expect.set_options(timeout=15_000)
