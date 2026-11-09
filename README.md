# Map My Merchants

`mapmymerchants` tracks brands, charges, and the places where they show up on a map.

The goal is to take an export of credit card or debit card transactions and put those merchants on
a Leaflet map.

Unlike `mapmymates`, this project does not import from CardDAV, an address book, or VCF files. A cool stretch goal could be to create contacts in a secondary address book to allow transaction emails.

Register a Chase CSV path without importing charges or places with:

```bash
.venv/bin/python manage.py import_chase_csv \
    /Users/jessicacovington/Downloads/Chase2216_Activity20260101_20260420_20260421.CSV \
    --register-only
```

Register a Chase CSV path and import the first 30 rows into charges and unresolved places with:

```bash
.venv/bin/python manage.py import_chase_csv \
    /Users/jessicacovington/Downloads/Chase2216_Activity20260101_20260420_20260421.CSV
```

Resolve coordinates for places missing them with:

```bash
.venv/bin/python manage.py resolve_place_coordinates
```

Import the first three Coastal POS purchases (skip deposits, transfers, and refunds) with:

```bash
.venv/bin/python manage.py import_coastal_csv \
    ~/Downloads/'Cocheck Transactions 20260101_20261031.csv' --limit=3
```

The original CSV rows are retained. Coastal supplies one date, used for both transaction and post
dates. Other Coastal payment descriptions are not imported yet.

Brands and places have a nullable `private` flag, editable in the admin. `None` means unreviewed.
Only `private=False` rows are seeded; places also require `brand__private=False`.

After applying migrations and reviewing privacy flags, snapshot public brands and places with:

```bash
.venv/bin/python manage.py reseed
```

This writes the next `*_seed.py` data migration, using brand statement names and place names
instead of database IDs. Transactions, timestamps, and user provenance are omitted. Existing
privacy flags are preserved when applying seeds.

Reseeding removes superseded rows from earlier seed migrations' literal `BRANDS` and `PLACES`
snapshots, including rows now private or unreviewed. Other rows, migration dependencies, and
operations remain. Apply the new migration normally; its reverse is a no-op.

## TODO
* Support other Coastal payments and any other useful exports
* Switch to Decimal for latitude and longitude
* Get reusable fields into django-plugin-field-day
