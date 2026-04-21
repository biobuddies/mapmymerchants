from django.contrib import admin

from .models import Business, Place


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ('name', 'created', 'updated')
    readonly_fields = ('created', 'updated')


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'osm_ref', 'osm_id', 'address', 'created', 'updated')
    readonly_fields = ('created', 'updated')
