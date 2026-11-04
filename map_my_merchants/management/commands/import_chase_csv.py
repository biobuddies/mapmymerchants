from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser

from map_my_merchants.management.chase import (
    get_or_create_brand,
    get_or_create_place,
    import_chase_rows,
    parse_brand_store_ref,
    place_name,
    register_statement_path,
)
from map_my_merchants.models import Brand, Charge, Place, Statement


class Command(BaseCommand):
    help = (
        'Import CSV or reprocess charges. '
        'Use "file.csv" to import, "file.csv:28" or "file.csv:28-30" to reprocess.'
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            'spec',
            type=str,
            help='CSV path, or <source_name>:<line_range> to reprocess existing charges',
        )
        parser.add_argument(
            '--register-only',
            action='store_true',
            help='Update the statement registry entry without importing charges or places.',
        )

    def handle(self, *args, **options) -> None:
        spec: str = options['spec']
        source_name, colon, line_spec = spec.rpartition(':')
        if colon:
            self._reprocess(source_name, line_spec)
        else:
            csv_path = Path(options['spec'])
            if options['register_only']:
                statement = register_statement_path(csv_path)
                results = [
                    {
                        'content_sha256': statement.content_sha256,
                        'source_name': statement.source_name,
                        'source_path': statement.source_path,
                        'status': 'registered-statement',
                    }
                ]
            else:
                results = import_chase_rows(csv_path)
            for result in results:
                fields = ' '.join(f'{key}={value}' for key, value in sorted(result.items()))
                self.stdout.write(fields)

    def _reprocess(self, source_name: str, line_spec: str) -> None:
        updated_by = get_user_model().objects.get(username='from-statement')
        line_numbers = self._parse_line_range(line_spec)
        statement = Statement.objects.get(source_name=source_name)
        charges = Charge.objects.filter(statement=statement, line_number__in=line_numbers).order_by(
            'line_number'
        )

        if not charges:
            self.stderr.write(f'No charges for {source_name!r} lines {line_spec}.')
            return

        orphan_place_ids = set()
        for charge in charges:
            if charge.place_id:
                orphan_place_ids.add(charge.place_id)
            self._reprocess_one(charge, updated_by)

        self._cleanup_orphans(orphan_place_ids)

    def _parse_line_range(self, line_spec: str) -> list[int]:
        if '-' in line_spec:
            start, end = line_spec.split('-', 1)
            return list(range(int(start), int(end) + 1))
        return [int(line_spec)]

    def _reprocess_one(self, charge: Charge, updated_by) -> None:
        description = charge.raw_input.get('Description', '')
        old_brand_name = (
            charge.place.brand.display_name if charge.place_id and charge.place.brand_id else None
        )
        old_place_name = charge.place.name if charge.place_id else None

        brand_name, store_ref = parse_brand_store_ref(description)
        brand = get_or_create_brand(
            brand_name, pk=charge.place.brand_id if charge.place_id else None, updated_by=updated_by
        )
        target_place_name = place_name(brand, description, store_ref)
        place = get_or_create_place(
            brand=brand,
            name=target_place_name,
            store_ref=store_ref,
            pk=charge.place_id if charge.place_id else None,
        )

        changed = []
        if old_brand_name and old_brand_name != brand.display_name:
            changed.append(f'brand: {old_brand_name!r} -> {brand.display_name!r}')
        if old_place_name and old_place_name != place.name:
            changed.append(f'place: {old_place_name!r} -> {place.name!r}')

        if changed:
            self.stdout.write(f'line {charge.line_number}: ' + ', '.join(changed))
        else:
            self.stdout.write(f'line {charge.line_number}: unchanged')

    def _cleanup_orphans(self, orphan_place_ids: set[int]) -> None:
        for place_id in orphan_place_ids:
            if not Charge.objects.filter(place_id=place_id).exists():
                place = Place.objects.select_related('brand').get(id=place_id)
                brand = place.brand
                place.delete()
                if not Place.objects.filter(brand=brand).exists():
                    brand.delete()
                    self.stdout.write(f'Orphan brand {brand.id} ({brand.display_name!r}) deleted.')
                self.stdout.write(f'Orphan place {place_id} ({place.name!r}) deleted.')
