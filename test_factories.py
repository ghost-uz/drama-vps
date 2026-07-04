"""Fabrikalar smoke-testlari [P11-T1] — fabrika invariantlarini qotiradi."""

import pytest

from drama.factories import EpisodeFactory, GenreFactory, MovieFactory, TagFactory
from funding.factories import FundingContributorFactory
from users.factories import UserFactory


@pytest.mark.django_db
def test_movie_factory_defaults():
    movie = MovieFactory()
    assert movie.pk and movie.slug
    assert movie.status == movie.Status.PUBLISHED  # default: katalogda ko'rinadi


@pytest.mark.django_db
def test_user_factory_profile_created_by_signal():
    user = UserFactory()
    assert user.profile is not None  # users/signals.py post_save get_or_create
    assert user.check_password("pass12345")


@pytest.mark.django_db
def test_episode_factory_season_consistent_with_movie():
    ep1 = EpisodeFactory(episode_number=1)
    ep2 = EpisodeFactory(movie=ep1.movie, episode_number=2)
    assert ep1.season == ep2.season  # bitta Movie -> bitta "Season 1" (get_or_create)
    assert ep1.season.movie == ep1.movie


@pytest.mark.django_db
def test_funding_contributor_grants_access():
    contrib = FundingContributorFactory()
    assert contrib.project.has_access(contrib.profile)


@pytest.mark.django_db
def test_genre_and_tag_factories_unique_slugs():
    assert GenreFactory().slug != GenreFactory().slug
    assert TagFactory().slug != TagFactory().slug
