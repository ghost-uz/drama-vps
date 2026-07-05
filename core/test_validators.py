"""core.validators testlari — fayl yuklash xavfsizligi [P10-T3]."""

import io
import re
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from core.validators import ImageFileValidator, RandomFileName, VideoFileValidator


def _image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size).save(buf, format=fmt)
    return buf.getvalue()


def _upload(name: str, data: bytes) -> SimpleUploadedFile:
    # content_type ataylab noto'g'ri — validator faqat KONTENTGA ishonishi kerak
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


MP4_HEADER = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 100


# --- ImageFileValidator ---


def test_valid_jpeg_passes():
    ImageFileValidator()(_upload("chek.jpg", _image_bytes("JPEG")))


def test_valid_png_passes():
    ImageFileValidator()(_upload("chek.png", _image_bytes("PNG")))


def test_text_masquerading_as_jpg_rejected():
    with pytest.raises(ValidationError) as ei:
        ImageFileValidator()(_upload("evil.jpg", b"<html><script>alert(1)</script>"))
    assert ei.value.code == "image_invalid"


def test_png_content_with_jpg_extension_rejected():
    """Soxta kengaytma: tarkib PNG, nomi .jpg — rad etiladi."""
    with pytest.raises(ValidationError) as ei:
        ImageFileValidator()(_upload("soxta.jpg", _image_bytes("PNG")))
    assert ei.value.code == "image_mismatch"


def test_disallowed_extension_rejected():
    with pytest.raises(ValidationError) as ei:
        ImageFileValidator()(_upload("anim.gif", _image_bytes("GIF")))
    assert ei.value.code == "image_ext"


def test_oversize_image_rejected():
    data = _image_bytes("JPEG") + b"\x00" * (2 * 1024 * 1024)
    with pytest.raises(ValidationError) as ei:
        ImageFileValidator(max_mb=1)(_upload("katta.jpg", data))
    assert ei.value.code == "image_too_large"


def test_pixel_bomb_rejected():
    """O'lcham cheki: 10x10=100 piksel > max_pixels=50 — bomba himoyasi."""
    with pytest.raises(ValidationError) as ei:
        ImageFileValidator(max_pixels=50)(_upload("bomba.png", _image_bytes("PNG")))
    assert ei.value.code == "image_bomb"


def test_committed_fieldfile_skipped():
    """Storage'dagi mavjud fayl (masalan, admin sarlavha tahriri) qayta o'qilmaydi."""
    ImageFileValidator()(SimpleNamespace(_committed=True))


def test_file_position_restored_after_validation():
    up = _upload("chek.jpg", _image_bytes("JPEG"))
    ImageFileValidator()(up)
    assert up.read(2) == b"\xff\xd8"  # JPEG SOI — keyingi o'quvchi fayl boshidan oladi


# --- VideoFileValidator ---


def test_valid_mp4_passes():
    VideoFileValidator()(_upload("qism.mp4", MP4_HEADER))


def test_valid_mkv_passes():
    VideoFileValidator()(_upload("qism.mkv", b"\x1a\x45\xdf\xa3" + b"\x00" * 32))


def test_valid_avi_passes():
    VideoFileValidator()(_upload("eski.avi", b"RIFF\x00\x00\x00\x00AVI " + b"\x00" * 16))


def test_wav_masquerading_as_avi_rejected():
    """RIFF bor, lekin 8-offset 'AVI ' emas ('WAVE') — ikkala imzo ham shart."""
    with pytest.raises(ValidationError) as ei:
        VideoFileValidator()(_upload("audio.avi", b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 16))
    assert ei.value.code == "video_mismatch"


def test_video_extension_rejected():
    with pytest.raises(ValidationError) as ei:
        VideoFileValidator()(_upload("virus.exe", MP4_HEADER))
    assert ei.value.code == "video_ext"


def test_html_masquerading_as_mp4_rejected():
    """Stored-XSS vektori: HTML fayl .mp4 niqobida — sehrli bayt mos kelmaydi."""
    with pytest.raises(ValidationError) as ei:
        VideoFileValidator()(_upload("kino.mp4", b"<html><script>alert(1)</script>--"))
    assert ei.value.code == "video_mismatch"


def test_oversize_video_rejected():
    data = MP4_HEADER + b"\x00" * (2 * 1024 * 1024)
    with pytest.raises(ValidationError) as ei:
        VideoFileValidator(max_mb=1)(_upload("katta.mp4", data))
    assert ei.value.code == "video_too_large"


# --- RandomFileName ---


def test_random_filename_pattern():
    """Unicode/bo'shliq/qavsli asl nom -> prefix/YYYY/MM/<uuid>.ext."""
    name = RandomFileName("receipts")(None, "МОЙ ЧЕК (шахсий) 1.JPG")
    assert re.fullmatch(r"receipts/\d{4}/\d{2}/[0-9a-f]{32}\.jpg", name)


def test_random_filename_unique_per_call():
    rfn = RandomFileName("x")
    assert rfn(None, "a.png") != rfn(None, "a.png")


def test_random_filename_equality_for_migrations():
    assert RandomFileName("a") == RandomFileName("a")
    assert RandomFileName("a") != RandomFileName("b")
