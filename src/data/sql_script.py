"""Разбор SQL-скриптов миграций (без executescript — сохраняет откат транзакции)."""

from __future__ import annotations

import re

from data.db import Connection

_BEGIN = re.compile(r"\bBEGIN\b", re.IGNORECASE)
_END = re.compile(r"\bEND\b", re.IGNORECASE)


def split_sql_statements(script: str) -> list[str]:
    """Разбить SQL на statements с учётом блоков BEGIN…END у триггеров."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(script)
    begin_depth = 0
    in_single = False
    in_double = False

    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""

        if not in_single and not in_double and ch == "-" and nxt == "-":
            while i < n and script[i] != "\n":
                buf.append(script[i])
                i += 1
            continue

        if not in_double and ch == "'":
            buf.append(ch)
            if in_single and nxt == "'":
                buf.append(nxt)
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if not in_single and ch == '"':
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue

        if not in_single and not in_double:
            rest = script[i:]
            begin_match = _BEGIN.match(rest)
            end_match = _END.match(rest)
            if begin_match:
                token = begin_match.group(0)
                buf.append(token)
                begin_depth += 1
                i += len(token)
                continue
            if end_match and begin_depth > 0:
                token = end_match.group(0)
                buf.append(token)
                begin_depth -= 1
                i += len(token)
                continue
            if ch == ";" and begin_depth == 0:
                stmt = "".join(buf).strip()
                if stmt:
                    statements.append(stmt)
                buf = []
                i += 1
                continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def execute_script_transactional(conn: Connection, sql: str) -> None:
    """Выполнить скрипт statement-by-statement внутри текущей транзакции."""
    for statement in split_sql_statements(sql):
        conn.execute(statement)
