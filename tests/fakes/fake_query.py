"""Fake do QueryRuntime Protocol (modeling.query_runtime): devolve
linhas pré-programadas para uma consulta DAX específica, sem tocar
ADOMD.NET/pythonnet. Registra cada chamada em `.calls`, mesmo padrão de
tests/fakes/fake_tom.py."""

from __future__ import annotations

from typing import Any

from errors import DaxQueryError


class FakeQueryRuntime:
    def __init__(
        self,
        rows_by_query: dict[str, list[dict[str, Any]]] | None = None,
        errors_by_query: dict[str, str] | None = None,
    ) -> None:
        self._rows_by_query = rows_by_query or {}
        self._errors_by_query = errors_by_query or {}
        self.calls: list[tuple[str, dict]] = []

    def execute(
        self, dax_query: str, max_rows: int | None = None
    ) -> tuple[list[dict[str, Any]], bool]:
        self.calls.append(("execute", {"dax_query": dax_query, "max_rows": max_rows}))
        if dax_query in self._errors_by_query:
            raise DaxQueryError(dax_query=dax_query, original_message=self._errors_by_query[dax_query])
        rows = self._rows_by_query.get(dax_query, [])
        if max_rows is not None and len(rows) > max_rows:
            return rows[:max_rows], True
        return rows, False

    def clear_cache(self, database_id: str) -> None:
        self.calls.append(("clear_cache", {"database_id": database_id}))

    def close(self) -> None:
        self.calls.append(("close", {}))
