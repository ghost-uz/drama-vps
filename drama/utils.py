import os
from io import BytesIO
from PIL import Image
from django.core.files.base import ContentFile
from django.utils.text import slugify

def process_image(image_field, title, folder="movies"):
    """Rasmni WebP formatiga o'tkazish va siqish"""
    if not image_field:
        return None

    # 1. Rasmni ochish
    img = Image.open(image_field)
    
    # 2. Agar rasm RGB bo'lmasa (masalan PNG), RGB ga o'tkazamiz
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # 3. Rasmni xotirada (RAM) saqlash uchun buffer
    output_io_stream = BytesIO()
    
    # 4. WebP formatida siqish (quality=80 - eng optimali)
    img.save(output_io_stream, format='WEBP', quality=80)
    output_io_stream.seek(0)

    # 5. Yangi fayl nomini yasash (poster-nomi.webp)
    filename = f"{slugify(title)}.webp"
    
    # 6. Django tushunadigan ContentFile qaytarish
    return ContentFile(output_io_stream.read(), name=os.path.join(folder, filename))