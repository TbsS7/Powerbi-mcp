"""Operações de escrita no modelo tabular: criar tabela, medida e
relacionamento.

Cada função valida contra o estado atual do modelo (via a conexão TOM
ativa, obtida de connection.get_active_runtime) antes de chamar o
runtime, e por padrão chama runtime.save_changes() ao final -- assim o
efeito de uma chamada avulsa desta tool é imediato, sem depender de uma
chamada separada de "salvar".

O parâmetro `save`, quando False, pula esse save_changes() individual.
É para orchestrator.applier: ao aplicar um blueprint com várias
operações de modelagem, ele chama cada create_* com save=False e faz um
único runtime.save_changes() no final -- assim uma falha no meio do
blueprint não deixa parte das mudanças já commitadas no modelo
enquanto o resto falhou.
"""

from __future__ import annotations

from typing import Any

from errors import (
    ColumnAlreadyExistsError,
    ColumnAlreadyHiddenError,
    ColumnNotFoundError,
    ColumnNotHiddenError,
    HierarchyAlreadyExistsError,
    HierarchyNotFoundError,
    MeasureAlreadyExistsError,
    MeasureNotFoundError,
    RelationshipNotFoundError,
    RoleAlreadyExistsError,
    RoleNotFoundError,
    TableAlreadyExistsError,
    TableHasRelationshipsError,
    TableNotFoundError,
    TablePermissionAlreadyExistsError,
    TablePermissionNotFoundError,
)
from modeling import connection
from modeling.metadata import HierarchyInfo, MeasureInfo, RelationshipInfo, RoleInfo, TableInfo


def create_table(
    table_name: str,
    dax_expression: str,
    save: bool = True,
    refresh: bool = True,
) -> dict[str, Any]:
    """Cria uma tabela calculada (expressão DAX).

    NOTA (2026-09-23): este servidor só cria tabelas calculadas --
    suporte a tabela via Power Query (M) foi removido de propósito
    (decisão do usuário). A investigação do bug 1.4 do plano de
    robustez achou a causa raiz: o TOM/AMO não tem NENHUMA API pra
    auto-descobrir colunas a partir de uma fonte M (confirmado por
    reflexão .NET nos tipos Table/Partition/Model -- nenhum método de
    "detectar schema"; ao vivo, uma tabela M criada por este servidor
    só ganhava uma coluna de sistema `RowNumber-<guid>`, nunca as
    colunas reais da query). Essa descoberta de coluna é feita pelo
    motor Mashup do Query Editor do lado do Desktop, fora do alcance do
    TOM -- por isso, em vez de meio-resolver (exigir que o chamador
    declare as colunas manualmente), a funcionalidade de Power Query
    foi removida inteira: `update_power_query`/`read_power_query_expression`
    também saíram.

    Para tabela calculada (DAX), o refresh abaixo continua necessário e
    válido -- é o mesmo caso que `field_parameters.create_field_parameter`
    já documentava (`refresh_table` depois de `create_calculated_table`
    pra descobrir colunas `Value1`/`Value2`/... de um construtor de
    tupla, por exemplo).

    Args:
        refresh: se True (padrão) e `save` também for True, chama
            `refresh_table` depois de salvar e relê as colunas reais do
            modelo antes de devolver. Sem `save`, não há nada no
            servidor ainda pra processar -- refresh é pulado
            silenciosamente nesse caso (fica só `refreshed: False`).
            Passe `refresh=False` para manter o comportamento antigo
            (retorno imediato, sem round-trip extra) quando as colunas
            não importam pro chamador.

    O retorno ganha `refreshed` (bool) e `refresh_error` (str | None).
    Se o refresh falhar, a tabela **não é revertida** -- ela é o
    resultado pedido e já está no modelo; `refresh_error` deixa claro
    que as colunas no retorno podem estar incompletas/desatualizadas e
    o chamador pode tentar `refresh_table` de novo.
    """
    runtime = connection.get_active_runtime()
    _ensure_table_does_not_exist(runtime, table_name)

    table = runtime.create_calculated_table(table_name=table_name, dax_expression=dax_expression)

    refreshed = False
    refresh_error: str | None = None
    if save:
        runtime.save_changes()
        if refresh:
            try:
                runtime.refresh_table(table_name)
            except Exception as exc:  # noqa: BLE001 - melhor esforço, ver docstring
                refresh_error = str(exc)
            else:
                refreshed = True
                for reread in runtime.list_tables():
                    if reread.name == table_name:
                        table = reread
                        break

    result = _table_to_dict(table)
    result["refreshed"] = refreshed
    result["refresh_error"] = refresh_error
    return result


def create_measure(
    table_name: str,
    measure_name: str,
    dax_expression: str,
    format_string: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_table_exists(runtime, table_name)
    _ensure_measure_does_not_exist(runtime, measure_name)

    measure = runtime.create_measure(
        table_name=table_name,
        measure_name=measure_name,
        dax_expression=dax_expression,
        format_string=format_string,
    )

    if save:
        runtime.save_changes()
    return _measure_to_dict(measure)


def create_relationship(
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    cardinality: str = "many_to_one",
    cross_filter_direction: str = "single",
    save: bool = True,
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_column_exists(runtime, from_table, from_column)
    _ensure_column_exists(runtime, to_table, to_column)

    relationship = runtime.create_relationship(
        from_table=from_table,
        from_column=from_column,
        to_table=to_table,
        to_column=to_column,
        cardinality=cardinality,
        cross_filter_direction=cross_filter_direction,
    )

    if save:
        runtime.save_changes()
    return _relationship_to_dict(relationship)


def delete_measure(table_name: str, measure_name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_measure_exists(runtime, table_name, measure_name)

    runtime.delete_measure(table_name=table_name, measure_name=measure_name)

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "measure_name": measure_name, "deleted": True}


def update_measure(
    table_name: str,
    measure_name: str,
    dax_expression: str | None = None,
    format_string: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_measure_exists(runtime, table_name, measure_name)

    measure = runtime.update_measure(
        table_name=table_name,
        measure_name=measure_name,
        dax_expression=dax_expression,
        format_string=format_string,
    )

    if save:
        runtime.save_changes()
    return _measure_to_dict(measure)


def delete_relationship(
    from_table: str, from_column: str, to_table: str, to_column: str, save: bool = True
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_relationship_exists(runtime, from_table, from_column, to_table, to_column)

    runtime.delete_relationship(
        from_table=from_table, from_column=from_column, to_table=to_table, to_column=to_column
    )

    if save:
        runtime.save_changes()
    return {
        "from_table": from_table,
        "from_column": from_column,
        "to_table": to_table,
        "to_column": to_column,
        "deleted": True,
    }


def delete_table(table_name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_table_exists(runtime, table_name)
    _ensure_table_has_no_relationships(runtime, table_name)

    runtime.delete_table(table_name=table_name)

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "deleted": True}


def create_calculated_column(
    table_name: str,
    column_name: str,
    dax_expression: str,
    format_string: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_table_exists(runtime, table_name)
    _ensure_column_does_not_exist(runtime, table_name, column_name)

    column = runtime.create_calculated_column(
        table_name=table_name,
        column_name=column_name,
        dax_expression=dax_expression,
        format_string=format_string,
    )

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "column_name": column.name, "data_type": column.data_type}


def delete_column(table_name: str, column_name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_column_exists(runtime, table_name, column_name)

    runtime.delete_column(table_name=table_name, column_name=column_name)

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "column_name": column_name, "deleted": True}


def create_hierarchy(
    table_name: str, hierarchy_name: str, levels: list[str], save: bool = True
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_table_exists(runtime, table_name)
    for column_name in levels:
        _ensure_column_exists(runtime, table_name, column_name)
    _ensure_hierarchy_does_not_exist(runtime, table_name, hierarchy_name)

    hierarchy = runtime.create_hierarchy(
        table_name=table_name, hierarchy_name=hierarchy_name, levels=levels
    )

    if save:
        runtime.save_changes()
    return _hierarchy_to_dict(hierarchy)


def delete_hierarchy(table_name: str, hierarchy_name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_hierarchy_exists(runtime, table_name, hierarchy_name)

    runtime.delete_hierarchy(table_name=table_name, hierarchy_name=hierarchy_name)

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "hierarchy_name": hierarchy_name, "deleted": True}


def list_hierarchies() -> list[dict[str, Any]]:
    runtime = connection.get_active_runtime()
    return [_hierarchy_to_dict(h) for h in runtime.list_hierarchies()]


def create_role(role_name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_role_does_not_exist(runtime, role_name)

    role = runtime.create_role(role_name=role_name)

    if save:
        runtime.save_changes()
    return _role_to_dict(role)


def add_table_permission(
    role_name: str, table_name: str, filter_expression: str, save: bool = True
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_role_exists(runtime, role_name)
    _ensure_table_exists(runtime, table_name)
    _ensure_table_permission_does_not_exist(runtime, role_name, table_name)

    role = runtime.add_table_permission(
        role_name=role_name, table_name=table_name, filter_expression=filter_expression
    )

    if save:
        runtime.save_changes()
    return _role_to_dict(role)


def delete_role(role_name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_role_exists(runtime, role_name)

    runtime.delete_role(role_name=role_name)

    if save:
        runtime.save_changes()
    return {"role_name": role_name, "deleted": True}


def list_roles() -> list[dict[str, Any]]:
    runtime = connection.get_active_runtime()
    return [_role_to_dict(r) for r in runtime.list_roles()]


def hide_column(role_name: str, table_name: str, column_name: str, save: bool = True) -> dict[str, Any]:
    """Esconde uma coluna (dado e metadado) para membros de `role_name`
    -- segurança em nível de OBJETO (OLS), diferente do filtro de linha
    de add_table_permission (RLS)."""
    runtime = connection.get_active_runtime()
    _ensure_role_exists(runtime, role_name)
    _ensure_table_permission_exists(runtime, role_name, table_name)
    _ensure_column_exists(runtime, table_name, column_name)
    _ensure_column_not_hidden(runtime, role_name, table_name, column_name)

    role = runtime.hide_column(role_name=role_name, table_name=table_name, column_name=column_name)

    if save:
        runtime.save_changes()
    return _role_to_dict(role)


def unhide_column(role_name: str, table_name: str, column_name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_role_exists(runtime, role_name)
    _ensure_column_hidden(runtime, role_name, table_name, column_name)

    role = runtime.unhide_column(role_name=role_name, table_name=table_name, column_name=column_name)

    if save:
        runtime.save_changes()
    return _role_to_dict(role)


def refresh_table(table_name: str) -> dict[str, Any]:
    """Dispara uma nova leitura dos dados de `table_name` (via Power
    Query/DAX, dependendo do modo da tabela). Pode demorar dependendo
    do volume de dados -- não há timeout embutido; a chamada bloqueia
    até o refresh terminar (ou o Power BI Desktop reportar erro)."""
    runtime = connection.get_active_runtime()
    _ensure_table_exists(runtime, table_name)

    runtime.refresh_table(table_name=table_name)
    return {"table_name": table_name, "refreshed": True}


def refresh_model() -> dict[str, Any]:
    """Igual a refresh_table, mas para todas as tabelas do modelo de
    uma vez. Mesmo aviso de duração -- pode demorar bem mais que uma
    tabela isolada."""
    runtime = connection.get_active_runtime()
    table_names = [t.name for t in runtime.list_tables()]

    runtime.refresh_model()
    return {"table_names": table_names, "refreshed": True}


def set_table_description(table_name: str, description: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_table_exists(runtime, table_name)

    runtime.set_table_description(table_name=table_name, description=description)

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "description": description}


def set_column_metadata(
    table_name: str,
    column_name: str,
    description: str | None = None,
    display_folder: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_column_exists(runtime, table_name, column_name)

    runtime.set_column_metadata(
        table_name=table_name, column_name=column_name,
        description=description, display_folder=display_folder,
    )

    if save:
        runtime.save_changes()
    return {
        "table_name": table_name, "column_name": column_name,
        "description": description, "display_folder": display_folder,
    }


def set_column_sort_by(
    table_name: str,
    column_name: str,
    sort_by_column: str | None,
    save: bool = True,
) -> dict[str, Any]:
    """Ordena `column_name` pelos valores de `sort_by_column` (ex: mês
    por extenso ordenado pelo número do mês) em vez da ordem alfabética
    padrão. `sort_by_column=None` reverte pra ordem alfabética/natural.

    CONFIRMADO AO VIVO: "Month Name" ordenado por "Month Number" saiu
    em ordem cronológica (Janeiro..Dezembro) num gráfico de colunas
    real, não mais alfabética.

    Raises:
        TableNotFoundError: `table_name` não existe.
        ColumnNotFoundError: `column_name` (ou `sort_by_column`, se
            informado) não existe em `table_name`.
    """
    runtime = connection.get_active_runtime()
    _ensure_column_exists(runtime, table_name, column_name)
    if sort_by_column is not None:
        _ensure_column_exists(runtime, table_name, sort_by_column)

    runtime.set_column_sort_by(
        table_name=table_name, column_name=column_name, sort_by_column=sort_by_column
    )

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "column_name": column_name, "sort_by_column": sort_by_column}


def set_column_format(
    table_name: str,
    column_name: str,
    format_string: str | None = None,
    data_category: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Define a máscara de formatação (`format_string`, ex: "R$ #,##0.00",
    "0.0%") e/ou a categoria de dado (`data_category`, ex: "WebUrl",
    "ImageUrl", "Address", "City", "Country", "Latitude", "Longitude")
    de uma coluna. Só os parâmetros passados mudam.

    `data_category` é passado direto pro TOM sem validar contra uma
    lista fechada aqui -- o Power BI/TOM é quem valida o valor no save;
    os nomes acima são os mais comuns na prática, não a lista completa.

    CONFIRMADO AO VIVO: `data_category="Country"` na coluna "Country"
    apareceu no Desktop (Modelagem > propriedades da coluna) como
    "País/Região". `format_string` não foi conferido visualmente nesta
    rodada (só que não deu erro ao salvar).

    Raises:
        TableNotFoundError: `table_name` não existe.
        ColumnNotFoundError: `column_name` não existe em `table_name`.
    """
    runtime = connection.get_active_runtime()
    _ensure_column_exists(runtime, table_name, column_name)

    runtime.set_column_format(
        table_name=table_name, column_name=column_name,
        format_string=format_string, data_category=data_category,
    )

    if save:
        runtime.save_changes()
    return {
        "table_name": table_name, "column_name": column_name,
        "format_string": format_string, "data_category": data_category,
    }


def set_column_visibility(
    table_name: str,
    column_name: str,
    is_hidden: bool,
    save: bool = True,
) -> dict[str, Any]:
    """Esconde/reexibe uma coluna do painel de Campos do Desktop, pra
    todo mundo -- diferente de hide_column/unhide_column, que só
    escondem pra membros de um role de RLS específico (OLS).

    Raises:
        TableNotFoundError: `table_name` não existe.
        ColumnNotFoundError: `column_name` não existe em `table_name`.
    """
    runtime = connection.get_active_runtime()
    _ensure_column_exists(runtime, table_name, column_name)

    runtime.set_column_visibility(table_name=table_name, column_name=column_name, is_hidden=is_hidden)

    if save:
        runtime.save_changes()
    return {"table_name": table_name, "column_name": column_name, "is_hidden": is_hidden}


def set_measure_metadata(
    table_name: str,
    measure_name: str,
    description: str | None = None,
    display_folder: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    _ensure_measure_exists(runtime, table_name, measure_name)

    runtime.set_measure_metadata(
        table_name=table_name, measure_name=measure_name,
        description=description, display_folder=display_folder,
    )

    if save:
        runtime.save_changes()
    return {
        "table_name": table_name, "measure_name": measure_name,
        "description": description, "display_folder": display_folder,
    }


# --- validações --------------------------------------------------------


def _ensure_table_exists(runtime: Any, table_name: str) -> None:
    tables = runtime.list_tables()
    if not any(t.name == table_name for t in tables):
        raise TableNotFoundError(table_name, known_tables=[t.name for t in tables])


def _ensure_table_does_not_exist(runtime: Any, table_name: str) -> None:
    tables = runtime.list_tables()
    if any(t.name == table_name for t in tables):
        raise TableAlreadyExistsError(table_name)


def _ensure_measure_does_not_exist(runtime: Any, measure_name: str) -> None:
    measures = runtime.list_measures()
    if any(m.name == measure_name for m in measures):
        raise MeasureAlreadyExistsError(measure_name)


def _ensure_column_exists(runtime: Any, table_name: str, column_name: str) -> None:
    tables = runtime.list_tables()
    table = next((t for t in tables if t.name == table_name), None)
    if table is None:
        raise TableNotFoundError(table_name, known_tables=[t.name for t in tables])
    if not any(c.name == column_name for c in table.columns):
        raise ColumnNotFoundError(
            table_name, column_name, known_columns=[c.name for c in table.columns]
        )


def _ensure_column_does_not_exist(runtime: Any, table_name: str, column_name: str) -> None:
    tables = runtime.list_tables()
    table = next((t for t in tables if t.name == table_name), None)
    if table is not None and any(c.name == column_name for c in table.columns):
        raise ColumnAlreadyExistsError(table_name, column_name)


def _ensure_hierarchy_does_not_exist(runtime: Any, table_name: str, hierarchy_name: str) -> None:
    if any(
        h.table_name == table_name and h.name == hierarchy_name for h in runtime.list_hierarchies()
    ):
        raise HierarchyAlreadyExistsError(table_name, hierarchy_name)


def _ensure_hierarchy_exists(runtime: Any, table_name: str, hierarchy_name: str) -> None:
    if not any(
        h.table_name == table_name and h.name == hierarchy_name for h in runtime.list_hierarchies()
    ):
        raise HierarchyNotFoundError(table_name, hierarchy_name)


def _ensure_role_does_not_exist(runtime: Any, role_name: str) -> None:
    if any(r.name == role_name for r in runtime.list_roles()):
        raise RoleAlreadyExistsError(role_name)


def _ensure_role_exists(runtime: Any, role_name: str) -> None:
    if not any(r.name == role_name for r in runtime.list_roles()):
        raise RoleNotFoundError(role_name)


def _ensure_table_permission_does_not_exist(runtime: Any, role_name: str, table_name: str) -> None:
    role = next(r for r in runtime.list_roles() if r.name == role_name)
    if any(p.table_name == table_name for p in role.table_permissions):
        raise TablePermissionAlreadyExistsError(role_name, table_name)


def _find_table_permission(runtime: Any, role_name: str, table_name: str) -> Any:
    role = next(r for r in runtime.list_roles() if r.name == role_name)
    return next((p for p in role.table_permissions if p.table_name == table_name), None)


def _ensure_table_permission_exists(runtime: Any, role_name: str, table_name: str) -> None:
    if _find_table_permission(runtime, role_name, table_name) is None:
        raise TablePermissionNotFoundError(role_name, table_name)


def _ensure_column_not_hidden(runtime: Any, role_name: str, table_name: str, column_name: str) -> None:
    permission = _find_table_permission(runtime, role_name, table_name)
    if permission is not None and column_name in permission.hidden_columns:
        raise ColumnAlreadyHiddenError(role_name, table_name, column_name)


def _ensure_column_hidden(runtime: Any, role_name: str, table_name: str, column_name: str) -> None:
    permission = _find_table_permission(runtime, role_name, table_name)
    if permission is None or column_name not in permission.hidden_columns:
        raise ColumnNotHiddenError(role_name, table_name, column_name)


def _ensure_measure_exists(runtime: Any, table_name: str, measure_name: str) -> None:
    measures = runtime.list_measures()
    if not any(m.table_name == table_name and m.name == measure_name for m in measures):
        raise MeasureNotFoundError(measure_name, known_measures=[m.name for m in measures])


def _ensure_relationship_exists(
    runtime: Any, from_table: str, from_column: str, to_table: str, to_column: str
) -> None:
    relationships = runtime.list_relationships()
    match = any(
        r.from_table == from_table
        and r.from_column == from_column
        and r.to_table == to_table
        and r.to_column == to_column
        for r in relationships
    )
    if not match:
        raise RelationshipNotFoundError(from_table, from_column, to_table, to_column)


def _ensure_table_has_no_relationships(runtime: Any, table_name: str) -> None:
    referencing = [
        r
        for r in runtime.list_relationships()
        if r.from_table == table_name or r.to_table == table_name
    ]
    if referencing:
        raise TableHasRelationshipsError(
            table_name,
            relationships=[
                {
                    "from_table": r.from_table,
                    "from_column": r.from_column,
                    "to_table": r.to_table,
                    "to_column": r.to_column,
                }
                for r in referencing
            ],
        )


# --- serialização para resultado de tool ------------------------------


def _table_to_dict(table: TableInfo) -> dict[str, Any]:
    return {
        "table_name": table.name,
        "columns": [{"name": c.name, "data_type": c.data_type} for c in table.columns],
    }


def _measure_to_dict(measure: MeasureInfo) -> dict[str, Any]:
    return {
        "table_name": measure.table_name,
        "measure_name": measure.name,
        "dax_expression": measure.dax_expression,
        "format_string": measure.format_string,
    }


def _relationship_to_dict(relationship: RelationshipInfo) -> dict[str, Any]:
    return {
        "from_table": relationship.from_table,
        "from_column": relationship.from_column,
        "to_table": relationship.to_table,
        "to_column": relationship.to_column,
        "cardinality": relationship.cardinality,
        "cross_filter_direction": relationship.cross_filter_direction,
    }


def _hierarchy_to_dict(hierarchy: HierarchyInfo) -> dict[str, Any]:
    return {
        "table_name": hierarchy.table_name,
        "hierarchy_name": hierarchy.name,
        "levels": list(hierarchy.levels),
    }


def _role_to_dict(role: RoleInfo) -> dict[str, Any]:
    return {
        "role_name": role.name,
        "table_permissions": [
            {
                "table_name": p.table_name,
                "filter_expression": p.filter_expression,
                "hidden_columns": list(p.hidden_columns),
            }
            for p in role.table_permissions
        ],
    }
