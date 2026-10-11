"""Trusted demo entrypoint for the isolated rootfs; never called by API workers."""

import json
import runpy
import sqlite3
import sys
from pathlib import Path


def statements(source):
    current = ""
    for char in source:
        current += char
        if char == ";" and sqlite3.complete_statement(current):
            yield current
            current = ""
    if current.strip():
        yield current


def sql_demo(source):
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE demo_items (id INTEGER PRIMARY KEY, value INTEGER)")
        connection.executemany("INSERT INTO demo_items VALUES (?, ?)", [(1, 10), (2, 20), (3, 30)])
        connection.enable_load_extension(False)

        def authorize(operation, first, second, database, trigger):
            if operation in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}:
                return sqlite3.SQLITE_DENY
            if operation == sqlite3.SQLITE_FUNCTION and (second or "").lower() == "load_extension":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        for count, statement in enumerate(statements(source), start=1):
            if count > 20:
                raise ValueError("statement_limit")
            cursor = connection.execute(statement)
            if cursor.description:
                rows = cursor.fetchmany(101)
                if len(rows) > 100:
                    raise ValueError("row_limit")
                print(json.dumps({"columns": [col[0] for col in cursor.description], "rows": rows}))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"code", "sql"}:
        raise SystemExit(64)
    if sys.argv[1] == "code":
        sys.path.insert(0, "/workspace")
        runpy.run_path("/workspace/main.py", run_name="__main__")
    else:
        sql_demo(Path("/workspace/query.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
