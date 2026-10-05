"""Perspectivas: um recorte do modelo com só algumas tabelas/colunas/
medidas/hierarquias. No Power BI, o uso é no "Personalizar visuais": o
leitor do relatório só vê os campos da perspectiva escolhida pra página.

Fontes (regra do projeto -- nada inventado):
- Doc oficial "Let users personalize visuals in a report" (Microsoft
  Learn): o TMDL de exemplo (`perspectiveTable` com `includeAll`, ou
  `perspectiveColumn`/`perspectiveMeasure`/`perspectiveHierarchy`), a
  consulta DAX oficial com INFO.PERSPECTIVES() e afins pra conferir, e
  os avisos -- perspectiva NÃO é mecanismo de segurança, e antes de
  apagar uma, conferir se não está em uso no "Personalizar visuais".
- Reflexão .NET das DLLs do TOM (ver o bloco "perspectivas" em
  modeling/tom_runtime.py).
"""

from __future__ import annotations

from typing import Any

from errors import (
    InvalidPerspectiveError,
    ModelObjectNotFoundError,
    PerspectiveAlreadyExistsError,
    PerspectiveNotFoundError,
)
from modeling import connection
from modeling.metadata import PerspectiveInfo, PerspectiveTableInfo

# Coluna interna que todo modelo tem ("RowNumber-<guid>") -- nunca é um
# campo de verdade pro usuário.
_ROW_NUMBER_PREFIX = "RowNumber-"


def create_perspective(
    name: str,
    tables: list[str] | None = None,
    fields: list[str] | None = None,
    description: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Cria a perspectiva `name` com `tables` inteiras (inclui o que for
    criado nelas depois) e/ou `fields` avulsos ("Tabela.Campo" --
    coluna, medida ou hierarquia, descoberto sozinho)."""
    if not name or not name.strip():
        raise InvalidPerspectiveError("Informe um nome pra perspectiva.")
    if not tables and not fields:
        raise InvalidPerspectiveError(
            "Uma perspectiva precisa de pelo menos uma tabela (`tables`) ou campo (`fields`)."
        )

    runtime = connection.get_active_runtime()
    if any(p.name == name for p in runtime.list_perspectives()):
        raise PerspectiveAlreadyExistsError(name)

    model_tables = {t.name: t for t in runtime.list_tables()}
    measures_by_table: dict[str, list[str]] = {}
    for measure in runtime.list_measures():
        measures_by_table.setdefault(measure.table_name, []).append(measure.name)
    hierarchies_by_table: dict[str, list[str]] = {}
    for hierarchy in runtime.list_hierarchies():
        hierarchies_by_table.setdefault(hierarchy.table_name, []).append(hierarchy.name)

    whole = []
    for table_name in tables or []:
        if table_name not in model_tables:
            raise ModelObjectNotFoundError("tabela", table_name, known=sorted(model_tables))
        whole.append(table_name)

    picked: dict[str, dict[str, list[str]]] = {}
    for field in fields or []:
        table_name, kind, field_name = _resolve_field(field, model_tables, measures_by_table, hierarchies_by_table)
        if table_name in whole:
            continue  # a tabela inteira já está na perspectiva
        bucket = picked.setdefault(table_name, {"columns": [], "measures": [], "hierarchies": []})
        if field_name not in bucket[kind]:
            bucket[kind].append(field_name)

    perspective = PerspectiveInfo(
        name=name,
        description=description or None,
        tables=tuple(PerspectiveTableInfo(table_name=t, include_all=True) for t in whole)
        + tuple(
            PerspectiveTableInfo(
                table_name=t,
                columns=tuple(b["columns"]),
                measures=tuple(b["measures"]),
                hierarchies=tuple(b["hierarchies"]),
            )
            for t, b in picked.items()
        ),
    )
    runtime.create_perspective(perspective)
    if save:
        runtime.save_changes()
    return _to_dict(perspective)


def delete_perspective(name: str, save: bool = True) -> dict[str, Any]:
    runtime = connection.get_active_runtime()
    known = [p.name for p in runtime.list_perspectives()]
    if name not in known:
        raise PerspectiveNotFoundError(name, known)
    runtime.delete_perspective(name)
    if save:
        runtime.save_changes()
    return {"name": name, "deleted": True}


def list_perspectives() -> list[dict[str, Any]]:
    runtime = connection.get_active_runtime()
    return [_to_dict(p) for p in runtime.list_perspectives()]


def perspective_names(pbip_path: str | None = None) -> list[str]:
    """Perspectivas existentes: pela conexão ativa se houver, senão pelos
    arquivos TMDL salvos do projeto."""
    runtime = connection.get_active_runtime(required=False)
    if runtime is not None:
        return [p.name for p in runtime.list_perspectives()]
    if pbip_path:
        from modeling import tmdl_reader

        return tmdl_reader.read_perspective_names(pbip_path)
    return []


def _resolve_field(field, model_tables, measures_by_table, hierarchies_by_table) -> tuple[str, str, str]:
    """"Tabela.Campo" -> (tabela, tipo, campo). Nome de tabela pode ter
    ponto, então tenta a tabela existente mais longa que é prefixo."""
    candidates = sorted(
        (t for t in model_tables if field.startswith(t + ".")), key=len, reverse=True
    )
    for table_name in candidates:
        field_name = field[len(table_name) + 1:]
        columns = [c.name for c in model_tables[table_name].columns if not c.name.startswith(_ROW_NUMBER_PREFIX)]
        if field_name in columns:
            return table_name, "columns", field_name
        if field_name in measures_by_table.get(table_name, []):
            return table_name, "measures", field_name
        if field_name in hierarchies_by_table.get(table_name, []):
            return table_name, "hierarchies", field_name
    known = [
        f"{t.name}.{c.name}" for t in model_tables.values() for c in t.columns
        if not c.name.startswith(_ROW_NUMBER_PREFIX)
    ] + [f"{t}.{m}" for t, ms in measures_by_table.items() for m in ms]
    raise ModelObjectNotFoundError("campo", field, known=known)


def _to_dict(perspective: PerspectiveInfo) -> dict[str, Any]:
    return {
        "name": perspective.name,
        "description": perspective.description,
        "tables": [
            {
                "table_name": t.table_name,
                "include_all": t.include_all,
                "columns": list(t.columns),
                "measures": list(t.measures),
                "hierarchies": list(t.hierarchies),
            }
            for t in perspective.tables
        ],
    }
