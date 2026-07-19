"""E2E kritik oqimlar [P11-T4] — Playwright (chromium) + Django live_server.

Ishga tushirish: `pytest -m e2e` (default'da SKIP — conftest hook). Brauzer:
`python -m playwright install chromium`. Har test `django_db(transaction=True)`:
seed ma'lumot COMMIT bo'ladi -> live_server thread'i uni ko'radi (oddiy `django_db`
tranzaksiyaga o'raladi + rollback -> alohida server thread ko'rmaydi).

Qamrov: browse, ro'yxatdan o'tish, kirish, free qism (gating), VIP gate, VIP xarid
gate'ni ochadi. CSRF/JS haqiqiy brauzerda ishlaydi — bu API testlaridan farqi.
"""

import pytest
from django.contrib.auth.models import User
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def _seed_movie_with_episodes(is_vip=False, episodes=12):
    from drama.factories import EpisodeFactory, MovieFactory

    movie = MovieFactory(title="E2E Drama", is_vip=is_vip)
    for i in range(1, episodes + 1):
        EpisodeFactory(movie=movie, episode_number=i, bunny_video_id=f"vid{i}")
    return movie


def test_browse_home_to_movie_detail(live_server, page):
    """Bosh sahifa yuklanadi -> katalog kartasiga bosish -> kino detali ochiladi."""
    from drama.factories import MovieFactory

    movie = MovieFactory(title="Topiladigan Drama")
    page.goto(live_server.url)
    assert "Drama" in page.title()
    page.locator(f'a[href="{movie.get_absolute_url()}"]').first.click()
    page.wait_for_load_state()
    assert "Topiladigan Drama" in page.title()


def test_register_creates_user_and_redirects_to_login(live_server, page):
    """Ro'yxatdan o'tish formasi -> user DB'da yaratiladi -> login sahifasiga yo'naltiriladi."""
    page.goto(f"{live_server.url}/users/register/")
    page.fill("#id_username", "e2e_newbie")
    page.fill("#id_email", "e2e_newbie@test.uz")
    page.fill("#id_password1", "Str0ngPass!2026")
    page.fill("#id_password2", "Str0ngPass!2026")
    page.click("button[type=submit]")
    page.wait_for_url("**/users/login/**")
    assert User.objects.filter(username="e2e_newbie").exists()


def test_login_authenticates(live_server, page):
    """Kirish -> bosh sahifaga (LOGIN_REDIRECT_URL) + header profil havolasini ko'rsatadi."""
    from users.factories import UserFactory

    user = UserFactory(username="e2e_login")  # paroli "pass12345"
    page.goto(f"{live_server.url}/users/login/")
    page.fill("#id_username", "e2e_login")
    page.fill("#id_password", "pass12345")
    page.click("button[type=submit]")
    # Autentifikatsiya: header profil havolasi endi /users/profile/<user>/ ga ketadi
    expect(page.get_by_label("Profilga kirish")).to_have_attribute(
        "href", f"/users/profile/{user.username}/"
    )


def test_free_episode_not_gated(live_server, page):
    """1-qism (<=10) VIP kinoda ham anonim uchun TEKIN — VIP gate ko'rinmaydi."""
    movie = _seed_movie_with_episodes(is_vip=True, episodes=12)
    page.goto(f"{live_server.url}{movie.get_absolute_url()}?episode=1")
    assert "1-qism" in page.title()
    assert page.get_by_text("VIP Bo'lim").count() == 0


def test_vip_episode_gated_for_anonymous(live_server, page):
    """11+ qism VIP kinoda anonim uchun QULF — VIP gate ko'rinadi."""
    movie = _seed_movie_with_episodes(is_vip=True, episodes=12)
    page.goto(f"{live_server.url}{movie.get_absolute_url()}?episode=11")
    expect(page.get_by_text("VIP Bo'lim")).to_be_visible()
    expect(page.get_by_text("premium obuna kerak")).to_be_visible()


def test_vip_purchase_unlocks_gate(live_server, page):
    """Uchdan-uchgacha: kirish -> 11-qism qulf -> VIP xarid (Coin) -> 11-qism ochiladi."""
    from users.factories import UserFactory
    from users.models import SubscriptionPlan

    movie = _seed_movie_with_episodes(is_vip=True, episodes=12)
    SubscriptionPlan.objects.create(name="VIP 1 oy", price_coins=100, duration_days=30)
    user = UserFactory(username="e2e_vip")
    user.profile.balance = 500  # xarid uchun Coin
    user.profile.save()

    page.goto(f"{live_server.url}/users/login/")
    page.fill("#id_username", "e2e_vip")
    page.fill("#id_password", "pass12345")
    page.click("button[type=submit]")
    expect(page.get_by_label("Profilga kirish")).to_have_attribute(
        "href", f"/users/profile/{user.username}/"
    )

    ep11 = f"{live_server.url}{movie.get_absolute_url()}?episode=11"
    page.goto(ep11)
    expect(page.get_by_text("VIP Bo'lim")).to_be_visible()  # xariddan OLDIN qulf

    page.goto(f"{live_server.url}/users/subscription/")
    # "networkidle" ISHLATMA — Yandex-metrika doim ping qiladi, hech qachon idle bo'lmaydi.
    # Buy tugmasi POST -> redirect; navigatsiya "load"gacha kutiladi (xarid commit bo'ladi).
    with page.expect_navigation():
        page.locator('form[action="/users/buy-vip/"] button[type=submit]').first.click()

    page.goto(ep11)
    assert page.get_by_text("VIP Bo'lim").count() == 0  # xariddan KEYIN ochiq


def test_comment_reply_flow(live_server, page):
    """[V2B-T1] Oddiy user izohga javob yozadi (ilgari superuser-only edi):
    Fikrlar sheet -> 'Javob berish' -> indikator -> yuborish -> javob thread
    konteynerida (#replies-<root>) badge bilan ko'rinadi; DB'da parent=root."""
    from drama.factories import EpisodeFactory, MovieFactory
    from drama.models import Review
    from users.factories import UserFactory

    movie = MovieFactory(title="Reply Drama")
    EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vid1")
    author = UserFactory(username="e2e_author")
    root = Review.objects.create(user=author, movie=movie, text="Zo'r kino ekan!")
    replier = UserFactory(username="e2e_replier")

    page.goto(f"{live_server.url}/users/login/")
    page.fill("#id_username", "e2e_replier")
    page.fill("#id_password", "pass12345")
    page.click("button[type=submit]")
    expect(page.get_by_label("Profilga kirish")).to_have_attribute(
        "href", f"/users/profile/{replier.username}/"
    )

    page.goto(f"{live_server.url}{movie.get_absolute_url()}")
    page.locator("#tapToPlay").click()  # play-overlay butun ekranni qoplaydi — yopamiz
    page.locator('.r-act-item[title="Fikrlar"]').click()  # izohlar sheet'ini ochish
    page.get_by_role("button", name="Javob berish").click()
    expect(page.locator("#replyIndicator")).to_be_visible()
    expect(page.locator("#replyIndicatorName")).to_contain_text("e2e_author")

    page.fill('#rCommentForm textarea[name="text"]', "Roziman!")
    page.click("#rCommentForm button[type=submit]")

    # HTMX javobni thread konteyneriga beforeend qiladi; indikator yopiladi
    expect(page.locator(f"#replies-{root.id}")).to_contain_text("Roziman!")
    expect(page.locator(f"#replies-{root.id}")).to_contain_text("javob berdi")
    expect(page.locator("#replyIndicator")).to_be_hidden()
    assert Review.objects.filter(text="Roziman!", parent=root, user=replier).exists()


def test_comment_write_then_reply_flow(live_server, page):
    """[comment-fix] Foydalanuvchi YANGI yozgan izohiga darhol javob beradi.

    Prod'dagi bug stsenariysi: eski (stale) player.js'da prepareReply stub edi;
    endi comments.js alohida fayl + hash'langan statik nom bilan keladi."""
    from drama.factories import EpisodeFactory, MovieFactory
    from drama.models import Review
    from users.factories import UserFactory

    movie = MovieFactory(title="Fresh Reply Drama")
    EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vidf")
    UserFactory(username="e2e_fresh")

    page.goto(f"{live_server.url}/users/login/")
    page.fill("#id_username", "e2e_fresh")
    page.fill("#id_password", "pass12345")
    page.click("button[type=submit]")
    expect(page.get_by_label("Profilga kirish")).to_have_attribute(
        "href", "/users/profile/e2e_fresh/"
    )

    page.goto(f"{live_server.url}{movie.get_absolute_url()}")
    page.locator("#tapToPlay").click()
    page.locator('.r-act-item[title="Fikrlar"]').click()

    page.fill('#rCommentForm textarea[name="text"]', "Yangi fikrim!")
    page.click("#rCommentForm button[type=submit]")
    expect(page.locator("#rCommentList")).to_contain_text("Yangi fikrim!")

    # Endi AYNAN shu yangi izohga javob (DOM'ga HTMX qo'shgan karta orqali)
    page.get_by_role("button", name="Javob berish").first.click()
    expect(page.locator("#replyIndicator")).to_be_visible()
    page.fill('#rCommentForm textarea[name="text"]', "O'zimga javob")
    page.click("#rCommentForm button[type=submit]")

    root = Review.objects.get(text="Yangi fikrim!")
    expect(page.locator(f"#replies-{root.id}")).to_contain_text("O'zimga javob")
    assert Review.objects.filter(text="O'zimga javob", parent=root).exists()


def test_classic_page_comment_and_like_flow(live_server, page):
    """[comment-fix + V2B-T2] Klassik (16:9) sahifada izoh yozish + like toggle."""
    from drama.factories import EpisodeFactory, MovieFactory
    from drama.models import Category, Review
    from users.factories import UserFactory

    cat = Category.objects.create(
        name="KinoE2E", slug="kino-e2e", player_type=Category.PlayerType.CLASSIC
    )
    movie = MovieFactory(title="Classic Comment Drama", category=cat)
    EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vidc")
    UserFactory(username="e2e_classic")

    page.goto(f"{live_server.url}/users/login/")
    page.fill("#id_username", "e2e_classic")
    page.fill("#id_password", "pass12345")
    page.click("button[type=submit]")
    expect(page.get_by_label("Profilga kirish")).to_have_attribute(
        "href", "/users/profile/e2e_classic/"
    )

    page.goto(f"{live_server.url}{movie.get_absolute_url()}")
    # Klassik sahifada forma to'g'ridan-to'g'ri sahifada (sheet YO'Q)
    page.fill('#rCommentForm textarea[name="text"]', "Klassikdan salom")
    page.click("#rCommentForm button[type=submit]")
    expect(page.locator("#rCommentList")).to_contain_text("Klassikdan salom")

    # Like toggle [V2B-T2]: HTMX fragment o'zini yangilaydi (0 -> 1)
    review = Review.objects.get(text="Klassikdan salom")
    like_form = page.locator(f'form[action="/review/{review.id}/like/"]')
    like_form.locator("button").click()
    expect(like_form.locator("span")).to_have_text("1")
    review.refresh_from_db()
    assert review.like_count == 1


def test_spoiler_comment_and_episode_toggle_flow(live_server, page):
    """[V2B-T3] Spoyler izoh <details> yopiq keladi -> bosilganda ochiladi;
    'Hammasi' toggle ro'yxatni HTMX bilan qayta yuklaydi."""
    from drama.factories import EpisodeFactory, MovieFactory
    from users.factories import UserFactory

    movie = MovieFactory(title="Spoiler Drama")
    EpisodeFactory(movie=movie, episode_number=1, bunny_video_id="vs1")
    EpisodeFactory(movie=movie, episode_number=2, bunny_video_id="vs2")
    UserFactory(username="e2e_spoiler")

    page.goto(f"{live_server.url}/users/login/")
    page.fill("#id_username", "e2e_spoiler")
    page.fill("#id_password", "pass12345")
    page.click("button[type=submit]")
    expect(page.get_by_label("Profilga kirish")).to_have_attribute(
        "href", "/users/profile/e2e_spoiler/"
    )

    page.goto(f"{live_server.url}{movie.get_absolute_url()}")
    page.locator("#tapToPlay").click()
    page.locator('.r-act-item[title="Fikrlar"]').click()

    page.check('input[name="is_spoiler"]')  # form= atributi orqali bog'langan checkbox
    page.fill('#rCommentForm textarea[name="text"]', "Katta sir: oxirida hammasi tiriladi")
    page.click("#rCommentForm button[type=submit]")

    spoiler_chip = page.get_by_text("Spoyler — ochish uchun bosing").first
    expect(spoiler_chip).to_be_visible()
    expect(page.get_by_text("Katta sir: oxirida hammasi tiriladi")).to_be_hidden()

    spoiler_chip.click()  # <details> ochiladi — JS talab qilinmaydi
    expect(page.get_by_text("Katta sir: oxirida hammasi tiriladi")).to_be_visible()

    page.get_by_role("button", name="Hammasi").click()  # HTMX toggle
    expect(page.locator("#rCommentList")).to_contain_text("Spoyler — ochish uchun bosing")
