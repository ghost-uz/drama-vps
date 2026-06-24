"""drama/api/filters.py — katalog filtrlash [P2-T2].

Eslatma: 'status' bo'yicha filtr YO'Q — public katalog faqat published()
ko'rsatadi (ko'rinish invarianti queryset darajasida), shuning uchun status
filtri mantiqsiz/keraksiz bo'lardi.
"""

from django_filters import rest_framework as filters

from drama.models import Movie


class MovieFilter(filters.FilterSet):
    genre = filters.CharFilter(field_name="genres__slug", lookup_expr="exact")
    tag = filters.CharFilter(field_name="tags__slug", lookup_expr="exact")
    country = filters.CharFilter(field_name="country", lookup_expr="iexact")
    year_min = filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_max = filters.NumberFilter(field_name="year", lookup_expr="lte")

    class Meta:
        model = Movie
        fields = ("year", "genre", "tag", "country", "is_vip")
