# Map My Merchants

`mapmymerchants` tracks brands, charges, and the places where they show up on a map.

The goal is to take an export of credit card or debit card transactions and put those merchants on
a Leaflet map.

Unlike `mapmymates`, this project does not import from CardDAV, an address book, or VCF files.

Register a Chase CSV path without importing charges or places with:

```bash
.venv/bin/python manage.py import_chase_csv \
    ~/Downloads/chase.csv \
    --register-only
```

Register a Chase CSV path and import the first 30 rows into charges and unresolved places with:

```bash
.venv/bin/python manage.py import_chase_csv \
    ~/Downloads/chase.csv
```

Resolve coordinates for places missing them with:

```bash
.venv/bin/python manage.py resolve_place_coordinates
```
