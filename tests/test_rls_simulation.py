"""Testes da simulação de RLS: evaluate_dax_as_role (modeling.query) e a
montagem da string de conexão ADOMD (query_runtime.
build_connection_string).

Fonte: doc oficial "Connection string properties (Analysis Services)" --
`Roles` ("comma-delimited list of predefined roles ... An administrator
using this property connects using the permissions conveyed by the
role"). `EffectiveUserName` (simular um usuário específico, pra RLS
dinâmico) foi testado ao vivo e NÃO funciona no Desktop local sem
domínio corporativo -- removido por decisão do usuário (ver README).

Nenhum teste toca ADOMD.NET: query_runtime.connect é substituído via
monkeypatch, mesmo padrão de tests/test_query.py.
"""

from __future__ import annotations

import pytest

from errors import InvalidRlsSimulationError, QueryConnectionError, RoleNotFoundError, StaleConnectionError
from modeling import connection, query, query_runtime
from tests.fakes.fake_query import FakeQueryRuntime
from tests.fakes.fake_tom import FakeTomRuntime

QUERY = 'EVALUATE ROW("Vendas", [Total Sales])'


@pytest.fixture
def fake_tom() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas", port=51234)
    runtime.create_role("Gerente Governo")
    runtime.create_role("Gerente Varejo")
    connection.set_active_runtime(runtime)
    return runtime


@pytest.fixture
def captured(monkeypatch) -> dict:
    """Substitui query_runtime.connect e guarda os argumentos recebidos."""
    box: dict = {"fake": FakeQueryRuntime({QUERY: [{"[Vendas]": 52.5}]})}

    def fake_connect(port, database_name, roles=None):
        box.update(port=port, database_name=database_name, roles=roles)
        return box["fake"]

    monkeypatch.setattr(query_runtime, "connect", fake_connect)
    return box


# --- build_connection_string (função pura) --------------------------------------


def test_connection_string_without_roles_is_unchanged():
    assert query_runtime.build_connection_string(51234, "Vendas") == "Data Source=localhost:51234;Catalog=Vendas"


def test_connection_string_with_roles_is_comma_delimited_and_quoted():
    result = query_runtime.build_connection_string(51234, "Vendas", roles=["Gerente Governo", "Gerente Varejo"])
    assert result == 'Data Source=localhost:51234;Catalog=Vendas;Roles="Gerente Governo,Gerente Varejo"'


def test_connection_string_refuses_unsafe_values():
    # defesa em profundidade: mesmo se a validação de cima falhar, nada
    # com ; " ou , (em role) entra na string de conexão
    for bad_roles in (["a;Data Source=outro"], ['a"b'], ["a,b"]):
        with pytest.raises(ValueError):
            query_runtime.build_connection_string(1, "Vendas", roles=bad_roles)


# --- falha ao abrir a conexão de consulta (achado ao vivo, 2026-09-26) ----------------


def test_open_error_unknown_to_translator_still_carries_engine_message():
    """Achado ao vivo: um AdomdErrorResponseException no Open() (ex:
    EffectiveUserName que o Desktop local não consegue resolver) não era
    reconhecido pelo tradutor e escapava cru -> "Error executing tool X"
    sem mensagem nenhuma. Agora vira QueryConnectionError com a mensagem
    do motor."""
    AdomdErrorResponseException = type("AdomdErrorResponseException", (Exception,), {})
    exc = AdomdErrorResponseException(
        "The following system error occurred:  The name provided is not a properly formed account name."
    )

    translated = query_runtime.translate_open_error(exc)

    assert isinstance(translated, QueryConnectionError)
    assert "properly formed account name" in str(translated)


def test_open_error_recognized_as_stale_connection_keeps_that_type():
    SocketException = type("SocketException", (Exception,), {})
    translated = query_runtime.translate_open_error(SocketException("connection failed"))
    assert isinstance(translated, StaleConnectionError)


# --- evaluate_dax_as_role ------------------------------------------------------------


def test_runs_query_as_role(fake_tom: FakeTomRuntime, captured: dict):
    result = query.evaluate_dax_as_role(QUERY, roles=["Gerente Governo"])

    assert captured["port"] == 51234
    assert captured["database_name"] == "Vendas"
    assert captured["roles"] == ["Gerente Governo"]
    assert result["rows"] == [{"Vendas": 52.5}]  # mesmo tratamento de colunas do evaluate_dax
    assert result["roles"] == ["Gerente Governo"]
    assert result["truncated"] is False


def test_forwards_max_rows(fake_tom: FakeTomRuntime, captured: dict):
    query.evaluate_dax_as_role(QUERY, roles=["Gerente Governo"], max_rows=10)
    assert captured["fake"].calls[0] == ("execute", {"dax_query": QUERY, "max_rows": 10})


def test_closes_the_connection(fake_tom: FakeTomRuntime, captured: dict):
    query.evaluate_dax_as_role(QUERY, roles=["Gerente Governo"])
    assert captured["fake"].calls[-1] == ("close", {})


def test_unknown_role_raises_before_connecting(fake_tom: FakeTomRuntime, captured: dict):
    with pytest.raises(RoleNotFoundError):
        query.evaluate_dax_as_role(QUERY, roles=["Fantasma"])
    assert "roles" not in captured  # nunca chegou a conectar


def test_requires_at_least_one_role(fake_tom: FakeTomRuntime, captured: dict):
    with pytest.raises(InvalidRlsSimulationError):
        query.evaluate_dax_as_role(QUERY, roles=[])


def test_rejects_role_name_with_comma_even_if_it_exists(fake_tom: FakeTomRuntime, captured: dict):
    # vírgula dividiria a lista de roles da conexão em dois
    fake_tom.create_role("Norte, Sul")
    with pytest.raises(InvalidRlsSimulationError):
        query.evaluate_dax_as_role(QUERY, roles=["Norte, Sul"])
    assert "roles" not in captured

