"""Filtros com valor (pré-aplicados) no nível de página (page.json) e de
relatório (report.json) -- sem slicer visual. O JSON de cada filtro vem
de visuals.filters (construtores puros, com as fontes oficiais citadas
na docstring de lá); este módulo só faz a leitura/escrita dos arquivos.

report.json é compartilhado com visuals.theme_writer (themeCollection,
resourcePackages, objects, settings) -- aqui só a chave `filterConfig` é
tocada, num read-modify-write que preserva todo o resto.

Filtros de usuário (`howCreated: "User"`) convivem no mesmo array com os
de drillthrough (`howCreated: "Drillthrough"`, visuals.page_writer): a
deduplicação e a remoção daqui só enxergam os de usuário.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from errors import (
    FilterAlreadyExistsError,
    FilterNotFoundError,
    InvalidFilterDefinitionError,
    PageNotFoundError,
)
from modeling import metadata as modeling_metadata
from visuals import filters, project
from visuals.names import resolve_page_dir
from visuals.validator import ResolvedField, resolve_field

_REPORT_SCOPE = "report"
_FILTER_TYPES = ("categorical", "between", "comparison")


def add_page_filter(
    pbip_path: str,
    page_name: str,
    query_ref: str,
    filter_type: str,
    values: list[Any] | None = None,
    exclude: bool = False,
    lower: Any = None,
    upper: Any = None,
    operator: str | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Adiciona um filtro com valor a `page_name` (vale pra todos os
    visuais da página). Ver `_build_filter` pros parâmetros por tipo.

    Raises:
        PageNotFoundError, UnknownFieldError, InvalidFilterDefinitionError,
        FilterAlreadyExistsError.
    """
    json_path = _page_json_path(pbip_path, page_name)
    resolved = _resolve(pbip_path, query_ref)
    entry = _build_filter(resolved, filter_type, values, exclude, lower, upper, operator, value)
    _add_to_file(json_path, entry, resolved, scope=page_name)
    return {"scope": page_name, "query_ref": resolved.query_ref, "filter_name": entry["name"], "type": entry["type"]}


def remove_page_filter(pbip_path: str, page_name: str, query_ref: str) -> dict[str, Any]:
    """Remove o filtro de usuário em `query_ref` de `page_name` (não
    mexe em campo de drillthrough no mesmo campo)."""
    json_path = _page_json_path(pbip_path, page_name)
    resolved = _resolve(pbip_path, query_ref)
    _remove_from_file(json_path, resolved, scope=page_name)
    return {"scope": page_name, "query_ref": resolved.query_ref, "deleted": True}


def add_visual_filter(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    query_ref: str,
    filter_type: str,
    values: list[Any] | None = None,
    exclude: bool = False,
    lower: Any = None,
    upper: Any = None,
    operator: str | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Filtro com valor num VISUAL só (`visual.json -> filterConfig`, na
    raiz -- schema oficial visualContainer/2.7.0; doc filters.md: mesmo
    array de filtros da página/relatório). Ex: limitar um gráfico aos
    itens "Atual" e "PY" de um calculation group."""
    from visuals.visual_writer import _resolve_visual_dir

    json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    resolved = _resolve(pbip_path, query_ref)
    entry = _build_filter(resolved, filter_type, values, exclude, lower, upper, operator, value)
    scope = f"{page_name}/{visual_name}"
    _add_to_file(json_path, entry, resolved, scope=scope)
    return {"scope": scope, "query_ref": resolved.query_ref, "filter_name": entry["name"], "type": entry["type"]}


def remove_visual_filter(pbip_path: str, page_name: str, visual_name: str, query_ref: str) -> dict[str, Any]:
    """Remove o filtro de usuário em `query_ref` de um visual."""
    from visuals.visual_writer import _resolve_visual_dir

    json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    resolved = _resolve(pbip_path, query_ref)
    scope = f"{page_name}/{visual_name}"
    _remove_from_file(json_path, resolved, scope=scope)
    return {"scope": scope, "query_ref": resolved.query_ref, "deleted": True}


def add_report_filter(
    pbip_path: str,
    query_ref: str,
    filter_type: str,
    values: list[Any] | None = None,
    exclude: bool = False,
    lower: Any = None,
    upper: Any = None,
    operator: str | None = None,
    value: Any = None,
) -> dict[str, Any]:
    """Adiciona um filtro com valor ao relatório inteiro (todas as
    páginas). Mesmos parâmetros de add_page_filter, sem `page_name`."""
    json_path = _report_json_path(pbip_path)
    resolved = _resolve(pbip_path, query_ref)
    entry = _build_filter(resolved, filter_type, values, exclude, lower, upper, operator, value)
    _add_to_file(json_path, entry, resolved, scope=_REPORT_SCOPE)
    return {"scope": _REPORT_SCOPE, "query_ref": resolved.query_ref, "filter_name": entry["name"], "type": entry["type"]}


def remove_report_filter(pbip_path: str, query_ref: str) -> dict[str, Any]:
    """Remove o filtro de usuário em `query_ref` do relatório."""
    json_path = _report_json_path(pbip_path)
    resolved = _resolve(pbip_path, query_ref)
    _remove_from_file(json_path, resolved, scope=_REPORT_SCOPE)
    return {"scope": _REPORT_SCOPE, "query_ref": resolved.query_ref, "deleted": True}


# --- internos ---------------------------------------------------------------


def _build_filter(
    resolved: ResolvedField,
    filter_type: str,
    values: list[Any] | None,
    exclude: bool,
    lower: Any,
    upper: Any,
    operator: str | None,
    value: Any,
) -> dict[str, Any]:
    """`categorical` usa `values` (+ `exclude`); `between` usa `lower`/
    `upper` (inclusivos); `comparison` usa `operator` (eq/gt/gte/lt/lte)
    + `value`."""
    if filter_type == "categorical":
        return filters.categorical_filter(resolved, values or [], exclude=exclude)
    if filter_type == "between":
        return filters.between_filter(resolved, lower, upper)
    if filter_type == "comparison":
        return filters.comparison_filter(resolved, operator or "", value)
    raise InvalidFilterDefinitionError(
        f"filter_type '{filter_type}' desconhecido. Use um de: {', '.join(_FILTER_TYPES)} "
        "(TopN só existe em nível de visual)."
    )


def _resolve(pbip_path: str, query_ref: str) -> ResolvedField:
    model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
    return resolve_field(model_metadata, query_ref)


def _page_json_path(pbip_path: str, page_name: str) -> Path:
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")
    return page_dir / "page.json"


def _report_json_path(pbip_path: str) -> Path:
    report_dir = project.resolve_report_dir(pbip_path)
    return project.get_definition_dir(report_dir) / "report.json"


def _add_to_file(json_path: Path, entry: dict[str, Any], resolved: ResolvedField, scope: str) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    existing = data.setdefault("filterConfig", {}).setdefault("filters", [])
    if any(
        filters.filter_matches(f, resolved.entity, resolved.property, filters.HOW_CREATED_USER)
        for f in existing
    ):
        raise FilterAlreadyExistsError(scope, resolved.query_ref)
    existing.append(entry)
    _write_json(json_path, data)


def _remove_from_file(json_path: Path, resolved: ResolvedField, scope: str) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    existing = data.get("filterConfig", {}).get("filters", [])
    kept = [
        f
        for f in existing
        if not filters.filter_matches(f, resolved.entity, resolved.property, filters.HOW_CREATED_USER)
    ]
    if len(kept) == len(existing):
        raise FilterNotFoundError(scope, resolved.query_ref)

    if kept:
        data["filterConfig"]["filters"] = kept
    else:
        data["filterConfig"].pop("filters", None)
        if not data["filterConfig"]:
            data.pop("filterConfig")
    _write_json(json_path, data)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
