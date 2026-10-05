"""Escrita de page.json / pages.json / version.json / report.json
dentro da pasta .Report de um projeto .pbip (formato PBIR).

create_report_page cria o esqueleto `definition/` (version.json,
report.json, pages/pages.json) na primeira vez que uma página é
adicionada a um relatório ainda não salvo em PBIR -- nunca sobrescreve
um `definition/` já existente, e recusa um relatório PBIR-Legacy (ver
visuals.project.get_definition_dir).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from errors import (
    DrillthroughFieldAlreadyExistsError,
    DrillthroughFieldNotFoundError,
    PageAlreadyExistsError,
    PageNotFoundError,
    PerspectiveNotFoundError,
)
from modeling import metadata as modeling_metadata
from visuals import project
from visuals.filters import HOW_CREATED_DRILLTHROUGH, filter_matches, new_filter_name
from visuals.names import resolve_page_dir
from visuals.schema_urls import (
    PAGE_SCHEMA,
    PAGES_METADATA_SCHEMA,
    PBIR_DEFINITION_VERSION,
    REPORT_SCHEMA,
    VERSION_METADATA_SCHEMA,
)
from visuals.validator import field_reference_node, resolve_field

_DEFAULT_PAGE_WIDTH = 1280
_DEFAULT_PAGE_HEIGHT = 720
# Página de tooltip: o que o Power BI Desktop gravou ao criar uma pela UI
# (comparação de 2026-09-29) -- `type: "Tooltip"`, `ActualSize`, 400x300,
# sem `pageBinding`. O schema oficial page/1.4.0 confirma `type`.
_TOOLTIP_PAGE_WIDTH = 400
_TOOLTIP_PAGE_HEIGHT = 300
_DRILLTHROUGH_BINDING_NAME = "Pod"


def create_report_page(
    pbip_path: str,
    page_name: str,
    display_name: str | None = None,
    tooltip: bool = False,
) -> dict[str, Any]:
    """Cria uma página. `tooltip=True` cria uma página de tooltip
    (mini-página que aparece ao passar o mouse num visual ligado a ela
    por set_visual_tooltip_page)."""
    report_dir = project.resolve_report_dir(pbip_path)

    # dispara ReportProjectNotFoundError se for PBIR-Legacy; não faz
    # nada se ainda não houver definition/ (esse caso é esperado aqui --
    # é quando fazemos o scaffold abaixo)
    if project.is_legacy_report(report_dir):
        project.get_definition_dir(report_dir)  # levanta com a mensagem certa

    definition_dir = report_dir / "definition"
    if not project.has_pbir_definition(report_dir):
        _scaffold_definition(definition_dir)

    pages_dir = definition_dir / "pages"
    page_dir = resolve_page_dir(pages_dir, page_name)
    if page_dir.exists():
        raise PageAlreadyExistsError(page_name)

    resolved_display_name = display_name or page_name
    page_dir.mkdir(parents=True)
    page: dict[str, Any] = {
        "$schema": PAGE_SCHEMA,
        "name": page_name,
        "displayName": resolved_display_name,
        "displayOption": "ActualSize" if tooltip else "FitToPage",
        "width": _TOOLTIP_PAGE_WIDTH if tooltip else _DEFAULT_PAGE_WIDTH,
        "height": _TOOLTIP_PAGE_HEIGHT if tooltip else _DEFAULT_PAGE_HEIGHT,
    }
    if tooltip:
        page["type"] = "Tooltip"
    _write_json(page_dir / "page.json", page)
    _register_page(pages_dir, page_name)

    return {"page_name": page_name, "display_name": resolved_display_name, "tooltip": tooltip}


def set_page_perspective(pbip_path: str, page_name: str, perspective: str | None) -> dict[str, Any]:
    """Perspectiva que o leitor vê no "Personalizar visuais" desta página
    (Formatar página -> Personalizar visual). `None` volta pra "Campos
    padrão" (o modelo inteiro).

    Grava `objects.personalizeVisual[].properties.perspectiveRef` --
    exatamente o que o Desktop gravou ao escolher pela UI (comparação de
    2026-09-30; schema oficial page/1.4.0 tem `PersonalizeVisual`). Não
    liga o recurso no relatório (`settings.allowInlineExploration` do
    report.json, efeito no relatório inteiro) -- só avisa se estiver
    desligado."""
    from modeling import perspectives as model_perspectives

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    page_json_path = page_dir / "page.json"
    if not page_json_path.is_file():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    if perspective is not None:
        known = model_perspectives.perspective_names(pbip_path)
        if perspective not in known:
            raise PerspectiveNotFoundError(perspective, known)

    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    objects = page.setdefault("objects", {})
    entries = objects.setdefault("personalizeVisual", [])
    base = next((e for e in entries if "selector" not in e), None)
    if perspective is not None:
        if base is None:
            base = {"properties": {}}
            entries.insert(0, base)
        literal = "'" + perspective.replace("'", "''") + "'"
        base.setdefault("properties", {})["perspectiveRef"] = {"expr": {"Literal": {"Value": literal}}}
    elif base is not None:
        base.get("properties", {}).pop("perspectiveRef", None)
        if not base.get("properties"):
            entries.remove(base)
    if not entries:
        objects.pop("personalizeVisual")
    if not objects:
        page.pop("objects")
    _write_json(page_json_path, page)

    report_json = definition_dir / "report.json"
    settings = json.loads(report_json.read_text(encoding="utf-8")).get("settings", {}) if report_json.is_file() else {}
    enabled = settings.get("allowInlineExploration") is True
    result: dict[str, Any] = {
        "page_name": page_name,
        "perspective": perspective,
        "personalize_visuals_enabled": enabled,
    }
    if not enabled:
        result["note"] = (
            "O recurso \"Personalizar visuais\" está desligado neste relatório -- a perspectiva só "
            "vale quando ele estiver ligado (Arquivo > Opções e configurações > Opções > Arquivo "
            "atual > Configurações de relatório > Personalizar visuais)."
        )
    return result


def delete_report_page(pbip_path: str, page_name: str) -> dict[str, Any]:
    """Remove uma página do relatório (pasta + entrada em pages.json).

    Se a página removida era a `activePageName`, a primeira página
    restante (na ordem de `pageOrder`) assume esse papel; se não
    sobrar nenhuma página, `activePageName` é removido de pages.json.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
    """
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    pages_dir = definition_dir / "pages"
    page_dir = resolve_page_dir(pages_dir, page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(
            f"Página '{page_name}' não existe em '{report_dir}'."
        )

    shutil.rmtree(page_dir)
    _unregister_page(pages_dir, page_name)

    return {"page_name": page_name, "deleted": True}


def add_drillthrough_field(pbip_path: str, page_name: str, query_ref: str) -> dict[str, Any]:
    """Configura `page_name` como página de destino de drillthrough por
    `query_ref` (ex: "financials.Segment") -- o menu de clique direito
    "Drill through" passa a aparecer em qualquer visual de outra página
    que use esse mesmo campo, sem precisar tocar na página de origem.

    Confirmado contra o exemplo oficial completo da Microsoft para
    autoria de PBIR (skills-for-fabric/.../authoring-workflows.md, seção
    "Drillthrough Page"): a página de destino recebe um filtro vazio em
    `filterConfig.filters` (`type="Categorical"`,
    `howCreated="Drillthrough"` -- sem valor selecionado, só o campo; o
    valor é aplicado em tempo real quando alguém usa o drillthrough) e
    um `pageBinding` (`type="Drillthrough"`) com um `parameters[]`
    apontando pra esse filtro via `boundFilter`. `filterConfiguration/
    1.1.0` e `semanticQuery/1.2.0` (pra `field`/`fieldExpr`) vendorizados
    em tests/schemas/ pra validação offline.

    Chamar de novo com outro `query_ref` na mesma página adiciona mais um
    campo de drillthrough (múltiplos campos = múltiplos filtros +
    múltiplos parâmetros, mas um `pageBinding` só, reaproveitado).

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        UnknownFieldError: `query_ref` não existe no modelo (propagado
            por visuals.validator.resolve_field).
        DrillthroughFieldAlreadyExistsError: a página já tem um campo de
            drillthrough pra essa mesma referência.
    """
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
    resolved = resolve_field(model_metadata, query_ref)
    field_node = field_reference_node(resolved)

    page_json_path = page_dir / "page.json"
    page = json.loads(page_json_path.read_text(encoding="utf-8"))

    filter_config = page.setdefault("filterConfig", {"filters": []})
    filters = filter_config.setdefault("filters", [])
    if any(
        filter_matches(f, resolved.entity, resolved.property, HOW_CREATED_DRILLTHROUGH)
        for f in filters
    ):
        raise DrillthroughFieldAlreadyExistsError(page_name, resolved.query_ref)

    filter_name = new_filter_name()
    filters.append(
        {
            "name": filter_name,
            "field": field_node,
            "type": "Categorical",
            "howCreated": "Drillthrough",
        }
    )

    page_binding = page.setdefault(
        "pageBinding", {"name": _DRILLTHROUGH_BINDING_NAME, "type": "Drillthrough", "parameters": []}
    )
    page_binding["parameters"].append(
        {"name": f"Param_{filter_name}", "boundFilter": filter_name, "fieldExpr": field_node}
    )

    _write_json(page_json_path, page)

    return {"page_name": page_name, "query_ref": resolved.query_ref, "filter_name": filter_name}


def remove_drillthrough_field(pbip_path: str, page_name: str, query_ref: str) -> dict[str, Any]:
    """Reverte add_drillthrough_field pra `query_ref` -- remove o filtro
    e o parâmetro correspondentes. Se era o último campo de drillthrough
    da página, também remove `filterConfig`/`pageBinding` por completo,
    deixando o page.json limpo.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        UnknownFieldError: `query_ref` não existe no modelo.
        DrillthroughFieldNotFoundError: a página não tem um campo de
            drillthrough pra essa referência.
    """
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    model_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)
    resolved = resolve_field(model_metadata, query_ref)

    page_json_path = page_dir / "page.json"
    page = json.loads(page_json_path.read_text(encoding="utf-8"))

    filters = page.get("filterConfig", {}).get("filters", [])
    matching = next(
        (
            f
            for f in filters
            if filter_matches(f, resolved.entity, resolved.property, HOW_CREATED_DRILLTHROUGH)
        ),
        None,
    )
    if matching is None:
        raise DrillthroughFieldNotFoundError(page_name, resolved.query_ref)

    filter_name = matching["name"]
    page["filterConfig"]["filters"] = [f for f in filters if f["name"] != filter_name]
    if not page["filterConfig"]["filters"]:
        page.pop("filterConfig", None)

    parameters = page.get("pageBinding", {}).get("parameters", [])
    page["pageBinding"]["parameters"] = [p for p in parameters if p["boundFilter"] != filter_name]
    if not page["pageBinding"]["parameters"]:
        page.pop("pageBinding", None)

    _write_json(page_json_path, page)

    return {"page_name": page_name, "query_ref": resolved.query_ref, "deleted": True}


def _unregister_page(pages_dir: Path, page_name: str) -> None:
    pages_json_path = pages_dir / "pages.json"
    data = json.loads(pages_json_path.read_text(encoding="utf-8"))

    page_order = [p for p in data.get("pageOrder", []) if p != page_name]
    data["pageOrder"] = page_order

    if data.get("activePageName") == page_name:
        if page_order:
            data["activePageName"] = page_order[0]
        else:
            data.pop("activePageName", None)

    _write_json(pages_json_path, data)


def _scaffold_definition(definition_dir: Path) -> None:
    definition_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        definition_dir / "version.json",
        {"$schema": VERSION_METADATA_SCHEMA, "version": PBIR_DEFINITION_VERSION},
    )
    _write_json(definition_dir / "report.json", {"$schema": REPORT_SCHEMA, "themeCollection": {}})
    pages_dir = definition_dir / "pages"
    pages_dir.mkdir()
    _write_json(pages_dir / "pages.json", {"$schema": PAGES_METADATA_SCHEMA})


def _register_page(pages_dir: Path, page_name: str) -> None:
    pages_json_path = pages_dir / "pages.json"
    data = json.loads(pages_json_path.read_text(encoding="utf-8"))

    page_order = data.get("pageOrder", [])
    if page_name not in page_order:
        page_order.append(page_name)
    data["pageOrder"] = page_order

    if "activePageName" not in data:
        data["activePageName"] = page_name

    _write_json(pages_json_path, data)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
