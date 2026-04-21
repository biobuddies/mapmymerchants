from django.core.management.base import BaseCommand, CommandParser

from map_my_merchants.management.chase import resolve_missing_place_coordinates


class Command(BaseCommand):
    help = 'Resolve coordinates for places missing them by querying Overpass with stored refs.'

    def add_arguments(self, parser: CommandParser) -> None:
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
        for result in resolve_missing_place_coordinates(
            options['overpass_url'],
            options['overpass_timeout_seconds'],
        ):
            fields = ' '.join(f'{key}={value}' for key, value in sorted(result.items()))
            self.stdout.write(fields)
