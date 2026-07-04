"""factory_boy fabrikalari — funding app [P11-T1]."""

import factory

from drama.factories import MovieFactory
from funding.models import FundingContributor, FundingProject
from users.factories import UserFactory


class FundingProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FundingProject

    movie = factory.SubFactory(MovieFactory)
    target_amount = 1000


class FundingContributorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FundingContributor

    project = factory.SubFactory(FundingProjectFactory)
    profile = factory.LazyFunction(lambda: UserFactory().profile)
    amount_paid = 100
