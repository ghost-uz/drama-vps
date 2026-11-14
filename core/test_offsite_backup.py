"""Off-site DB backup testlari [R0-T4] — core/offsite_backup.py + task + qo'riqchilar.

Qo'riqchi testlar falsafasi (bu repoda odat): konfiguratsiya ham kod — beat
jadvali vaqti, compose mount'i va backup.sh qalqonlari regressiyadan test bilan
himoyalanadi, chunki ularning buzilishi JIM keladi (backup "bor-u", ishlamaydi).
"""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from celery.exceptions import Retry
from django.conf import settings as dj_settings
from django.core.management import call_command
from django.core.management.base import CommandError

from core import offsite_backup
from core import tasks as core_tasks
from core.offsite_backup import SyncResult, sync_db_backups

BASE_DIR = Path(dj_settings.BASE_DIR)


# --- soxta GCS mijozi (tarmoqsiz) ---


class _FakeBlob:
    def __init__(self, name, uploads, fail_names):
        self.name = name
        self._uploads = uploads
        self._fail_names = fail_names

    def upload_from_filename(self, path, if_generation_match=None):
        if self.name in self._fail_names:
            from google.api_core.exceptions import PreconditionFailed

            raise PreconditionFailed(f"allaqachon mavjud: {self.name}")
        self._uploads.append((self.name, path, if_generation_match))


class _FakeBucket:
    def __init__(self, client):
        self._client = client

    def blob(self, name):
        return _FakeBlob(name, self._client.uploads, self._client.fail_names)


class _FakeClient:
    def __init__(self, existing=(), fail_names=()):
        self._existing = set(existing)
        self.fail_names = set(fail_names)
        self.uploads = []

    def list_blobs(self, bucket_name, prefix=""):
        return [SimpleNamespace(name=n) for n in sorted(self._existing) if n.startswith(prefix)]

    def bucket(self, name):
        return _FakeBucket(self)


def _use_fake(monkeypatch, fake):
    monkeypatch.setattr(offsite_backup, "_client", lambda: fake)


# --- sync_db_backups ---


def test_sync_off_when_bucket_unset(settings, monkeypatch):
    settings.GCS_BACKUP_BUCKET = ""

    def _boom():
        raise AssertionError("bucket bo'sh bo'lsa GCS mijozi umuman yaratilmasligi kerak")

    monkeypatch.setattr(offsite_backup, "_client", _boom)
    assert sync_db_backups() == SyncResult([], [], 0, 0)


def test_sync_uploads_only_missing(settings, tmp_path, monkeypatch):
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    settings.DB_BACKUP_DIR = str(tmp_path)
    (tmp_path / "drama-20260101-030000.dump").write_bytes(b"eski")
    (tmp_path / "drama-20260102-030000.dump").write_bytes(b"yangi")
    (tmp_path / "notes.txt").write_bytes(b"dump emas, e'tiborsiz qolsin")

    fake = _FakeClient(existing={"db/drama-20260101-030000.dump"})
    _use_fake(monkeypatch, fake)

    result = sync_db_backups()
    assert result.uploaded == ["db/drama-20260102-030000.dump"]
    assert result.already == 1
    assert result.local_total == 2  # notes.txt sanalmaydi
    # if_generation_match=0 — "obyekt hali yo'q" oldsharti (ustma-ust yozishdan qalqon)
    assert fake.uploads == [
        (
            "db/drama-20260102-030000.dump",
            str(tmp_path / "drama-20260102-030000.dump"),
            0,
        )
    ]


def test_sync_skips_empty_dump(settings, tmp_path, monkeypatch):
    """0 baytli dump yuklanmaydi — u backup.sh qalqoni buzilganining belgisi."""
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    settings.DB_BACKUP_DIR = str(tmp_path)
    (tmp_path / "drama-20260101-030000.dump").write_bytes(b"")

    fake = _FakeClient()
    _use_fake(monkeypatch, fake)

    result = sync_db_backups()
    assert result.skipped_empty == ["drama-20260101-030000.dump"]
    assert result.uploaded == [] and fake.uploads == []


def test_sync_precondition_race_counts_as_already(settings, tmp_path, monkeypatch):
    """Parallel o'tish faylni oldinroq yuklagan bo'lsa (412) — xato emas, skip."""
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    settings.DB_BACKUP_DIR = str(tmp_path)
    (tmp_path / "drama-20260101-030000.dump").write_bytes(b"x")

    fake = _FakeClient(fail_names={"db/drama-20260101-030000.dump"})
    _use_fake(monkeypatch, fake)

    result = sync_db_backups()
    assert result.uploaded == [] and result.already == 1


# --- celery task xulqi ---


def _capture_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(core_tasks.notify_telegram_task, "delay", lambda text: sent.append(text))
    return sent


def test_offsite_task_off_without_bucket(settings):
    settings.GCS_BACKUP_BUCKET = ""
    assert core_tasks.offsite_db_backup_task.apply().result == "off"


def test_offsite_task_reports_and_alerts_on_empty_dump(settings, monkeypatch):
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    sent = _capture_alerts(monkeypatch)
    monkeypatch.setattr(
        "core.offsite_backup.sync_db_backups",
        lambda: SyncResult(["db/a.dump"], ["b.dump"], 2, 4),
    )
    assert core_tasks.offsite_db_backup_task.apply().result == "uploaded=1 already=2"
    assert len(sent) == 1 and "0 baytli" in sent[0]


def test_offsite_task_alerts_when_no_dumps(settings, monkeypatch):
    """Dump umuman yo'q = sidecar o'lik — bu JIM qolmasligi kerak (R0 saboqlari)."""
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    sent = _capture_alerts(monkeypatch)
    monkeypatch.setattr("core.offsite_backup.sync_db_backups", lambda: SyncResult([], [], 0, 0))
    assert core_tasks.offsite_db_backup_task.apply().result == "no-dumps"
    assert len(sent) == 1 and "sidecar" in sent[0]


def test_offsite_task_retries_quietly_before_final(settings, monkeypatch):
    """Birinchi xatolar retry bo'ladi — har o'tkinchi uzilishda alert shovqini yo'q."""
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    sent = _capture_alerts(monkeypatch)

    def _boom():
        raise RuntimeError("gcs down")

    monkeypatch.setattr("core.offsite_backup.sync_db_backups", _boom)
    task = core_tasks.offsite_db_backup_task
    task.push_request(retries=0)
    try:
        with pytest.raises((Retry, RuntimeError)):
            task()
    finally:
        task.pop_request()
    assert sent == []


def test_offsite_task_alerts_after_final_retry(settings, monkeypatch):
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    sent = _capture_alerts(monkeypatch)

    def _boom():
        raise RuntimeError("gcs down")

    monkeypatch.setattr("core.offsite_backup.sync_db_backups", _boom)
    task = core_tasks.offsite_db_backup_task
    task.push_request(retries=task.max_retries)
    try:
        with pytest.raises(RuntimeError):
            task()
    finally:
        task.pop_request()
    assert len(sent) == 1 and "OFFSITE BACKUP" in sent[0]


# --- management buyrug'i ---


def test_command_requires_bucket(settings):
    settings.GCS_BACKUP_BUCKET = ""
    with pytest.raises(CommandError):
        call_command("sync_db_backups")


def test_command_reports_sync_summary(settings, monkeypatch):
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    monkeypatch.setattr(
        "core.management.commands.sync_db_backups.sync_db_backups",
        lambda: SyncResult(["db/drama-20260102-030000.dump"], [], 1, 2),
    )
    out = StringIO()
    call_command("sync_db_backups", stdout=out)
    text = out.getvalue()
    assert "gs://test-bucket/db/drama-20260102-030000.dump" in text
    assert "1 ta yuklandi" in text and "1 ta allaqachon GCS'da" in text


def test_command_create_bucket_passes_options(settings, monkeypatch):
    settings.GCS_BACKUP_BUCKET = "test-bucket"
    calls = []
    monkeypatch.setattr(
        "core.management.commands.sync_db_backups.ensure_backup_bucket",
        lambda **kw: calls.append(kw) or "gs://test-bucket YARATILDI",
    )
    monkeypatch.setattr(
        "core.management.commands.sync_db_backups.sync_db_backups",
        lambda: SyncResult([], [], 0, 0),
    )
    out = StringIO()
    call_command("sync_db_backups", "--create-bucket", "--retention-days", "45", stdout=out)
    assert calls == [{"retention_days": 45, "location": None}]
    assert "YARATILDI" in out.getvalue()


# --- qo'riqchilar: jadval vaqti, compose mount, backup.sh qalqonlari ---


def test_beat_schedule_runs_after_sidecar_dump():
    """⚠️ Vaqt mintaqasi tuzog'i: sidecar crond UTC'da (dump 03:00 UTC), beat esa
    Asia/Tashkent (UTC+5) da -> 08:30 Tashkent = 03:30 UTC, dumpdan 30 daqiqa
    KEYIN. hour=3 ga "tuzatilsa" sinxron dumpdan OLDIN yurib, har kuni kechagi
    holatni yuklab yurgan bo'lardi."""
    from config.celery import app

    entry = app.conf.beat_schedule["offsite-db-backup"]
    assert entry["task"] == "core.tasks.offsite_db_backup_task"
    assert entry["schedule"].hour == {8}
    assert entry["schedule"].minute == {30}


def test_compose_prod_mounts_dbbackups_into_celery_worker():
    """Mount yo'qolsa sinxron "no-dumps" alert bilan shovqin qiladi, lekin backup
    oqmay qoladi — regressiyani deploy'dan oldin shu test ushlasin."""
    text = (BASE_DIR / "docker-compose.prod.yml").read_text(encoding="utf-8")
    mount = "dbbackups:/backups:ro"
    assert mount in text, "celery-worker'da dbbackups read-only mount bo'lishi shart [R0-T4]"
    worker_block_start = text.index("celery-worker:")
    next_service_start = text.index("celery-beat:")
    assert worker_block_start < text.index(mount) < next_service_start, (
        "dbbackups mount aynan celery-worker servisida turishi kerak "
        "(offsite sinxron worker'da ishlaydi)"
    )


def test_backup_sh_keeps_its_guards():
    text = (BASE_DIR / "scripts" / "backup.sh").read_text(encoding="utf-8")
    # `set -e` bo'sh-fayl qalqonini chetlab o'tmasligi uchun pg_dump xatosi
    # `if !` bilan ushlanadi (aks holda 0 baytli "dump" ro'yxatda qolardi).
    assert "if ! pg_dump" in text
    # O'lik gsutil yo'li qaytmasin: alpine'da gsutil yo'q, yuklash celery'da.
    # Izoh satrlari hisobga olinmaydi — ularda tarixiy eslatma turishi mumkin.
    code_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert "gsutil" not in "\n".join(code_lines)
