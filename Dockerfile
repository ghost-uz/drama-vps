# syntax=docker/dockerfile:1
# ==============================================================================
# Drama.uz — multi-stage image (Python 3.12-slim).
#   builder : bog'liqliklarni izolyatsiyalangan venv'ga o'rnatadi
#   runtime : yengil, non-root, faqat venv + kod
#
# psycopg2-binary va Pillow binary wheel'lar libpq/libjpeg/zlib'ni o'z ichiga
# oladi (bundled) -> build-essential/libpq-dev KERAK EMAS, image kichik qoladi.
# ==============================================================================

# --- 1-BOSQICH: builder -------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Izolyatsiyalangan venv — runtime bosqichiga butunligicha ko'chiriladi
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements/ requirements/
COPY requirements.txt .
RUN pip install -r requirements/prod.txt

# --- 2-BOSQICH: runtime -------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# curl — Docker/nginx healthcheck uchun
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root foydalanuvchi (xavfsizlik — root bo'lib ishlamaslik)
RUN addgroup --system app && adduser --system --ingroup app app

# Builder'dan tayyor venv'ni ko'chirib olamiz (build-tools'siz)
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . .

# entrypoint executable + static/media papkalar + butun /app egaligini app'ga
RUN chmod +x /app/docker/entrypoint.sh \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app

USER app
EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
