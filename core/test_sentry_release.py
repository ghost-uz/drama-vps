"""Sentry release zanjiri qo'riqchilari [R1-T1].

Release tegi uch bo'g'inli zanjirdan o'tadi va bittasi uzilsa nosozlik JIM
keladi (Sentry event'lari shunchaki release'siz tushadi):

    deploy.yml (build-arg GIT_SHA=<image tegi>) -> Dockerfile (ARG+ENV GIT_SHA)
        -> config/settings/prod.py (release = SENTRY_RELEASE || GIT_SHA || None)

prod.py'ni testda IMPORT qilib bo'lmaydi (GCS kalit faylini talab qiladi),
shu bois zanjir matn-qo'riqchilar bilan qotiriladi — test_domain_migration va
test_offsite_backup'dagi odat.
"""

from pathlib import Path

from django.conf import settings as dj_settings

BASE_DIR = Path(dj_settings.BASE_DIR)


def test_dockerfile_bakes_git_sha():
    text = (BASE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG GIT_SHA" in text, "Dockerfile'da ARG GIT_SHA yo'q — release zanjiri uzilgan"
    assert "ENV GIT_SHA" in text, (
        "ARG faqat build vaqtida yashaydi — ENV GIT_SHA bo'lmasa prod.py uni ko'rmaydi"
    )
    # ENV COPY'dan KEYIN turishi kerak: teg har deploy'da o'zgaradi, oldin tursa
    # har buildda butun COPY qatlami keshi bekor bo'lardi.
    assert text.index("COPY . .") < text.index("ARG GIT_SHA")


def test_deploy_workflow_passes_image_tag_as_build_arg():
    text = (BASE_DIR / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "GIT_SHA=${{ steps.meta.outputs.tag }}" in text, (
        "deploy.yml build-arg'ida image tegi GIT_SHA sifatida uzatilishi shart — "
        "aks holda Sentry release bo'sh qoladi [R1-T1]"
    )


def test_prod_settings_release_chain():
    text = (BASE_DIR / "config" / "settings" / "prod.py").read_text(encoding="utf-8")
    # Override (SENTRY_RELEASE) birinchi, avtomatik GIT_SHA keyin.
    assert 'config("SENTRY_RELEASE", default="")' in text
    assert 'config("GIT_SHA", default="")' in text
    assert text.index('config("SENTRY_RELEASE"') < text.index('config("GIT_SHA"')
    # Acceptance [R1-T1]: environment default production.
    assert 'config("SENTRY_ENVIRONMENT", default="production")' in text
