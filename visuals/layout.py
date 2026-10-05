"""Reposicionamento de visuais existentes numa página.

set_page_layout só reescreve a propriedade `position` de cada
visual.json já existente -- não cria, remove nem valida campos de
visual algum. O restante do arquivo (query, visualType) é preservado
byte a byte (só o dict Python é relido e regravado).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from errors import InvalidLayoutError, PageNotFoundError, VisualNotFoundError
from visuals import project
from visuals.names import resolve_page_dir

_MARGIN = 8
MARGIN = _MARGIN  # público: o applier reserva a faixa do título com ele
# cartão legado e o atual (a doc oficial recomenda cardVisual)
_CARD_TYPES = ("card", "cardVisual")


def get_page_size(pbip_path: str, page_name: str) -> tuple[float, float]:
    """(largura, altura) da página, lidas do page.json (padrão 1280x720)."""
    report_dir = project.resolve_report_dir(pbip_path)
    page_dir = resolve_page_dir(project.get_definition_dir(report_dir) / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")
    return _read_page_size(page_dir)


def set_page_layout(
    pbip_path: str,
    page_name: str,
    layout: Literal["grid", "kpi_row"],
    top: float | None = None,
    keep_fixed: list[str] | None = None,
) -> dict[str, Any]:
    """Reposiciona os visuais da página. `top` é o y onde o layout
    começa (padrão: a margem de 8px) -- usado pra reservar uma faixa de
    título no topo; `keep_fixed` são nomes de visuais que ficam onde
    estão (ex: o textbox do título)."""
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    page_width, page_height = _read_page_size(page_dir)
    if top is not None and not 0 <= top < page_height:
        raise InvalidLayoutError(f"top = {top} fora da página (0 a {page_height}).")
    visuals = _read_visuals(page_dir)

    fixed = set(keep_fixed or [])
    names = {_visual_name(path, data) for path, data in visuals}
    missing = sorted(fixed - names)
    if missing:
        raise VisualNotFoundError(missing[0], page_name)
    visuals = [(path, data) for path, data in visuals if _visual_name(path, data) not in fixed]

    # o layout é calculado numa página "encolhida" (sem a faixa de cima)
    # e depois deslocado pra baixo
    offset = 0.0 if top is None else max(top - _MARGIN, 0.0)
    layout_height = page_height - offset

    if not visuals:
        return {"page_name": page_name, "layout": layout, "visual_count": 0}

    if layout == "kpi_row":
        positions = _kpi_row_positions(visuals, page_width, layout_height)
    else:
        positions = _grid_positions(len(visuals), page_width, layout_height)

    for (visual_path, data), position in zip(visuals, positions):
        position = {**position, "y": position["y"] + offset}
        data["position"] = {**data.get("position", {}), **position}
        visual_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {"page_name": page_name, "layout": layout, "visual_count": len(visuals)}


def _read_page_size(page_dir: Path) -> tuple[float, float]:
    page_json_path = page_dir / "page.json"
    if page_json_path.is_file():
        data = json.loads(page_json_path.read_text(encoding="utf-8"))
        return data.get("width", 1280), data.get("height", 720)
    return 1280, 720


def _read_visuals(page_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    visuals_dir = page_dir / "visuals"
    if not visuals_dir.is_dir():
        return []
    visuals = []
    for visual_dir in sorted(d for d in visuals_dir.iterdir() if d.is_dir()):
        visual_json_path = visual_dir / "visual.json"
        if visual_json_path.is_file():
            data = json.loads(visual_json_path.read_text(encoding="utf-8"))
            visuals.append((visual_json_path, data))
    return visuals


def _visual_name(visual_json_path: Path, data: dict[str, Any]) -> str:
    return data.get("name") or visual_json_path.parent.name


def _visual_type(data: dict[str, Any]) -> str:
    return data.get("visual", {}).get("visualType", "")


def _grid_positions(count: int, page_width: float, page_height: float) -> list[dict[str, float]]:
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    cell_width = (page_width - _MARGIN * (columns + 1)) / columns
    cell_height = (page_height - _MARGIN * (rows + 1)) / rows

    positions = []
    for i in range(count):
        row, col = divmod(i, columns)
        positions.append(
            {
                "x": _MARGIN + col * (cell_width + _MARGIN),
                "y": _MARGIN + row * (cell_height + _MARGIN),
                "width": cell_width,
                "height": cell_height,
            }
        )
    return positions


def _kpi_row_positions(
    visuals: list[tuple[Path, dict[str, Any]]], page_width: float, page_height: float
) -> list[dict[str, float]]:
    """Cards numa faixa fixa no topo, os demais visuais numa grade
    ocupando o resto da altura da página. A ordem devolvida corresponde
    à ordem de `visuals` (cards primeiro, depois os demais), então o
    chamador precisa aplicar as posições na mesma ordem em que iterou
    `visuals` -- ver set_page_layout, que usa zip(visuals, positions)."""
    card_indices = [i for i, (_, data) in enumerate(visuals) if _visual_type(data) in _CARD_TYPES]
    other_indices = [i for i in range(len(visuals)) if i not in card_indices]

    kpi_row_height = min(120, page_height * 0.2) if card_indices else 0
    positions_by_index: dict[int, dict[str, float]] = {}

    if card_indices:
        card_width = (page_width - _MARGIN * (len(card_indices) + 1)) / len(card_indices)
        for order, idx in enumerate(card_indices):
            positions_by_index[idx] = {
                "x": _MARGIN + order * (card_width + _MARGIN),
                "y": _MARGIN,
                "width": card_width,
                "height": kpi_row_height - _MARGIN,
            }

    if other_indices:
        remaining_top = kpi_row_height + (_MARGIN if card_indices else 0)
        remaining_height = page_height - remaining_top
        grid = _grid_positions(len(other_indices), page_width, remaining_height)
        for order, idx in enumerate(other_indices):
            cell = grid[order]
            positions_by_index[idx] = {**cell, "y": cell["y"] + remaining_top}

    return [positions_by_index[i] for i in range(len(visuals))]
