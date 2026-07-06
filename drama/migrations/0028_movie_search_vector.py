# drama/migrations/0028 — FTS: search_vector + pg_trgm + GIN indekslar [P8-T1]
#
# Postgres-maxsus qismlar (extension, GIN, backfill) vendor-guard bilan:
# sqlite (test suite)da faqat ustun qo'shiladi — qidiruv icontains fallback'da
# ishlayveradi. pg_trgm PG13+ da "trusted" — superuser shart emas (DB owner
# yetarli); TrigramExtension postgres bo'lmasa o'zi no-op.
#
# Backfill SQL update_search_vector task bilan BIR XIL ifoda (A=title/original,
# B=aktyorlar, C=tavsif; config='simple' — uz uchun stemming'siz to'g'ri yo'l).

import django.contrib.postgres.search
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations

_GIN_INDEXES = [
    # tsvector GIN — @@ (FTS) so'rovlari uchun
    (
        "drama_movie_search_vector_gin",
        "CREATE INDEX IF NOT EXISTS drama_movie_search_vector_gin "
        "ON drama_movie USING gin (search_vector);",
    ),
    # trigram GIN — xato-bardosh (similarity/%) qidiruv title bo'yicha
    (
        "drama_movie_title_trgm",
        "CREATE INDEX IF NOT EXISTS drama_movie_title_trgm "
        "ON drama_movie USING gin (title gin_trgm_ops);",
    ),
    (
        "drama_movie_orig_title_trgm",
        "CREATE INDEX IF NOT EXISTS drama_movie_orig_title_trgm "
        "ON drama_movie USING gin (original_title gin_trgm_ops);",
    ),
]

_BACKFILL_SQL = """
UPDATE drama_movie m SET search_vector =
  setweight(to_tsvector('simple',
    coalesce(m.title, '') || ' ' || coalesce(m.title_uz, '') || ' ' ||
    coalesce(m.title_en, '') || ' ' || coalesce(m.original_title, '')), 'A') ||
  setweight(to_tsvector('simple', coalesce((
    SELECT string_agg(a.name, ' ')
    FROM drama_movie_actors ma
    JOIN drama_actor a ON a.id = ma.actor_id
    WHERE ma.movie_id = m.id), '')), 'B') ||
  setweight(to_tsvector('simple',
    coalesce(m.description, '') || ' ' || coalesce(m.description_uz, '') || ' ' ||
    coalesce(m.description_en, '')), 'C');
"""


def apply_postgres_parts(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for _name, sql in _GIN_INDEXES:
        schema_editor.execute(sql)
    schema_editor.execute(_BACKFILL_SQL)


def reverse_postgres_parts(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name, _sql in _GIN_INDEXES:
        schema_editor.execute(f"DROP INDEX IF EXISTS {name};")


class Migration(migrations.Migration):
    dependencies = [
        ("drama", "0027_movie_drama_movie_country_562e26_idx_and_more"),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddField(
            model_name="movie",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(editable=False, null=True),
        ),
        migrations.RunPython(apply_postgres_parts, reverse_postgres_parts),
    ]
