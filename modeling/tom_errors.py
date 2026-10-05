"""Tradução de exceções .NET (levantadas por pythonnet ao chamar
TOM/AMO) para a hierarquia de erros deste projeto (`errors.py`).

Python puro -- não importa `clr` nem tipos `Microsoft.AnalysisServices.*`
-- compara pelo NOME da exceção (`type(exc).__name__`) em vez de
importar o tipo .NET, no mesmo espírito de `_cardinality_from_tom` /
`_convert_value` em `tom_runtime.py`. Isso permite testar a lógica de
tradução inteira sem pythonnet instalado (`tests/test_tom_errors.py`
usa exceções Python renomeadas via `type(...)`, não .NET de verdade).

Os nomes de exceção abaixo (`OutOfSyncException`, `OperationException`,
`TomValidationException`, `CompatibilityViolationException`,
`TomException`, `AmoException`, `JsonSerializationException`,
`XmlSerializationException`, `TmdlSerializationException`) foram
CONFIRMADOS POR REFLEXÃO .NET contra as DLLs reais do TOM
(`Microsoft.AnalysisServices.Core.dll` / `.Tabular.dll`) nesta sessão.

O reconhecimento de "conexão morta" (`StaleConnectionError`), em
contraste, é MELHOR ESFORÇO NÃO CONFIRMADO: as exceções de conexão
morta vêm da camada XMLA/AdomdClient (não dos assemblies Core/Tabular
refletidos), então usamos um casamento por palavra-chave na mensagem e
no nome do tipo em vez de uma lista fechada. Se a primeira rodada ao
vivo contra um Desktop reiniciado não cair aqui, o nome real do tipo
.NET precisa ser registrado (logar `type(exc).__name__`) e adicionado à
lista -- ver README.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator

from errors import (
    ModelOperationFailedError,
    ModelOutOfSyncError,
    PowerBiMcpError,
    StaleConnectionError,
)

# Confirmados por reflexão .NET (ver docstring do módulo).
_OUT_OF_SYNC_TYPE_NAMES = {"OutOfSyncException"}

_OPERATION_FAILED_TYPE_NAMES = {
    "OperationException",
    "TomValidationException",
    "CompatibilityViolationException",
    "TomException",
    "AmoException",
    "JsonSerializationException",
    "XmlSerializationException",
    "TmdlSerializationException",
}

# Melhor esforço, não confirmado -- ver docstring do módulo.
_STALE_CONNECTION_TYPE_KEYWORDS = ("connectionexception", "socketexception", "xmlastream")
_STALE_CONNECTION_MESSAGE_KEYWORDS = (
    "is not connected",
    "connection was closed",
    "connection has been closed",
    "unable to connect",
    "connection failed",
    "the connection is broken",
)


def translate_dotnet_exception(
    type_name: str,
    message: str,
    *,
    operation: str,
    live_ports: tuple[int, ...] = (),
) -> PowerBiMcpError | None:
    """Traduz uma exceção .NET (pelo nome do tipo e mensagem) pra um
    `PowerBiMcpError` com mensagem acionável, ou devolve `None` se o
    tipo não for um dos reconhecidos -- nesse caso quem chamou deve
    deixar a exceção original propagar sem mascarar (pode ser um bug
    nosso, não do motor)."""
    lowered_type = type_name.lower()
    lowered_message = message.lower()

    if type_name in _OUT_OF_SYNC_TYPE_NAMES:
        return ModelOutOfSyncError(operation=operation, original_message=message)

    if any(kw in lowered_type for kw in _STALE_CONNECTION_TYPE_KEYWORDS) or any(
        kw in lowered_message for kw in _STALE_CONNECTION_MESSAGE_KEYWORDS
    ):
        return StaleConnectionError(original_message=message, live_ports=live_ports)

    if type_name in _OPERATION_FAILED_TYPE_NAMES:
        return ModelOperationFailedError(operation=operation, original_message=message)

    return None


@contextmanager
def wrap_dotnet_errors(
    operation: str, live_ports_provider: Callable[[], tuple[int, ...]] | None = None
) -> Iterator[None]:
    """Context manager usado ao redor de chamadas TOM que podem lançar
    exceções .NET cruas (SaveChanges, RequestRefresh, Connect) --
    traduz para PowerBiMcpError preservando a mensagem original do
    motor. Erros já nossos (PowerBiMcpError) e exceções não reconhecidas
    (ex.: StopIteration de um `next()` sem match, ou um bug Python
    nosso) atravessam sem alteração -- nunca mascara o que não sabemos
    traduzir."""
    try:
        yield
    except PowerBiMcpError:
        raise
    except Exception as exc:  # exceções .NET chegam como Exception via pythonnet
        live_ports = live_ports_provider() if live_ports_provider else ()
        translated = translate_dotnet_exception(
            type(exc).__name__, str(exc), operation=operation, live_ports=live_ports
        )
        if translated is not None:
            raise translated from exc
        raise
