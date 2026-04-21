from django.contrib import admin
from django.db.models import Case, FloatField, TextField, Value, When
from django.db.models.functions import Abs, Cast, Concat, Round
from django.utils.html import format_html

from .models import Brand, Charge, Place


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'match_pattern', 'chase_ref_pattern', 'created', 'updated')
    readonly_fields = ('created', 'updated')


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_date',
        'brand',
        'amount_usd',
        'store_ref',
        'place',
        'created',
        'updated',
    )
    readonly_fields = ('created', 'updated')


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    fields = ('name', 'brands', 'address', 'osm_link', 'coordinates', 'created')
    list_display = ('name', 'osm_link', 'address', 'coordinates', 'created')
    readonly_fields = ('osm_link', 'coordinates', 'created')

    def get_queryset(self, request):
        latitude = Round(Abs(Cast('mega_latitude', FloatField()) / 1_000_000), 6)
        longitude = Round(Abs(Cast('mega_longitude', FloatField()) / 1_000_000), 6)
        return super().get_queryset(request).annotate(
            coordinates=Concat(
                Cast(latitude, TextField()),
                Value('° '),
                Case(When(mega_latitude__lt=0, then=Value('S')), default=Value('N')),
                Value(', '),
                Cast(longitude, TextField()),
                Value('° '),
                Case(When(mega_longitude__lt=0, then=Value('W')), default=Value('E')),
                output_field=TextField(),
            )
        )

    @admin.display(description='Coordinates', ordering='coordinates')
    def coordinates(self, obj):
        return obj.coordinates

    @admin.display(description='OpenStreetMap', ordering='osm_id')
    def osm_link(self, obj):
        if not obj.osm_id or not obj.osm_type:
            return ''
        return format_html(
            '<a href="https://www.openstreetmap.org/{}/{}">{}</a>',
            obj.osm_type,
            obj.osm_id,
            f'{obj.osm_type}/{obj.osm_id}',
        )
