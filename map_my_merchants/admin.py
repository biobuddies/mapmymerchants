from django.contrib import admin

from .models import Brand, Charge, Place


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'created', 'updated')
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
    list_display = ('name', 'osm_ref', 'osm_id', 'address', 'created', 'updated')
    readonly_fields = ('created', 'updated')
