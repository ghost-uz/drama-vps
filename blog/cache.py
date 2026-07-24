"""Blog keshi — versiyalangan kalitlar [V2G-T2].

drama/cache.py naqshini takrorlaydi, lekin ALOHIDA versiya: blog kontenti
katalogdan mustaqil o'zgaradi, shu bois movie-bump'lar blog fragmentlarini
behuda invalidatsiya qilmasin (va aksincha). Kalit: ``blog:v{n}:{name}``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.core.cache import cache

BLOG_VERSION_KEY = "blog:ver"
DEFAULT_TIMEOUT = 6 * 60 * 60  # 6 soat — bump asosiy invalidatsiya, TTL zaxira


def blog_version() -> int:
    version = cache.get(BLOG_VERSION_KEY)
    if version is None:
        cache.add(BLOG_VERSION_KEY, 1, None)
        version = cache.get(BLOG_VERSION_KEY, 1)
    return int(version)


def bump_blog_version() -> int:
    """Versiyani +1 — barcha blog:* kalitlar darhol eskiradi."""
    try:
        return int(cache.incr(BLOG_VERSION_KEY))
    except ValueError:
        cache.set(BLOG_VERSION_KEY, 2, None)
        return 2


def blog_key(name: str) -> str:
    return f"blog:v{blog_version()}:{name}"


def get_or_set_blog(name: str, producer: Callable[[], Any], timeout: int = DEFAULT_TIMEOUT) -> Any:
    key = blog_key(name)
    value = cache.get(key)
    if value is None:
        value = producer()
        cache.set(key, value, timeout)
    return value
