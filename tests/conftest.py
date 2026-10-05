"""Fixtures compartilhadas.

modeling.connection guarda a conexão TOM ativa em estado de módulo (é a
sessão do servidor MCP, que naturalmente vive fora de qualquer chamada
de tool individual). Isso é exatamente o que queremos em produção, mas
em testes esse estado global vazaria de um teste para o outro se nada o
resetasse -- por isso este fixture autouse.
"""

from __future__ import annotations

import pytest

from modeling import connection


@pytest.fixture(autouse=True)
def _reset_active_connection():
    connection.clear_active_runtime()
    yield
    connection.clear_active_runtime()
