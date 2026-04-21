# Map My Merchants

`mapmymerchants` tracks brands, charges, and the places where they show up on a map.

The goal is to take an export of credit card or debit card transactions and put those merchants on
a Leaflet map.

Unlike `mapmymates`, this project does not import from CardDAV, an address book, or VCF files.

Import the latest selected Chase chain transactions with:

```bash
.venv/bin/python manage.py import_chase_csv \
    /Users/jessicacovington/Downloads/Chase2216_Activity20260101_20260420_20260421.CSV
```
