"""Testes de modeling.tom_errors: tradução de exceções .NET (por nome
de tipo + mensagem, sem importar clr/tipos .NET de verdade -- ver
docstring do módulo) para a hierarquia de erros do projeto.

Simula exceções .NET com classes Python locais que têm o MESMO NOME de
tipo (`type(exc).__name__`) que as exceções reais confirmadas por
reflexão -- é exatamente o que translate_dotnet_exception compara,
então isso testa a lógica real sem precisar de pythonnet/Desktop.
"""

from __future__ import annotations

import pytest

from errors import (
    ModelOperationFailedError,
    ModelOutOfSyncError,
    PowerBiMcpError,
    StaleConnectionError,
)
from modeling.tom_errors import translate_dotnet_exception, wrap_dotnet_errors


# --- translate_dotnet_exception (função pura) --------------------------


def test_traduz_out_of_sync_exception():
    result = translate_dotnet_exception(
        "OutOfSyncException", "modelo mudou", operation="save_changes"
    )
    assert isinstance(result, ModelOutOfSyncError)
    assert "save_changes" in str(result)
    assert "modelo mudou" in str(result)


@pytest.mark.parametrize(
    "type_name",
    [
        "OperationException",
        "TomValidationException",
        "CompatibilityViolationException",
        "TomException",
        "AmoException",
    ],
)
def test_traduz_tipos_de_falha_de_operacao_confirmados_por_reflexao(type_name):
    result = translate_dotnet_exception(type_name, "M Engine error: token", operation="save_changes")
    assert isinstance(result, ModelOperationFailedError)
    assert "M Engine error: token" in str(result)
    assert "save_changes" in str(result)


def test_traduz_por_palavra_chave_de_mensagem_de_conexao():
    result = translate_dotnet_exception(
        "GenericException", "The connection was closed by the server.", operation="refresh_table"
    )
    assert isinstance(result, StaleConnectionError)


def test_traduz_por_nome_de_tipo_de_conexao():
    result = translate_dotnet_exception("XmlaStreamException", "erro", operation="refresh_table")
    assert isinstance(result, StaleConnectionError)


def test_stale_connection_error_sugere_porta_viva_quando_fornecida():
    result = translate_dotnet_exception(
        "SocketException", "connection failed", operation="save_changes", live_ports=(52431,)
    )
    assert isinstance(result, StaleConnectionError)
    assert "52431" in str(result)
    assert "connect_to_desktop" in str(result)


def test_stale_connection_error_sem_porta_viva_nao_inventa_porta():
    result = translate_dotnet_exception(
        "SocketException", "connection failed", operation="save_changes"
    )
    assert isinstance(result, StaleConnectionError)
    assert result.live_ports == ()


def test_tipo_desconhecido_devolve_none():
    result = translate_dotnet_exception("KeyError", "algo python nosso", operation="save_changes")
    assert result is None


# --- wrap_dotnet_errors (context manager) -------------------------------


def test_wrap_deixa_power_bi_mcp_error_passar_sem_alteracao():
    original = ModelOutOfSyncError(operation="x", original_message="y")
    with pytest.raises(ModelOutOfSyncError) as exc_info:
        with wrap_dotnet_errors("save_changes"):
            raise original
    assert exc_info.value is original


def test_wrap_traduz_excecao_reconhecida():
    class OperationException(Exception):
        pass

    with pytest.raises(ModelOperationFailedError) as exc_info:
        with wrap_dotnet_errors("save_changes"):
            raise OperationException("Failed to save modifications to the server.")
    assert "Failed to save modifications" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, OperationException)


def test_wrap_deixa_excecao_nao_reconhecida_propagar_crua():
    with pytest.raises(StopIteration):
        with wrap_dotnet_errors("save_changes"):
            raise StopIteration()


def test_wrap_usa_live_ports_provider_so_quando_necessario():
    calls = []

    def provider():
        calls.append(1)
        return (52431,)

    with pytest.raises(PowerBiMcpError):
        with wrap_dotnet_errors("save_changes", provider):
            raise Exception("connection was closed")  # noqa: TRY002 - simula exceção .NET genérica

    assert calls == [1]


def test_wrap_nao_chama_live_ports_provider_no_caminho_feliz():
    calls = []

    def provider():
        calls.append(1)
        return (52431,)

    with wrap_dotnet_errors("save_changes", provider):
        pass

    assert calls == []
