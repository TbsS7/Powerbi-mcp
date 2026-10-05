"""Testes de modeling.query.evaluate_dax.

A conexão TOM ativa (FakeTomRuntime) só é consultada por port/
database_name -- query_runtime.connect é substituído via monkeypatch
para devolver um FakeQueryRuntime, então nada aqui toca .NET.
"""

from __future__ import annotations

import pytest

from modeling import connection, query, query_runtime
from tests.fakes.fake_query import FakeQueryRuntime
from tests.fakes.fake_tom import FakeTomRuntime


@pytest.fixture
def fake_tom() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas", port=51999)
    connection.set_active_runtime(runtime)
    return runtime


def test_evaluate_dax_connects_using_active_runtime_port_and_database(monkeypatch, fake_tom):
    fake_query = FakeQueryRuntime()
    captured: dict = {}

    def fake_connect(port: int, database_name: str):
        captured["port"] = port
        captured["database_name"] = database_name
        return fake_query

    monkeypatch.setattr(query_runtime, "connect", fake_connect)

    query.evaluate_dax("EVALUATE ROW(\"x\", 1)")

    assert captured == {"port": 51999, "database_name": "Vendas"}


def test_evaluate_dax_returns_rows_and_row_count(monkeypatch, fake_tom):
    dax = 'EVALUATE ROW("Total", 42)'
    fake_query = FakeQueryRuntime(rows_by_query={dax: [{"Total": 42}]})
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)

    result = query.evaluate_dax(dax)

    assert result == {"rows": [{"Total": 42}], "row_count": 1, "truncated": False}


def test_evaluate_dax_strips_brackets_from_alias_only_column_names(monkeypatch, fake_tom):
    dax = "EVALUATE {[Total Vendas]}"
    fake_query = FakeQueryRuntime(rows_by_query={dax: [{"[Total Vendas]": 42}]})
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)

    result = query.evaluate_dax(dax)

    assert result["rows"] == [{"Total Vendas": 42}]


def test_evaluate_dax_keeps_table_qualified_column_names_untouched(monkeypatch, fake_tom):
    dax = "EVALUATE Financials"
    fake_query = FakeQueryRuntime(rows_by_query={dax: [{"Financials[Segment]": "Government"}]})
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)

    result = query.evaluate_dax(dax)

    assert result["rows"] == [{"Financials[Segment]": "Government"}]


def test_evaluate_dax_forwards_max_rows_and_reports_truncated(monkeypatch, fake_tom):
    dax = "EVALUATE Financials"
    fake_query = FakeQueryRuntime(
        rows_by_query={dax: [{"n": 1}, {"n": 2}, {"n": 3}]}
    )
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)

    result = query.evaluate_dax(dax, max_rows=2)

    assert result == {"rows": [{"n": 1}, {"n": 2}], "row_count": 2, "truncated": True}
    assert fake_query.calls[0] == ("execute", {"dax_query": dax, "max_rows": 2})


def test_evaluate_dax_max_rows_not_reached_is_not_truncated(monkeypatch, fake_tom):
    dax = "EVALUATE Financials"
    fake_query = FakeQueryRuntime(rows_by_query={dax: [{"n": 1}]})
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)

    result = query.evaluate_dax(dax, max_rows=10)

    assert result == {"rows": [{"n": 1}], "row_count": 1, "truncated": False}


def test_evaluate_dax_closes_the_connection_even_after_executing(monkeypatch, fake_tom):
    fake_query = FakeQueryRuntime()
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)

    query.evaluate_dax("EVALUATE ROW(\"x\", 1)")

    assert fake_query.calls[0][0] == "execute"
    assert fake_query.calls[-1][0] == "close"


def test_evaluate_dax_closes_the_connection_even_if_execute_raises(monkeypatch, fake_tom):
    class RaisingQueryRuntime(FakeQueryRuntime):
        def execute(self, dax_query: str, max_rows: int | None = None):
            super().execute(dax_query, max_rows=max_rows)
            raise RuntimeError("consulta inválida")

    fake_query = RaisingQueryRuntime()
    monkeypatch.setattr(query_runtime, "connect", lambda port, database_name: fake_query)

    with pytest.raises(RuntimeError):
        query.evaluate_dax("EVALUATE ROW(\"x\", 1)")

    assert fake_query.calls[-1][0] == "close"
