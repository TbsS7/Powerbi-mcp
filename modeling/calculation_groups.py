"""Calculation groups: itens de cálculo reaproveitáveis que se aplicam a
QUALQUER medida explícita do visual via `SELECTEDMEASURE()` -- em vez de
criar "Total Vendas YTD", "Total Custo YTD", ... uma medida por
combinação, um item "YTD" serve pra todas.

Fontes (regra do projeto -- nada inventado):
- Doc oficial "Calculation groups in Analysis Services tabular models"
  (learn.microsoft.com) -- traz o TMSL/TMDL completo: tabela com
  `calculationGroup` (precedence + calculationItems), coluna de texto
  `sourceColumn: "Name"` ordenada por uma coluna oculta int64
  `sourceColumn: "Ordinal"`, partição `source.type: calculationGroup`;
  e os exemplos de inteligência de tempo com `SELECTEDMEASURE()`.
- Reflexão .NET das DLLs do TOM: todos os tipos/propriedades/enums
  usados em `_PythonnetTomRuntime` (ver o bloco "calculation groups" lá).
- Doc "Create calculation groups in Power BI": criar um grupo exige
  `DiscourageImplicitMeasures = true` no modelo INTEIRO. Por decisão do
  usuário, isso só acontece com opt-in explícito
  (`allow_discourage_implicit_measures=True`) -- ver
  ImplicitMeasuresMustBeDiscouragedError.

A comparação com um grupo criado pela UI do Desktop (técnica que
resolveu field parameters) foi pulada de propósito, com o OK do usuário,
porque a doc oficial desta vez traz a estrutura inteira e ela bate 1:1
com a reflexão -- fica como plano B se o teste ao vivo falhar.

CONFIRMADO AO VIVO (2026-09-24, ver README "Validação real"): com o
refresh_table logo depois do save, a tabela já aparece preenchida
(itens na ordem do Ordinal) e utilizável numa matriz; e
`format_string_expression` é mesmo uma expressão DAX -- a máscara vai
entre aspas (`'"0.0%"'`): YoY % saiu como 249,5% na matriz, e o TMDL
salvo pelo próprio Desktop gravou `formatStringDefinition = "0.0%"`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from errors import (
    CalculationGroupNotFoundError,
    CalculationItemAlreadyExistsError,
    CalculationItemNotFoundError,
    ImplicitMeasuresMustBeDiscouragedError,
    InvalidCalculationGroupError,
    TableAlreadyExistsError,
)
from modeling import connection, time_intelligence
from modeling.metadata import CalculationGroupInfo, CalculationItemInfo, get_model_metadata

_PERCENT_FORMAT_EXPRESSION = '"0.0%"'


def create_calculation_group(
    table_name: str,
    items: list[dict[str, Any]],
    column_name: str | None = None,
    precedence: int = 0,
    allow_discourage_implicit_measures: bool = False,
    save: bool = True,
) -> dict[str, Any]:
    """Cria um calculation group `table_name` com `items` (cada um
    `{"name", "expression", "format_string_expression"?}`), na ordem
    dada (vira o `Ordinal` 0, 1, 2, ...). `column_name` é a coluna que
    se arrasta pra slicer/matriz (padrão: o próprio `table_name`).

    Raises:
        InvalidCalculationGroupError: sem itens, item sem nome/expressão,
            nome repetido.
        TableAlreadyExistsError: já existe tabela com esse nome.
        ImplicitMeasuresMustBeDiscouragedError: o modelo ainda permite
            medidas implícitas e `allow_discourage_implicit_measures` não
            veio True.
    """
    calculation_items = _normalize_items(items)
    runtime = connection.get_active_runtime()

    if get_model_metadata().find_table(table_name) is not None:
        raise TableAlreadyExistsError(table_name)

    enabled_now = False
    if not runtime.get_discourage_implicit_measures():
        if not allow_discourage_implicit_measures:
            raise ImplicitMeasuresMustBeDiscouragedError()
        runtime.set_discourage_implicit_measures(True)
        enabled_now = True

    group = runtime.create_calculation_group(
        table_name=table_name,
        column_name=column_name or table_name,
        precedence=precedence,
        items=calculation_items,
    )
    refreshed, refresh_error = _save_and_refresh(runtime, table_name, save)

    result = _group_to_dict(group)
    result.update(
        discourage_implicit_measures_enabled_now=enabled_now,
        refreshed=refreshed,
        refresh_error=refresh_error,
    )
    return result


def add_calculation_item(
    table_name: str,
    item_name: str,
    expression: str,
    format_string_expression: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Adiciona um item ao fim de um calculation group existente."""
    runtime = connection.get_active_runtime()
    group = _find_group(runtime, table_name)
    if any(i.name == item_name for i in group.items):
        raise CalculationItemAlreadyExistsError(table_name, item_name)
    [item] = _normalize_items(
        [{"name": item_name, "expression": expression, "format_string_expression": format_string_expression}]
    )
    ordinal = max((i.ordinal for i in group.items), default=-1) + 1
    item = CalculationItemInfo(
        name=item.name, expression=item.expression, ordinal=ordinal,
        format_string_expression=item.format_string_expression,
    )
    runtime.add_calculation_item(table_name=table_name, item=item)
    refreshed, refresh_error = _save_and_refresh(runtime, table_name, save)
    return {
        "table_name": table_name, "item_name": item_name, "ordinal": ordinal,
        "refreshed": refreshed, "refresh_error": refresh_error,
    }


def delete_calculation_item(table_name: str, item_name: str, save: bool = True) -> dict[str, Any]:
    """Remove um item de um calculation group (pra remover o grupo
    inteiro, use delete_table)."""
    runtime = connection.get_active_runtime()
    group = _find_group(runtime, table_name)
    if not any(i.name == item_name for i in group.items):
        raise CalculationItemNotFoundError(table_name, item_name, [i.name for i in group.items])
    runtime.delete_calculation_item(table_name=table_name, item_name=item_name)
    refreshed, refresh_error = _save_and_refresh(runtime, table_name, save)
    return {
        "table_name": table_name, "item_name": item_name, "deleted": True,
        "refreshed": refreshed, "refresh_error": refresh_error,
    }


def list_calculation_groups() -> list[dict[str, Any]]:
    runtime = connection.get_active_runtime()
    return [_group_to_dict(g) for g in runtime.list_calculation_groups()]


def create_time_intelligence_calculation_group(
    table_name: str,
    date_table: str,
    date_column: str,
    variants: list[str],
    column_name: str | None = None,
    precedence: int = 0,
    include_current: bool = True,
    allow_discourage_implicit_measures: bool = False,
    save: bool = True,
) -> dict[str, Any]:
    """Calculation group de inteligência de tempo: um item por variante
    (mesmas de create_time_intelligence_measures -- YTD, QTD, MTD, PY,
    PM, YoY, MoM -- e os MESMOS templates DAX, com `SELECTEDMEASURE()` no
    lugar da medida base), mais um item "Atual" (`SELECTEDMEASURE()`) no
    começo se `include_current`. Variantes percentuais (YoY/MoM) ganham
    format string de percentual; as outras herdam o formato da medida.

    Mesmo cuidado de create_time_intelligence_measures: o visual precisa
    agrupar/filtrar por coluna da PRÓPRIA `date_table` (relacionamento de
    mão única -- ver README).
    """
    time_intelligence.validate_date_column(get_model_metadata(), date_table, date_column)
    time_intelligence.validate_variants(variants)

    items: list[dict[str, Any]] = []
    if include_current:
        items.append({"name": "Atual", "expression": "SELECTEDMEASURE()"})
    for variant in variants:
        items.append(
            {
                "name": time_intelligence.variant_label(variant),
                "expression": time_intelligence.build_time_intelligence_calculation_item_dax(
                    date_table, date_column, variant
                ),
                "format_string_expression": (
                    _PERCENT_FORMAT_EXPRESSION if time_intelligence.is_percentage_variant(variant) else None
                ),
            }
        )

    return create_calculation_group(
        table_name=table_name,
        items=items,
        column_name=column_name,
        precedence=precedence,
        allow_discourage_implicit_measures=allow_discourage_implicit_measures,
        save=save,
    )


# --- internos ---------------------------------------------------------------


def _normalize_items(items: list[dict[str, Any]]) -> tuple[CalculationItemInfo, ...]:
    if not items:
        raise InvalidCalculationGroupError("Um calculation group precisa de pelo menos um item.")
    normalized = []
    seen: set[str] = set()
    for ordinal, raw in enumerate(items):
        name = (raw.get("name") or "").strip()
        expression = (raw.get("expression") or "").strip()
        if not name or not expression:
            raise InvalidCalculationGroupError(
                f"Item na posição {ordinal} precisa de 'name' e 'expression' não vazios."
            )
        if name in seen:
            raise InvalidCalculationGroupError(f"Nome de item repetido: '{name}'.")
        seen.add(name)
        normalized.append(
            CalculationItemInfo(
                name=name,
                expression=expression,
                ordinal=ordinal,
                format_string_expression=raw.get("format_string_expression") or None,
            )
        )
    return tuple(normalized)


def _find_group(runtime: Any, table_name: str) -> CalculationGroupInfo:
    groups = runtime.list_calculation_groups()
    group = next((g for g in groups if g.table_name == table_name), None)
    if group is None:
        raise CalculationGroupNotFoundError(table_name, [g.table_name for g in groups])
    return group


def _save_and_refresh(runtime: Any, table_name: str, save: bool) -> tuple[bool, str | None]:
    if not save:
        return False, None
    runtime.save_changes()
    try:
        runtime.refresh_table(table_name)
    except Exception as exc:  # noqa: BLE001 - melhor esforço, mesmo padrão de create_table
        return False, str(exc)
    return True, None


def _group_to_dict(group: CalculationGroupInfo) -> dict[str, Any]:
    return {
        "table_name": group.table_name,
        "column_name": group.column_name,
        "precedence": group.precedence,
        "items": [asdict(i) for i in group.items],
    }
