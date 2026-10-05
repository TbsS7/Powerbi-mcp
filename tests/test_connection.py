"""Testes de modeling.connection: descoberta + conexão TOM, e o estado
de sessão (conexão ativa) que operations.py e metadata.py consomem.

tom_runtime.connect é sempre substituído por um factory fake nestes
testes -- nenhum deles toca .NET.
"""

from __future__ import annotations

import pytest

from errors import DesktopNotFoundError, MultipleDesktopInstancesError
from modeling import connection, tom_runtime
from modeling.discovery import DesktopInstance
from tests.fakes.fake_tom import FakeTomRuntime


@pytest.fixture(autouse=True)
def all_ports_listening(monkeypatch):
    """Por padrão toda porta "responde" -- os testes abaixo usam portas
    inventadas; os que testam instância fechada sobrescrevem isto."""
    monkeypatch.setattr(connection.discovery, "is_port_listening", lambda port: True)


def test_get_active_runtime_raises_when_nothing_connected():
    with pytest.raises(Exception):
        connection.get_active_runtime()


def test_get_active_runtime_returns_none_when_not_required_and_nothing_connected():
    assert connection.get_active_runtime(required=False) is None


def test_connect_to_desktop_with_explicit_port_bypasses_discovery(monkeypatch):
    fake = FakeTomRuntime(database_name="Vendas", port=12345, compatibility_level=1601)

    def fake_connect(port: int, database_name: str | None = None):
        assert port == 12345
        assert database_name is None
        return fake

    monkeypatch.setattr(tom_runtime, "connect", fake_connect)

    result = connection.connect_to_desktop(port=12345)

    assert result == {
        "port": 12345,
        "database_name": "Vendas",
        "compatibility_level": 1601,
    }
    assert connection.get_active_runtime() is fake


def test_connect_to_desktop_raises_when_no_instance_found(monkeypatch):
    monkeypatch.setattr(connection.discovery, "find_desktop_instances", lambda: [])

    with pytest.raises(DesktopNotFoundError):
        connection.connect_to_desktop()


def test_connect_to_desktop_auto_connects_single_instance(monkeypatch):
    monkeypatch.setattr(
        connection.discovery,
        "find_desktop_instances",
        lambda: [DesktopInstance(port=51500, workspace_name="AnalysisServicesWorkspace_X")],
    )
    fake = FakeTomRuntime(database_name="Vendas", port=51500, compatibility_level=1600)
    monkeypatch.setattr(tom_runtime, "connect", lambda port, database_name=None: fake)

    result = connection.connect_to_desktop()

    assert result["port"] == 51500
    assert result["database_name"] == "Vendas"
    assert connection.get_active_runtime() is fake


def test_connect_to_desktop_raises_on_multiple_instances_without_disambiguation(monkeypatch):
    monkeypatch.setattr(
        connection.discovery,
        "find_desktop_instances",
        lambda: [
            DesktopInstance(port=51500, workspace_name="AnalysisServicesWorkspace_A"),
            DesktopInstance(port=51600, workspace_name="AnalysisServicesWorkspace_B"),
        ],
    )

    with pytest.raises(MultipleDesktopInstancesError) as exc_info:
        connection.connect_to_desktop()

    ports = [i["port"] for i in exc_info.value.instances]
    assert ports == [51500, 51600]
    assert connection.get_active_runtime(required=False) is None


def test_connect_to_desktop_disambiguates_multiple_instances_by_database_name(monkeypatch):
    monkeypatch.setattr(
        connection.discovery,
        "find_desktop_instances",
        lambda: [
            DesktopInstance(port=51500, workspace_name="AnalysisServicesWorkspace_A"),
            DesktopInstance(port=51600, workspace_name="AnalysisServicesWorkspace_B"),
        ],
    )
    fake_a = FakeTomRuntime(database_name="Marketing", port=51500)
    fake_b = FakeTomRuntime(database_name="Vendas", port=51600)

    def fake_connect(port: int, database_name: str | None = None):
        return {51500: fake_a, 51600: fake_b}[port]

    monkeypatch.setattr(tom_runtime, "connect", fake_connect)

    result = connection.connect_to_desktop(database_name="Vendas")

    assert result["port"] == 51600
    assert connection.get_active_runtime() is fake_b


def test_connect_to_desktop_raises_when_database_name_matches_none(monkeypatch):
    monkeypatch.setattr(
        connection.discovery,
        "find_desktop_instances",
        lambda: [
            DesktopInstance(port=51500, workspace_name="AnalysisServicesWorkspace_A"),
            DesktopInstance(port=51600, workspace_name="AnalysisServicesWorkspace_B"),
        ],
    )
    fake_a = FakeTomRuntime(database_name="Marketing", port=51500)
    fake_b = FakeTomRuntime(database_name="Financeiro", port=51600)
    monkeypatch.setattr(
        tom_runtime, "connect", lambda port, database_name=None: {51500: fake_a, 51600: fake_b}[port]
    )

    with pytest.raises(DesktopNotFoundError):
        connection.connect_to_desktop(database_name="Vendas")

    assert connection.get_active_runtime(required=False) is None


def test_set_and_clear_active_runtime_roundtrip():
    fake = FakeTomRuntime()
    connection.set_active_runtime(fake)
    assert connection.get_active_runtime() is fake

    connection.clear_active_runtime()
    assert connection.get_active_runtime(required=False) is None


def test_set_active_runtime_disconnects_previous_runtime_when_replaced():
    """Achado testando contra um Power BI Desktop real: Server.Connect()
    nunca era desconectado -- chamar connect_to_desktop duas vezes
    abandonava a conexão .NET anterior aberta."""
    first = FakeTomRuntime(database_name="Primeira")
    second = FakeTomRuntime(database_name="Segunda")

    connection.set_active_runtime(first)
    connection.set_active_runtime(second)

    assert ("disconnect", {}) in first.calls
    assert ("disconnect", {}) not in second.calls
    assert connection.get_active_runtime() is second


def test_set_active_runtime_first_call_does_not_disconnect_anything():
    fake = FakeTomRuntime()
    connection.set_active_runtime(fake)
    assert ("disconnect", {}) not in fake.calls


def test_clear_active_runtime_disconnects_current_runtime():
    fake = FakeTomRuntime()
    connection.set_active_runtime(fake)

    connection.clear_active_runtime()

    assert ("disconnect", {}) in fake.calls


# --- instâncias já fechadas (achado no uso: pasta de workspace fica pra trás) ------


def _three_instances(monkeypatch):
    monkeypatch.setattr(
        connection.discovery,
        "find_desktop_instances",
        lambda: [
            DesktopInstance(port=51005, workspace_name="AnalysisServicesWorkspace_Velha1"),
            DesktopInstance(port=52698, workspace_name="AnalysisServicesWorkspace_Viva"),
            DesktopInstance(port=64771, workspace_name="AnalysisServicesWorkspace_Velha2"),
        ],
    )


def test_closed_instances_are_ignored_and_the_live_one_connects(monkeypatch):
    _three_instances(monkeypatch)
    monkeypatch.setattr(connection.discovery, "is_port_listening", lambda port: port == 52698)
    connected_ports = []

    def fake_connect(port, database_name=None):
        connected_ports.append(port)
        return FakeTomRuntime(database_name="Viva", port=port)

    monkeypatch.setattr(tom_runtime, "connect", fake_connect)

    result = connection.connect_to_desktop()

    assert result["port"] == 52698
    assert connected_ports == [52698]


def test_multiple_live_instances_still_ask_which_one(monkeypatch):
    _three_instances(monkeypatch)
    monkeypatch.setattr(connection.discovery, "is_port_listening", lambda port: port != 51005)

    with pytest.raises(MultipleDesktopInstancesError) as exc_info:
        connection.connect_to_desktop()

    assert [i["port"] for i in exc_info.value.instances] == [52698, 64771]


def test_only_closed_instances_explains_leftover_folders(monkeypatch):
    _three_instances(monkeypatch)
    monkeypatch.setattr(connection.discovery, "is_port_listening", lambda port: False)

    with pytest.raises(DesktopNotFoundError, match="fechad"):
        connection.connect_to_desktop()
