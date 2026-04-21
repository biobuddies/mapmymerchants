from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from map_my_merchants.management.chase import import_chase_rows, repair_statement_raw_input


class Command(BaseCommand):
    help = 'Import the first 30 Chase CSV rows into brands, charges, and unresolved places.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('csv_path', type=Path)
        parser.add_argument(
            '--repair-raw-input',
            action='store_true',
            help='Rewrite raw_input for the existing first 30 imported rows from the CSV headers.',
        )

    def handle(self, *args, **options) -> None:
        csv_path = options['csv_path']
        if options['repair_raw_input']:
            if not csv_path.exists():
                raise CommandError(f'Missing CSV: {csv_path}')
            results = repair_statement_raw_input(csv_path)
        else:
            results = import_chase_rows(csv_path)
        for result in results:
            fields = ' '.join(f'{key}={value}' for key, value in sorted(result.items()))
            self.stdout.write(fields)
