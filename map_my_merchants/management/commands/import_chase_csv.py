from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from map_my_merchants.management.chase import import_latest_places


class Command(BaseCommand):
    help = 'Import the latest Chase transactions for selected chains into businesses and places.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('csv_path', type=Path)
        parser.add_argument(
            '--overpass-url',
            default='https://overpass-api.de/api/interpreter',
        )
        parser.add_argument(
            '--overpass-timeout-seconds',
            default=180,
            type=int,
        )

    def handle(self, *args, **options) -> None:
        for result in import_latest_places(
            options['csv_path'],
            options['overpass_url'],
            options['overpass_timeout_seconds'],
        ):
            fields = ' '.join(f'{key}={value}' for key, value in sorted(result.items()))
            self.stdout.write(fields)
