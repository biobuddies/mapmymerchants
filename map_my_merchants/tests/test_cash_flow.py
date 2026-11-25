from datetime import date
from decimal import Decimal

from django.core.management import call_command
from pytest import mark

from map_my_merchants.cash_flow import import_cash_flow_csv, parse_amount_usd, summarize_months
from map_my_merchants.models import Transaction


@mark.parametrize(
    ('text', 'expected'),
    (('-12.34', '-12.34'), ('$1,234.56', '1234.56'), ('(12.34)', '-12.34'), ('', '0')),
)
def test_parse_amount_usd(text, expected):
    assert parse_amount_usd(text) == Decimal(expected)


@mark.django_db
def test_summarize_months_from_split_and_signed_columns(tmp_path):
    checking_path = tmp_path / 'checking.csv'
    checking_path.write_text(
        '﻿Date,Description,Debit,Credit,Balance\n'
        '03/01/2026,PAYROLL,,2000.00,2000.00\n'
        '03/05/2026,RENT,1500.00,,500.00\n'
        '04/01/2026,PAYROLL,,2000.00,2500.00\n'
        '04/02/2026,CAR REPAIR,"$2,600.00",,-100.00\n'
    )
    card_path = tmp_path / 'card.csv'
    card_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/17/2026,04/19/2026,FOOD LION #1484,Groceries,Sale,-46.20,\n'
    )

    call_command('import_cash_flow_csv', checking_path, card_path)
    import_cash_flow_csv(checking_path)

    assert Transaction.objects.count() == 5
    assert summarize_months() == (
        {
            'direction': 'saving',
            'expense_usd': Decimal('1500.00'),
            'income_usd': Decimal('2000.00'),
            'month': date(2026, 3, 1),
            'net_usd': Decimal('500.00'),
        },
        {
            'direction': 'spending',
            'expense_usd': Decimal('2646.20'),
            'income_usd': Decimal('2000.00'),
            'month': date(2026, 4, 1),
            'net_usd': Decimal('-646.20'),
        },
    )


@mark.django_db
def test_cash_flow_view(client, tmp_path):
    csv_path = tmp_path / 'checking.csv'
    csv_path.write_text('Date,Description,Amount\n2026-03-01,PAYROLL,100\n2026-03-02,GAS,-50\n')
    import_cash_flow_csv(csv_path)

    response = client.get('/cash-flow/')

    assert response.status_code == 200
    assert b'50.00 saving' in response.content
