from pathlib import Path

import sqlite_xsv
from django.db import connection as default_connection
from django.db.utils import OperationalError


def load_sqlite_xsv_connection(sender, connection, **kwargs) -> None:
    if connection.vendor != 'sqlite':
        return
    if connection.connection is None:
        connection.ensure_connection()
    raw_connection = connection.connection
    raw_connection.enable_load_extension(True)
    try:
        sqlite_xsv.load(raw_connection)
    finally:
        raw_connection.enable_load_extension(False)
    connection._map_my_merchants_xsv_loaded = True
    try:
        load_statement_tables(connection)
    except RuntimeError:
        return


def load_statement_tables(connection=default_connection) -> None:
    if connection.vendor != 'sqlite':
        return
    if connection.connection is None:
        connection.ensure_connection()
    if not getattr(connection, '_map_my_merchants_xsv_loaded', False):
        load_sqlite_xsv_connection(None, connection)
    if 'map_my_merchants_statement' not in connection.introspection.table_names():
        raise RuntimeError('Statement registry table is unavailable')
    with connection.cursor() as cursor:
        cursor.execute(
            'select id, source_path from map_my_merchants_statement where source_path <> "" order by id'
        )
        for statement_id, source_path in cursor.fetchall():
            try:
                refresh_statement_table(statement_id, source_path, connection)
            except (FileNotFoundError, ValueError):
                continue


def refresh_statement_table(
    statement_id: int, source_path: str, connection=default_connection
) -> None:
    if not source_path:
        raise ValueError(f'Statement {statement_id} has no source_path')
    csv_path = Path(source_path)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    if connection.connection is None:
        connection.ensure_connection()
    if not getattr(connection, '_map_my_merchants_xsv_loaded', False):
        load_sqlite_xsv_connection(None, connection)
    table_name = f'statement_{statement_id}'
    quoted_path = "'" + str(csv_path).replace("'", "''") + "'"
    with connection.cursor() as cursor:
        cursor.execute(f'drop table if exists temp.{table_name}')
        try:
            cursor.execute(
                f'create virtual table temp.{table_name} using csv(filename={quoted_path}, header=1)'
            )
        except OperationalError:
            load_sqlite_xsv_connection(None, connection)
            cursor.execute(
                f'create virtual table temp.{table_name} using csv(filename={quoted_path}, header=1)'
            )


def statement_csv_rows(
    statement, limit: int | None = None, connection=default_connection
) -> tuple[tuple[int, dict[str, str]], ...]:
    table_name = f'statement_{statement.id}'
    limit_sql = '' if limit is None else f' limit {limit}'
    with connection.cursor() as cursor:
        cursor.execute("select name from sqlite_temp_master where type = 'table'")
        if table_name not in {name for (name,) in cursor.fetchall()}:
            refresh_statement_table(statement.id, statement.source_path, connection)
        cursor.execute(f'select rowid, * from temp.{table_name}{limit_sql}')
        field_names = tuple(description[0] for description in cursor.description[1:])
        return tuple(
            (
                row[0],
                {
                    field_name: '' if value is None else str(value)
                    for field_name, value in zip(field_names, row[1:], strict=True)
                },
            )
            for row in cursor.fetchall()
        )


def preview_statement_data(statement, row_limit: int = 10) -> str:
    try:
        rows = tuple(
            {'line_number': str(line_number), **row}
            for line_number, row in statement_csv_rows(statement, row_limit)
        )
    except (FileNotFoundError, ValueError) as error:
        return str(error)
    if not rows:
        return ''
    field_names = tuple(rows[0].keys())
    return '\n'.join((
        '\t'.join(field_names),
        *('\t'.join(row[field_name] for field_name in field_names) for row in rows),
    ))
