"""Descoberta e conexão com o endpoint XMLA local do Power BI Desktop, e
o estado de sessão (conexão TOM ativa) que operations.py e metadata.py
consomem.

connect_to_desktop chama `discovery.find_desktop_instances` para
localizar instâncias abertas e `tom_runtime.connect` para efetivamente
conectar -- ambos referenciados aqui por módulo (não por
`from x import y`) de propósito, para que os testes possam substituí-los
via `monkeypatch.setattr(connection.discovery, ...)` /
`monkeypatch.setattr(tom_runtime, ...)` sem tocar .NET.
"""

from __future__ import annotations

from typing import Any

from errors import DesktopNotFoundError, MultipleDesktopInstancesError, PowerBiMcpError
from modeling import discovery, tom_runtime
from modeling.tom_runtime import TomRuntime

_active_runtime: TomRuntime | None = None


def connect_to_desktop(
    port: int | None = None,
    database_name: str | None = None,
) -> dict[str, Any]:
    """Conecta a uma instância aberta do Power BI Desktop e a marca como
    a conexão ativa da sessão.

    Se `port` for informado, conecta direto a ele (sem consultar a
    descoberta de instâncias). Caso contrário, descobre as instâncias
    abertas: se houver exatamente uma, conecta a ela; se houver mais de
    uma e `database_name` também for informado, conecta a cada uma até
    achar a que tem esse nome; se houver mais de uma e `database_name`
    não for informado, falha listando as instâncias encontradas.

    Raises:
        DesktopNotFoundError: nenhuma instância encontrada, ou nenhuma
            corresponde ao `database_name` pedido.
        MultipleDesktopInstancesError: mais de uma instância aberta e
            nenhum critério para escolher qual usar.
        TomDllNotFoundError: (propagado por tom_runtime.connect) as DLLs
            do TOM não foram encontradas.
    """
    if port is not None:
        runtime = tom_runtime.connect(port=port, database_name=database_name)
    else:
        runtime = _discover_and_connect(database_name)

    set_active_runtime(runtime)
    return {
        "port": runtime.port,
        "database_name": runtime.database_name,
        "compatibility_level": runtime.compatibility_level,
    }


def _discover_and_connect(database_name: str | None) -> TomRuntime:
    found = discovery.find_desktop_instances()
    # pasta de workspace de um Desktop já fechado fica pra trás -- só conta
    # instância cuja porta ainda responde (ver discovery.is_port_listening)
    instances = [i for i in found if discovery.is_port_listening(i.port)]
    if not instances:
        leftover = (
            f" (Achei {len(found)} pasta(s) de workspace, mas de instâncias já fechadas -- "
            "nenhuma porta respondeu.)"
            if found else ""
        )
        raise DesktopNotFoundError(
            "Nenhuma instância do Power BI Desktop foi encontrada aberta. "
            "Abra um relatório no Power BI Desktop e tente novamente, ou "
            "informe 'port' diretamente." + leftover
        )

    if len(instances) == 1:
        return tom_runtime.connect(port=instances[0].port, database_name=database_name)

    if database_name is None:
        raise MultipleDesktopInstancesError(
            instances=[{"port": i.port, "workspace_name": i.workspace_name} for i in instances]
        )

    checked_ports: list[int] = []
    for instance in instances:
        try:
            candidate = tom_runtime.connect(port=instance.port)
        except PowerBiMcpError:
            continue
        checked_ports.append(instance.port)
        if candidate.database_name == database_name:
            return candidate

    raise DesktopNotFoundError(
        f"Nenhuma das instâncias abertas do Power BI Desktop tem um banco "
        f"chamado '{database_name}'. Portas verificadas: {checked_ports}. "
        "Você pode informar 'port' diretamente."
    )


def set_active_runtime(runtime: TomRuntime) -> None:
    """Define a conexão TOM ativa da sessão. Usada internamente por
    connect_to_desktop e diretamente pelos testes para injetar um
    FakeTomRuntime sem passar por discovery/tom_runtime.connect.

    Se já havia uma conexão ativa diferente desta, ela é desconectada
    primeiro -- achado testando contra um Power BI Desktop real:
    Server.Connect() nunca era desfeito, então conectar de novo (ex.:
    chamar connect_to_desktop duas vezes) abandonava a conexão .NET
    anterior aberta."""
    global _active_runtime
    if _active_runtime is not None and _active_runtime is not runtime:
        _active_runtime.disconnect()
    _active_runtime = runtime


def clear_active_runtime() -> None:
    """Limpa a conexão ativa, desconectando-a primeiro se houver uma.
    Chamado entre testes (ver tests/conftest.py) para que o estado de um
    teste não vaze para o próximo, e é o único ponto de "desligar" a
    sessão hoje (não há uma tool disconnect_from_desktop)."""
    global _active_runtime
    if _active_runtime is not None:
        _active_runtime.disconnect()
    _active_runtime = None


def get_active_runtime(*, required: bool = True) -> TomRuntime | None:
    """Devolve a conexão TOM ativa da sessão.

    Args:
        required: se True (padrão) e não há conexão ativa, levanta
            DesktopNotFoundError. Se False, devolve None nesse caso --
            usado por list_model_metadata para decidir entre a fonte
            XMLA e a fonte TMDL sem forçar uma conexão.
    """
    if _active_runtime is None:
        if required:
            raise DesktopNotFoundError(
                "Nenhuma conexão ativa com o Power BI Desktop. Chame "
                "connect_to_desktop primeiro."
            )
        return None
    return _active_runtime
