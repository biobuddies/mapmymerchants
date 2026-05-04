from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from map_my_merchants.management.chase import import_chase_rows, register_statement_path


class Command(BaseCommand):
    help = 'Import the first 30 Chase CSV rows into brands, charges, and unresolved places.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('csv_path', type=Path)
        parser.add_argument(
            '--register-only',
            action='store_true',
            help='Update the statement registry entry without importing charges or places.',
        )

    def handle(self, *args, **options) -> None:
        csv_path = options['csv_path']
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
