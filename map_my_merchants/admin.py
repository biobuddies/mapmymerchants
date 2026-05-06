from json import dumps

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Case, FloatField, TextField, Value, When
from django.db.models.functions import Abs, Cast, Concat, Round
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import JsonLexer

from .management.chase import parsed_osm_lookup, refresh_place_from_osm_lookup
from .models import Brand, Charge, Place, Platform, Statement
from .xsv import preview_statement_data


class PlaceAdminForm(forms.ModelForm):
    osm_lookup = forms.CharField(label='OpenStreetMap lookup', required=False)

    class Meta:
        model = Place
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.osm_id and self.instance.osm_type:
            self.fields['osm_lookup'].initial = f'{self.instance.osm_type}/{self.instance.osm_id}'

    def clean_osm_lookup(self):
        value = self.cleaned_data['osm_lookup'].strip()
        if not value:
            return value
        try:
            parsed_osm_lookup(value)
        except ValueError as error:
            raise ValidationError(str(error)) from error
        return value


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'wikidata_id', 'match_pattern', 'ref_pattern', 'created', 'updated')
    readonly_fields = ('id', 'ref_pattern', 'created', 'match_pattern', 'name', 'updated', 'wikidata_id')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ('name', 'pattern')


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    fields = (
        'statement',
        'line_number',
        'transaction_date',
        'post_date',
        'platform',
        'place',
        'amount_usd',
        'description',
        'raw_input_table',
    )
    list_display = (
        'statement',
        'line_number',
        'transaction_date',
        'platform',
        'place',
        'amount_usd',
        'description',
    )
    list_display_links = ('place',)
    readonly_fields = (
        'id',
        'amount_usd',
        'description',
        'line_number',
        'platform',
        'post_date',
        'raw_input',
        'raw_input_table',
        'statement',
        'transaction_date',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Raw input')
    def raw_input_table(self, obj):
        if not isinstance(obj.raw_input, dict):
            return obj.raw_input
        rows = tuple(obj.raw_input.items())
        if not rows:
            return ''
        return format_html(
            (
                '<table><thead><tr><th>Key</th><th>Value</th></tr></thead>'
                '<tbody>{}</tbody></table>'
            ),
            format_html_join(
                '',
                '<tr><th><code>{}</code></th><td><code>{}</code></td></tr>',
                rows,
            ),
        )


@admin.register(Statement)
class StatementAdmin(admin.ModelAdmin):
    list_display = ('source_name', 'content_sha256', 'source_path', 'created', 'updated')
    readonly_fields = ('id', 'content_sha256', 'created', 'source_name', 'source_path', 'source_preview', 'updated')

    @admin.display(description='Source data')
    def source_preview(self, obj):
        if not (preview := preview_statement_data(obj)):
            return ''
        return format_html('<pre><code>{}</code></pre>', preview)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    form = PlaceAdminForm
    fields = ('name', 'brand', 'osm_lookup', 'osm_link', 'osm_response_html', 'address', 'coordinates', 'created')
    list_display = ('name', 'brand', 'osm_link', 'address', 'coordinates', 'created')
    readonly_fields = (
        'id',
        'address',
        'brand',
        'coordinates',
        'created',
        'mega_latitude',
        'mega_longitude',
        'name',
        'osm_id',
        'osm_link',
        'osm_ref',
        'osm_response',
        'osm_response_html',
        'osm_type',
        'updated',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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
        if obj.mega_latitude is None or obj.mega_longitude is None:
            return ''
        return obj.coordinates

    @admin.display(description='OpenStreetMap link', ordering='osm_id')
    def osm_link(self, obj):
        if not obj.osm_id or not obj.osm_type:
            return ''
        return format_html(
            '<a href="https://www.openstreetmap.org/{}/{}">{}</a>',
            obj.osm_type,
            obj.osm_id,
            f'{obj.osm_type}/{obj.osm_id}',
        )

    @admin.display(description='OpenStreetMap response')
    def osm_response_html(self, obj):
        if not obj.osm_response:
            return ''
        formatter = HtmlFormatter(style='default')
        highlighted = highlight(dumps(obj.osm_response, indent=2, sort_keys=True), JsonLexer(), formatter)
        styles = formatter.get_style_defs()
        return format_html('<style>{}</style>{}', mark_safe(styles), mark_safe(highlighted))

    def save_model(self, request, obj, form, change):
        osm_lookup = form.cleaned_data['osm_lookup']
        if osm_lookup:
            refresh_place_from_osm_lookup(
                obj,
                osm_lookup,
                overpass_timeout_seconds=180,
                overpass_url='https://overpass-api.de/api/interpreter',
            )
            return
        super().save_model(request, obj, form, change)
