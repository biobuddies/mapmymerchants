from ast import literal_eval
from logging import getLogger

from django.db.models import (
    BigIntegerField,
    DateField,
    DateTimeField,
    DecimalField,
    FloatField,
    ForeignKey,
    IntegerField,
    JSONField,
    Manager,
    ManyToManyField,
    Model,
    PROTECT,
    SET_NULL,
    UniqueConstraint,
    TextField,
    Value,
)
from django.db.models.functions import Cast, Concat
from django.utils.html import escape
from geopy.geocoders import Nominatim

logger = getLogger(__name__)


class Brand(Model):
    chase_ref_pattern = TextField(default=r'\s+#?(?P<ref>\d+)')
    created = DateTimeField(auto_now_add=True)
    match_pattern = TextField(default='')
    updated = DateTimeField(auto_now=True)

    name = TextField(unique=True)

    class Meta:
        verbose_name_plural = 'Brands'

    def __str__(self):
        return self.name


class PlaceManager(Manager):
    def with_positions(self):
        return self.annotate(
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
    address = TextField(blank=True, unique=True)
    created = DateTimeField(auto_now_add=True)
    brands = ManyToManyField(Brand, related_name='places')
    mega_latitude = IntegerField(blank=True, null=True)
    mega_longitude = IntegerField(blank=True, null=True)
    name = TextField(unique=True)
    osm_id = BigIntegerField(blank=True, null=True)
    osm_ref = TextField(blank=True)
    osm_response = JSONField(blank=True, default=dict)
    osm_type = TextField(blank=True)
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
        return f'({self.mega_latitude / 1_000_000}, {self.mega_longitude / 1_000_000})'

    def set_mega_latitude_mega_longitude_from_address(self):
        if self.mega_latitude and self.mega_longitude:
            logger.info(f'{self} already geocoded to {self.latitude_longitude}')
            return
        if not self.address:
            logger.warning(f'Unable to geocode {self} without address')
            return
        location = Nominatim(user_agent='map-my-merchants').geocode(self.address)
        self.mega_latitude = location.latitude * 1_000_000
        self.mega_longitude = location.longitude * 1_000_000
        self.save()


class Charge(Model):
    amount_usd = DecimalField(decimal_places=2, max_digits=12)
    brand = ForeignKey(Brand, on_delete=PROTECT, related_name='charges')
    created = DateTimeField(auto_now_add=True)
    description = TextField()
    place = ForeignKey(
        Place,
        blank=True,
        null=True,
        on_delete=SET_NULL,
        related_name='charges',
    )
    post_date = DateField()
    store_ref = TextField(blank=True)
    transaction_date = DateField()
    updated = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=('brand', 'amount_usd', 'description', 'post_date', 'store_ref', 'transaction_date'),
                name='charge_identity_unique',
            )
        ]
        ordering = ('-transaction_date', '-post_date', '-id')

    def __str__(self):
        return f'{self.transaction_date} {self.brand} {self.amount_usd}'
