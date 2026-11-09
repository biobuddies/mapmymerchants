from ast import literal_eval
from logging import getLogger

from django.conf import settings
from django.db.models import (
    PROTECT,
    BigIntegerField,
    BooleanField,
    DateField,
    DateTimeField,
    DecimalField,
    FloatField,
    ForeignKey,
    IntegerField,
    JSONField,
    Manager,
    Model,
    TextField,
    UniqueConstraint,
    Value,
)
from django.db.models.functions import Cast, Concat
from django.utils.html import escape
from geopy.geocoders import Nominatim
from geopy.location import Location

logger = getLogger(__name__)


class Platform(Model):
    name = TextField(unique=True)
    pattern = TextField()

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs) -> None:
        super().save(*args, **kwargs)


class Brand(Model):
    created = DateTimeField(auto_now_add=True)
    private = BooleanField(blank=True, default=None, null=True)
    wikidata_id = TextField(blank=True)
    updated = DateTimeField(auto_now=True)
    updated_by = ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=PROTECT,
        related_name='brand_updates',
    )

    statement_name = TextField(unique=True, db_column='name')
    display_name = TextField()

    class Meta:
        verbose_name_plural = 'Brands'

    def __str__(self):
        return self.display_name


class Statement(Model):
    content_sha256 = TextField(unique=True)
    created = DateTimeField(auto_now_add=True)
    source_name = TextField()
    source_path = TextField(blank=True)
    updated = DateTimeField(auto_now=True)

    def __str__(self):
        return self.source_name


class PlaceManager(Manager):
    def with_positions(self):
        return self.filter(mega_latitude__isnull=False, mega_longitude__isnull=False).annotate(
            position=Concat(
                Value('['),
                Cast('mega_latitude', FloatField()) / 1_000_000,
                Value(','),
                Cast('mega_longitude', FloatField()) / 1_000_000,
                Value(']'),
                output_field=TextField(),
            )
        )

    def as_tuples(self):
        return tuple(
            (literal_eval(position), escape(name), escape(address))
            for position, name, address in self.with_positions().values_list(
                'position', 'name', 'address'
            )
        )


class Place(Model):
    address = TextField(blank=True)
    brand = ForeignKey(Brand, on_delete=PROTECT, related_name='places')
    created = DateTimeField(auto_now_add=True)
    mega_latitude = IntegerField(blank=True, null=True)
    mega_longitude = IntegerField(blank=True, null=True)
    name = TextField(unique=True)
    osm_id = BigIntegerField(blank=True, null=True)
    osm_ref = TextField(blank=True)
    osm_response = JSONField(blank=True, default=dict)
    osm_type = TextField(blank=True)
    private = BooleanField(blank=True, default=None, null=True)
    updated = DateTimeField(auto_now=True)

    objects = PlaceManager()

    class Meta:
        constraints = [
            UniqueConstraint(fields=('osm_type', 'osm_id'), name='place_osm_type_osm_id_unique')
        ]

    def __str__(self):
        return self.name

    @property
    def latitude_longitude(self):
        if self.mega_latitude is None or self.mega_longitude is None:
            return ''
        return f'({self.mega_latitude / 1_000_000}, {self.mega_longitude / 1_000_000})'

    def set_mega_latitude_mega_longitude_from_address(self):
        if self.mega_latitude and self.mega_longitude:
            logger.info(f'{self} already geocoded to {self.latitude_longitude=}')
            return
        if not self.address:
            logger.warning(f'Unable to geocode {self} without address')
            return
        location = Nominatim(user_agent='map-my-merchants').geocode(self.address)
        if not isinstance(location, Location):
            logger.warning(f'No geocoding match for {self} at {self.address=}')
            return
        self.mega_latitude = round(location.latitude * 1_000_000)
        self.mega_longitude = round(location.longitude * 1_000_000)
        self.save()


class Charge(Model):
    amount_usd = DecimalField(decimal_places=2, max_digits=12)
    description = TextField()
    line_number = IntegerField()
    place = ForeignKey(Place, on_delete=PROTECT, related_name='charges')
    post_date = DateField()
    raw_input = JSONField(blank=True, default=dict)
    platform = ForeignKey(
        Platform, blank=True, null=True, on_delete=PROTECT, related_name='charges'
    )
    statement = ForeignKey(Statement, on_delete=PROTECT, related_name='charges')
    transaction_date = DateField()

    class Meta:
        constraints = [
            UniqueConstraint(fields=('statement', 'line_number'), name='charge_identity_unique')
        ]
        ordering = ('-transaction_date', '-post_date', '-id')

    def __str__(self):
        return f'{self.statement}#{self.line_number} {self.amount_usd}'
