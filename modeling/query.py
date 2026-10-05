"""Execução de consultas DAX contra o modelo tabular ativo.

Diferente de modeling/operations.py (que só grava estrutura via TOM),
evaluate_dax lê valores reais executando a consulta num motor de
consulta -- ADOMD.NET, uma biblioteca .NET inteiramente separada do TOM
(Microsoft.AnalysisServices.AdomdClient, não .Tabular). Ver
modeling/query_runtime.py para a fronteira com ela.

Reaproveita a conexão TOM ativa (connection.get_active_runtime()) só
para saber a porta e o nome do banco -- TOM nunca executa a consulta.
Uma conexão ADOMD nova é aberta, usada e fechada a cada chamada: não há
um "connect" separado para consultas, porque connect_to_desktop já fez
a descoberta que importa.

`query_runtime` é referenciado por módulo (não `from x import y`) de
propósito, para que os testes substituam `query.query_runtime.connect`
sem tocar .NET -- mesmo padrão de modeling/connection.py com
tom_runtime.
"""

from __future__ import annotations

import re
from typing import Any

from errors import InvalidRlsSimulationError, RoleNotFoundError
from modeling import connection, query_runtime

_BRACKET_ONLY_NAME_RE = re.compile(r"^\[(.+)\]$")


def evaluate_dax(dax_query: str, max_rows: int | None = None) -> dict[str, Any]:
    """Executa `dax_query` contra o modelo da conexão ativa e devolve
    as linhas do resultado.

    Args:
        dax_query: consulta DAX completa (EVALUATE ou DEFINE ...
            EVALUATE) -- passada como texto puro pro motor de consulta,
            então uma medida ad-hoc via `DEFINE MEASURE Tabela[Nome] =
            <expressão> EVALUATE ...` funciona sem suporte especial
            nenhum deste lado.
        max_rows: se informado, para de ler depois dessa quantidade de
            linhas em vez de trazer o resultado inteiro -- proteção
            contra resultado muito grande. `None` (padrão) traz tudo,
            igual ao comportamento anterior.

    Raises:
        DesktopNotFoundError: nenhuma conexão ativa (propagado por
            connection.get_active_runtime) -- chame connect_to_desktop
            primeiro.
        AdomdDllNotFoundError: as DLLs do ADOMD.NET não foram
            encontradas (propagado por query_runtime.connect).
        DaxQueryError: a consulta falhou ao executar (sintaxe
            inválida, referência inexistente etc.).
    """
    runtime = connection.get_active_runtime()
    query_conn = query_runtime.connect(port=runtime.port, database_name=runtime.database_name)
    try:
        rows, truncated = query_conn.execute(dax_query, max_rows=max_rows)
    finally:
        query_conn.close()
    rows = [_normalize_row(row) for row in rows]
    return {"rows": rows, "row_count": len(rows), "truncated": truncated}


def evaluate_dax_as_role(
    dax_query: str,
    roles: list[str],
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Simulação de RLS: executa `dax_query` com as permissões de
    `roles` (o equivalente ao "Exibir como" do Desktop) e devolve o que
    esses roles enxergariam. Só leitura -- não muda nada no modelo.

    Usa a propriedade de conexão `Roles` numa conexão ADOMD própria
    desta chamada -- ver query_runtime.build_connection_string pra
    fonte oficial. CONFIRMADO AO VIVO (2026-09-26): como um role com
    filtro Segment = "Government", o total bateu centavo a centavo com o
    mesmo cálculo filtrado à mão, e só o segmento permitido apareceu.
    Simular um usuário específico (RLS dinâmico, USERPRINCIPALNAME())
    NÃO é suportado: o Desktop local não resolve EffectiveUserName sem
    domínio corporativo -- use "Exibir como > Outro usuário" no Desktop.

    Raises:
        DesktopNotFoundError: nenhuma conexão ativa.
        InvalidRlsSimulationError: nenhum role, ou nome de role com
            `;`, `"` ou `,`.
        RoleNotFoundError: algum role não existe no modelo.
        DaxQueryError: a consulta falhou.
    """
    if not roles:
        raise InvalidRlsSimulationError("Informe pelo menos um role em `roles`.")
    for role in roles:
        if any(ch in role for ch in ';",'):
            raise InvalidRlsSimulationError(
                f"O role {role!r} tem ';', '\"' ou ',' no nome -- não dá pra passar com "
                "segurança na conexão (a lista de roles é separada por vírgula)."
            )

    runtime = connection.get_active_runtime()
    known_roles = {r.name for r in runtime.list_roles()}
    for role in roles:
        if role not in known_roles:
            raise RoleNotFoundError(role)

    query_conn = query_runtime.connect(
        port=runtime.port,
        database_name=runtime.database_name,
        roles=list(roles),
    )
    try:
        rows, truncated = query_conn.execute(dax_query, max_rows=max_rows)
    finally:
        query_conn.close()

    rows = [_normalize_row(row) for row in rows]
    return {
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "roles": list(roles),
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Se `AdomdDataReader` devolver o nome de uma coluna só entre
    colchetes, sem tabela (`"[Nome]"`), normaliza pra `"Nome"`. Uma
    referência qualificada por tabela (`"Tabela[Coluna]"`) não bate
    nesse padrão e fica intacta -- já é um nome útil, e ambíguo demais
    pra normalizar sem a tabela.

    MELHOR ESFORÇO / não confirmado ao vivo: testamos ao vivo várias
    formas de consulta (table constructor, ROW com alias, medida ad-hoc
    via DEFINE MEASURE) e nenhuma produziu o formato `"[Nome]"` -- só
    `"Value"` ou o alias explícito. Ver README, seção "Validação real",
    nota sobre `evaluate_dax`. Fica como proteção defensiva."""
    return {_normalize_column_name(name): value for name, value in row.items()}


def _normalize_column_name(name: str) -> str:
    match = _BRACKET_ONLY_NAME_RE.match(name)
    return match.group(1) if match else name
