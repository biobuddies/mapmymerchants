from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from map_my_merchants.management.coastal import import_coastal_rows


class Command(BaseCommand):
    help = 'Import a small batch of Coastal POS purchases, preserving original CSV row numbers.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('csv_path', type=Path)
        parser.add_argument('--limit', default=3, type=int)

    def handle(self, *args, **options) -> None:
        if options['limit'] < 1:
            raise CommandError('--limit must be positive')
        results = import_coastal_rows(options['csv_path'], options['limit'])
        for result in results:
            self.stdout.write(' '.join(f'{key}={value}' for key, value in sorted(result.items())))
        self.stdout.write(f'Imported {len(results)} Coastal POS purchases.')
