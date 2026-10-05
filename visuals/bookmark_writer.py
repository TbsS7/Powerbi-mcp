"""Escrita de bookmarks PBIR: <nome>.bookmark.json + bookmarks.json
dentro de definition/bookmarks/.

MELHOR ESFORÇO: create_bookmark cria só um bookmark de "navegação de
página" -- captura qual página fica ativa (`explorationState.
activeSection`), sem capturar filtro nem estado de visual
(`sections` fica vazio). Isso já cobre o caso de uso mais comum
combinado com um botão de navegação (visual_writer.add_navigation_button):
"ao clicar, ir pra este bookmark". O valor de `explorationState.version`
("1.0") não foi confirmado contra um bookmark real capturado pelo
Power BI Desktop -- pendente de validação ao vivo, ver README.

Schema confirmado contra a referência oficial da Microsoft
(bookmark/1.0.0 e bookmarksMetadata/1.0.0, vendorizados em
tests/schemas/) -- a estrutura do arquivo (nome, displayName,
explorationState.activeSection/sections) não é suposta.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from errors import (
    BookmarkAlreadyExistsError,
    BookmarkNotFoundError,
    InvalidBookmarkError,
    InvalidResourceNameError,
    PageNotFoundError,
    VisualNotFoundError,
)
from visuals import project
from visuals.names import is_valid_object_name, resolve_page_dir
from visuals.schema_urls import BOOKMARK_SCHEMA, BOOKMARKS_METADATA_SCHEMA

_EXPLORATION_STATE_VERSION = "1.0"
# Bookmark de mostrar/esconder: formato do exemplo da doc oficial
# bookmark.md ("Visibility toggles") -- version "1.3", `options` e estado
# por visual em sections.<página>.visualContainers.
_VISIBILITY_STATE_VERSION = "1.3"


def create_bookmark(
    pbip_path: str,
    bookmark_name: str,
    page_name: str,
    display_name: str | None = None,
    visible_visuals: list[str] | None = None,
    hidden_visuals: list[str] | None = None,
) -> dict[str, Any]:
    """Cria um bookmark que navega para `page_name` quando aplicado --
    ou, com `visible_visuals`/`hidden_visuals`, um bookmark de MOSTRAR/
    ESCONDER visuais nessa página (ex: abrir/fechar um painel de
    informações), que não troca de página nem mexe em filtro/slicer.

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        InvalidResourceNameError: `bookmark_name` não é seguro para
            usar como nome de arquivo (evita path traversal).
        BookmarkAlreadyExistsError: já existe um bookmark com esse nome.
    """
    if not is_valid_object_name(bookmark_name):
        raise InvalidResourceNameError("bookmark_name", bookmark_name)

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    visible = list(visible_visuals or [])
    hidden = list(hidden_visuals or [])
    if set(visible) & set(hidden):
        raise InvalidBookmarkError(
            f"Visual(is) {sorted(set(visible) & set(hidden))} estão em visible_visuals e hidden_visuals ao mesmo tempo."
        )
    for visual_name in visible + hidden:
        if not is_valid_object_name(visual_name) or not (page_dir / "visuals" / visual_name / "visual.json").is_file():
            raise VisualNotFoundError(visual_name, page_name)

    bookmarks_dir = definition_dir / "bookmarks"
    bookmarks_json_path = bookmarks_dir / "bookmarks.json"
    if not bookmarks_dir.is_dir():
        bookmarks_dir.mkdir()
        _write_json(bookmarks_json_path, {"$schema": BOOKMARKS_METADATA_SCHEMA, "items": []})

    bookmark_path = bookmarks_dir / f"{bookmark_name}.bookmark.json"
    if not bookmark_path.resolve().is_relative_to(bookmarks_dir.resolve()):
        raise InvalidResourceNameError("bookmark_name", bookmark_name)
    if bookmark_path.exists():
        raise BookmarkAlreadyExistsError(bookmark_name)

    resolved_display_name = display_name or bookmark_name
    bookmark: dict[str, Any] = {
        "$schema": BOOKMARK_SCHEMA,
        "name": bookmark_name,
        "displayName": resolved_display_name,
        "explorationState": {
            "version": _EXPLORATION_STATE_VERSION,
            "activeSection": page_name,
            "sections": {},
        },
    }
    if visible or hidden:
        bookmark["options"] = {
            "targetVisualNames": visible + hidden,
            "suppressData": True,
            "suppressDisplay": False,
            "suppressActiveSection": True,
            "applyOnlyToTargetVisuals": False,
        }
        bookmark["explorationState"]["version"] = _VISIBILITY_STATE_VERSION
        containers: dict[str, Any] = {name: {"singleVisual": {}} for name in visible}
        containers.update({name: {"singleVisual": {"display": {"mode": "hidden"}}} for name in hidden})
        bookmark["explorationState"]["sections"] = {page_name: {"visualContainers": containers}}
    _write_json(bookmark_path, bookmark)
    _append_bookmark_item(bookmarks_json_path, bookmark_name)

    result: dict[str, Any] = {
        "bookmark_name": bookmark_name,
        "display_name": resolved_display_name,
        "page_name": page_name,
    }
    if visible or hidden:
        result.update(visible_visuals=visible, hidden_visuals=hidden)
    return result


# Bookmark "voltar ao padrão": formato copiado de um bookmark criado pelo
# próprio Desktop (técnica de comparação, réplica página 2, 2026-09-30) +
# doc oficial bookmark.md ("Reset filters/slicers": Data On, Current page
# Off). explorationState.version "1.11" = a que o Desktop gravou.
_RESET_STATE_VERSION = "1.11"
_SLICER_TYPES = ("slicer", "advancedSlicerVisual")


def create_reset_bookmark(
    pbip_path: str,
    bookmark_name: str,
    page_name: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Cria um bookmark "voltar ao padrão" (Dados ligado) com o estado
    SALVO da página: seleção de cada slicer, filtros de visual, nível de
    drill dos gráficos e visuais escondidos. Aplicar o bookmark (ex: por
    um botão) devolve a página a esse estado -- inclusive limpa clique em
    gráfico, o que o botão "Limpar segmentações" não faz.

    O estado vem dos ARQUIVOS: deixe os slicers no padrão e salve no
    Desktop antes (o Desktop grava a seleção em `visual.objects.general`).

    Raises:
        PageNotFoundError: `page_name` não existe no relatório.
        InvalidResourceNameError: `bookmark_name` inseguro como nome de arquivo.
        BookmarkAlreadyExistsError: já existe um bookmark com esse nome.
    """
    if not is_valid_object_name(bookmark_name):
        raise InvalidResourceNameError("bookmark_name", bookmark_name)

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    bookmarks_dir = definition_dir / "bookmarks"
    bookmarks_json_path = bookmarks_dir / "bookmarks.json"
    bookmark_path = bookmarks_dir / f"{bookmark_name}.bookmark.json"
    if not bookmark_path.resolve().is_relative_to(bookmarks_dir.resolve()):
        raise InvalidResourceNameError("bookmark_name", bookmark_name)
    if bookmark_path.exists():
        raise BookmarkAlreadyExistsError(bookmark_name)

    containers: dict[str, Any] = {}
    with_selection: list[str] = []
    for visual_json_path in sorted((page_dir / "visuals").glob("*/visual.json")):
        instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
        name = instance["name"]
        container, has_selection = _captured_state(instance)
        containers[name] = container
        if has_selection:
            with_selection.append(name)

    if not bookmarks_dir.is_dir():
        bookmarks_dir.mkdir()
    if not bookmarks_json_path.is_file():
        _write_json(bookmarks_json_path, {"$schema": BOOKMARKS_METADATA_SCHEMA, "items": []})

    resolved_display_name = display_name or bookmark_name
    _write_json(bookmark_path, {
        "$schema": BOOKMARK_SCHEMA,
        "name": bookmark_name,
        "displayName": resolved_display_name,
        "options": {"suppressActiveSection": True},
        "explorationState": {
            "version": _RESET_STATE_VERSION,
            "activeSection": page_name,
            "sections": {page_name: {"visualContainers": containers}},
        },
    })
    _append_bookmark_item(bookmarks_json_path, bookmark_name)
    return {
        "bookmark_name": bookmark_name,
        "display_name": resolved_display_name,
        "page_name": page_name,
        "visuals_captured": len(containers),
        "slicers_with_selection": with_selection,
    }


def _captured_state(instance: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    visual = instance.get("visual", {})
    single: dict[str, Any] = {"visualType": visual.get("visualType"), "objects": {}}
    has_selection = False

    objects = visual.get("objects", {})
    if visual.get("visualType") in _SLICER_TYPES:
        general = [e for e in objects.get("general", []) if e.get("properties", {}).get("filter")]
        if general:
            merge: dict[str, Any] = {"general": [{"properties": {"filter": general[0]["properties"]["filter"]}}]}
            if objects.get("selection"):
                merge["selection"] = objects["selection"]
            single["objects"] = {"merge": merge}
            has_selection = True

    category = visual.get("query", {}).get("queryState", {}).get("Category", {}).get("projections", [])
    if len(category) > 1:
        active = [p["field"] for p in category if p.get("active")] or [category[0]["field"]]
        single["activeProjections"] = {"Category": active}

    if instance.get("isHidden"):
        single["display"] = {"mode": "hidden"}

    container: dict[str, Any] = {"singleVisual": single}
    by_expr = [
        {"name": f["name"], "type": f["type"], "filter": f["filter"], "expression": f["field"], "howCreated": 1}
        for f in instance.get("filterConfig", {}).get("filters", [])
        if f.get("filter") and f.get("field") and f.get("type")
    ]
    if by_expr:
        container["filters"] = {"byExpr": by_expr}
    return container, has_selection


def delete_bookmark(pbip_path: str, bookmark_name: str) -> dict[str, Any]:
    """Remove um bookmark (arquivo + entrada em bookmarks.json).

    Raises:
        InvalidResourceNameError: `bookmark_name` não é seguro para
            usar como nome de arquivo (evita path traversal).
        BookmarkNotFoundError: `bookmark_name` não existe.
    """
    if not is_valid_object_name(bookmark_name):
        raise InvalidResourceNameError("bookmark_name", bookmark_name)

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    bookmarks_dir = definition_dir / "bookmarks"
    bookmark_path = bookmarks_dir / f"{bookmark_name}.bookmark.json"
    if not bookmark_path.resolve().is_relative_to(bookmarks_dir.resolve()):
        raise InvalidResourceNameError("bookmark_name", bookmark_name)
    if not bookmark_path.is_file():
        raise BookmarkNotFoundError(bookmark_name)

    bookmark_path.unlink()
    _remove_bookmark_item(bookmarks_dir / "bookmarks.json", bookmark_name)

    return {"bookmark_name": bookmark_name, "deleted": True}


def list_bookmarks(pbip_path: str) -> list[dict[str, Any]]:
    """Lista os bookmarks existentes no relatório."""
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    bookmarks_dir = definition_dir / "bookmarks"
    bookmarks_json_path = bookmarks_dir / "bookmarks.json"
    if not bookmarks_json_path.is_file():
        return []

    items = json.loads(bookmarks_json_path.read_text(encoding="utf-8")).get("items", [])
    result = []
    for item in items:
        name = item["name"]
        # name vem de bookmarks.json, não de um parâmetro direto desta
        # chamada -- pular uma entrada inválida em vez de deixar um
        # índice adulterado ler fora de bookmarks_dir.
        if not is_valid_object_name(name):
            continue
        bookmark_path = bookmarks_dir / f"{name}.bookmark.json"
        if not bookmark_path.resolve().is_relative_to(bookmarks_dir.resolve()):
            continue
        data = json.loads(bookmark_path.read_text(encoding="utf-8"))
        result.append(
            {
                "bookmark_name": name,
                "display_name": data["displayName"],
                "page_name": data["explorationState"]["activeSection"],
            }
        )
    return result


def _append_bookmark_item(bookmarks_json_path: Path, bookmark_name: str) -> None:
    data = json.loads(bookmarks_json_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not any(item.get("name") == bookmark_name for item in items):
        items.append({"name": bookmark_name})
    data["items"] = items
    _write_json(bookmarks_json_path, data)


def _remove_bookmark_item(bookmarks_json_path: Path, bookmark_name: str) -> None:
    data = json.loads(bookmarks_json_path.read_text(encoding="utf-8"))
    data["items"] = [item for item in data.get("items", []) if item.get("name") != bookmark_name]
    _write_json(bookmarks_json_path, data)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
