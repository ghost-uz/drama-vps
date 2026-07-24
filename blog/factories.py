"""factory_boy fabrikalari — blog app [V2G-T2].

post = PostFactory()                    # published, hozir chop etilgan
draft = PostFactory(status="draft")     # qoralama (ommaviy emas)
sched = PostFactory.scheduled_future()  # kelajakda (hali ommaviy emas)
"""

from __future__ import annotations

import factory
from django.utils import timezone

from blog.models import Post


class PostFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Post

    title = factory.Sequence(lambda n: f"Maqola {n}")
    body = "<p>Test matni</p>"
    status = Post.Status.PUBLISHED
    publish_at = factory.LazyFunction(timezone.now)

    @classmethod
    def scheduled_future(cls, **kwargs: object) -> Post:
        from datetime import timedelta

        return cls(
            status=Post.Status.SCHEDULED,
            publish_at=timezone.now() + timedelta(days=1),
            **kwargs,
        )

    @classmethod
    def scheduled_past(cls, **kwargs: object) -> Post:
        from datetime import timedelta

        return cls(
            status=Post.Status.SCHEDULED,
            publish_at=timezone.now() - timedelta(hours=1),
            **kwargs,
        )
