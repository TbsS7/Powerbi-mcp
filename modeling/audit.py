"""Auditoria de qualidade/documentação do modelo -- READ-ONLY: só aponta
problemas, nunca corrige nada (decisão do usuário, plano da Fase 2).

Exige conexão XMLA ativa: lê `TomRuntime.list_model_details` (descrição,
visibilidade, sort-by, propriedades estendidas -- campos que o leitor
TMDL offline não expõe), e um relatório parcial a partir do TMDL seria
enganoso.

Cada regra é uma função pura `(ModelDetails, relacionamentos) ->
list[AuditIssue]`, registrada em `_RULES`. Exclusões aplicadas a todas:
- tabelas de data automáticas do Power BI (`LocalDateTable_*`,
  `DateTableTemplate_*`) -- existem em quase todo modelo real e gerariam
  dezenas de falsos positivos (vistas ao vivo no modelo "financials");
- colunas de sistema `RowNumber-<guid>` (o runtime real já as pula por
  `ColumnType.RowNumber`; o filtro por nome aqui é defesa extra).

Severidades: "aviso" (provável problema real) e "sugestao" (boa prática
de documentação/organização; pode ser intencional).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

from errors import UnknownAuditRuleError
from modeling import connection
from modeling.metadata import ColumnDetail, ModelDetails, RelationshipInfo, TableDetail

_SYSTEM_TABLE_PREFIXES = ("LocalDateTable_", "DateTableTemplate_")
_SYSTEM_COLUMN_PREFIXES = ("RowNumber-",)
_KEY_COLUMN_PATTERN = re.compile(r"(Id|ID|Key|KEY|Codigo|Código|Cod)$")
_FIELD_PARAMETER_PROPERTY = "ParameterMetadata"

AVISO = "aviso"
SUGESTAO = "sugestao"


@dataclass(frozen=True)
class AuditIssue:
    code: str
    severity: str
    object_kind: str  # "tabela", "coluna", "medida"
    object_ref: str  # "Tabela" ou "Tabela[Coluna/Medida]"
    message: str


def audit_model(rules: list[str] | None = None) -> dict[str, Any]:
    """Roda as regras de auditoria (todas, ou só as de `rules`) contra o
    modelo conectado e devolve os achados -- sem escrever nada.

    Raises:
        DesktopNotFoundError: sem conexão ativa (connect_to_desktop).
        UnknownAuditRuleError: algum código em `rules` não existe.
    """
    selected = list(_RULES) if rules is None else list(rules)
    for code in selected:
        if code not in _RULES:
            raise UnknownAuditRuleError(code, list(_RULES))

    runtime = connection.get_active_runtime()
    details = _without_system_objects(runtime.list_model_details())
    relationships = tuple(runtime.list_relationships())

    issues: list[AuditIssue] = []
    for code in selected:
        issues.extend(_RULES[code](details, relationships))
    issues.sort(key=lambda i: (0 if i.severity == AVISO else 1, i.code, i.object_ref))

    return {
        "issues": [asdict(i) for i in issues],
        "summary": {
            AVISO: sum(1 for i in issues if i.severity == AVISO),
            SUGESTAO: sum(1 for i in issues if i.severity == SUGESTAO),
        },
        "total": len(issues),
        "rules_run": selected,
    }


# --- regras -----------------------------------------------------------------


def _rule_measure_without_format_string(details: ModelDetails, _rels) -> list[AuditIssue]:
    return [
        AuditIssue(
            "MEDIDA_SEM_FORMAT_STRING", AVISO, "medida", f"{m.table_name}[{m.name}]",
            f"A medida '{m.name}' não tem format string -- o valor aparece sem "
            "formatação (casas decimais, separador de milhar, %) nos visuais.",
        )
        for m in details.measures
        if not m.format_string
    ]


def _rule_measure_without_description(details: ModelDetails, _rels) -> list[AuditIssue]:
    return [
        AuditIssue(
            "MEDIDA_SEM_DESCRICAO", SUGESTAO, "medida", f"{m.table_name}[{m.name}]",
            f"A medida '{m.name}' não tem descrição (aparece como tooltip no "
            "painel de Campos).",
        )
        for m in details.measures
        if not m.description
    ]


def _rule_table_without_description(details: ModelDetails, _rels) -> list[AuditIssue]:
    return [
        AuditIssue(
            "TABELA_SEM_DESCRICAO", SUGESTAO, "tabela", t.name,
            f"A tabela '{t.name}' não tem descrição.",
        )
        for t in details.tables
        if not t.description
    ]


def _rule_disconnected_table(details: ModelDetails, rels: tuple[RelationshipInfo, ...]) -> list[AuditIssue]:
    connected: set[str] = set()
    for r in rels:
        if _is_system_table(r.from_table) or _is_system_table(r.to_table):
            continue  # relacionamento com tabela de data automática não conecta ao modelo
        connected.update((r.from_table, r.to_table))
    return [
        AuditIssue(
            "TABELA_DESCONECTADA", SUGESTAO, "tabela", t.name,
            f"A tabela '{t.name}' não se relaciona com nenhuma outra tabela do "
            "modelo (fora as tabelas de data automáticas). Tabelas de "
            "parâmetro/medidas costumam ser assim de propósito; tabela de "
            "fato ou dimensão assim provavelmente está faltando relacionamento.",
        )
        for t in details.tables
        if t.name not in connected
    ]


def _rule_orphan_key_column(details: ModelDetails, rels: tuple[RelationshipInfo, ...]) -> list[AuditIssue]:
    in_relationship = _relationship_columns(rels)
    return [
        AuditIssue(
            "COLUNA_CHAVE_ORFA", AVISO, "coluna", f"{t.name}[{c.name}]",
            f"A coluna '{t.name}[{c.name}]' tem nome de chave mas não participa "
            "de nenhum relacionamento -- provavelmente falta ligar essa tabela "
            "a outra.",
        )
        for t in details.tables
        for c in t.columns
        if _KEY_COLUMN_PATTERN.search(c.name) and (t.name, c.name) not in in_relationship
    ]


def _rule_unused_hidden_column(details: ModelDetails, rels: tuple[RelationshipInfo, ...]) -> list[AuditIssue]:
    in_relationship = _relationship_columns(rels)
    measure_text = "\n".join(m.dax_expression or "" for m in details.measures)
    issues = []
    for t in details.tables:
        sort_targets = {c.sort_by_column for c in t.columns if c.sort_by_column}
        for c in t.columns:
            if not c.is_hidden:
                continue
            if (
                (t.name, c.name) in in_relationship
                or c.name in sort_targets
                or _FIELD_PARAMETER_PROPERTY in c.extended_properties
                or f"[{c.name}]" in measure_text
            ):
                continue
            issues.append(
                AuditIssue(
                    "COLUNA_OCULTA_SEM_USO", SUGESTAO, "coluna", f"{t.name}[{c.name}]",
                    f"A coluna '{t.name}[{c.name}]' está oculta e não aparece em "
                    "relacionamento, ordenação (sort-by), field parameter nem no "
                    "texto de nenhuma medida -- talvez possa ser removida (confira "
                    "antes colunas calculadas e visuais que ainda a usem).",
                )
            )
    return issues


_RULES: dict[str, Callable[[ModelDetails, tuple[RelationshipInfo, ...]], list[AuditIssue]]] = {
    "MEDIDA_SEM_FORMAT_STRING": _rule_measure_without_format_string,
    "COLUNA_CHAVE_ORFA": _rule_orphan_key_column,
    "MEDIDA_SEM_DESCRICAO": _rule_measure_without_description,
    "TABELA_SEM_DESCRICAO": _rule_table_without_description,
    "TABELA_DESCONECTADA": _rule_disconnected_table,
    "COLUNA_OCULTA_SEM_USO": _rule_unused_hidden_column,
}


# --- internos ---------------------------------------------------------------


def _is_system_table(name: str) -> bool:
    return name.startswith(_SYSTEM_TABLE_PREFIXES)


def _is_system_column(column: ColumnDetail) -> bool:
    return column.name.startswith(_SYSTEM_COLUMN_PREFIXES)


def _without_system_objects(details: ModelDetails) -> ModelDetails:
    tables = tuple(
        TableDetail(
            name=t.name,
            description=t.description,
            is_hidden=t.is_hidden,
            columns=tuple(c for c in t.columns if not _is_system_column(c)),
        )
        for t in details.tables
        if not _is_system_table(t.name)
    )
    measures = tuple(m for m in details.measures if not _is_system_table(m.table_name))
    return ModelDetails(tables=tables, measures=measures)


def _relationship_columns(rels: tuple[RelationshipInfo, ...]) -> set[tuple[str, str]]:
    columns: set[tuple[str, str]] = set()
    for r in rels:
        columns.add((r.from_table, r.from_column))
        columns.add((r.to_table, r.to_column))
    return columns
