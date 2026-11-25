from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from map_my_merchants.cash_flow import import_cash_flow_csv, summarize_months


class Command(BaseCommand):
    help = 'Import checking or card CSVs as signed transactions, then print monthly cash flow.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('csv_paths', nargs='+', type=Path)

    def handle(self, *args, **options) -> None:
        for csv_path in options['csv_paths']:
            self.stdout.write(f'imported={import_cash_flow_csv(csv_path)} csv_path={csv_path}')
        for month in summarize_months():
            self.stdout.write(
                f'{month["month"]:%Y-%m} income_usd={month["income_usd"]}'
                f' expense_usd={month["expense_usd"]} net_usd={month["net_usd"]}'
                f' {month["direction"]}'
            )
