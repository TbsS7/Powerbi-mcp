"""Layout de celular de uma página: um `mobile.json` por visual
(`visuals/<visual>/mobile.json`), com a posição do visual na tela do
celular. Não mexe no layout da área de trabalho (visual.json).

Fontes: doc oficial Microsoft Learn "Power BI Desktop project report
folder" (mobile.json = "visual mobile layout metadata, such as mobile
position and formatting") e schema oficial visualContainerMobileState/
2.3.0. Comparação com o Desktop (2026-09-29, layout montado pela UI):
tela de 324px de largura, visual solto em x=0 com largura 324, `z`
crescente, sem `tabOrder`, e o textbox leva uma cópia de
`objects.general` (o texto).

As ALTURAS por tipo (título 48, cartão 100 em dupla, slicer 120, demais
240) são escolha nossa, não vêm do Desktop -- só deixam o empilhamento
legível no celular.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from errors import MobileLayoutExistsError, PageNotFoundError, VisualNotFoundError
from visuals import project
from visuals.names import resolve_page_dir
from visuals.schema_urls import VISUAL_CONTAINER_MOBILE_SCHEMA

MOBILE_WIDTH = 324
_GAP = 8
_CARD_TYPES = ("card", "cardVisual")
_HEIGHTS = {"textbox": 48, "card": 100, "cardVisual": 100, "slicer": 120}
_DEFAULT_HEIGHT = 240


def set_mobile_layout(
    pbip_path: str,
    page_name: str,
    visuals: list[str] | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Empilha os visuais na tela do celular, na ordem de leitura da área
    de trabalho (de cima pra baixo, da esquerda pra direita) ou na ordem
    de `visuals`. Cartões seguidos ficam em dupla; o resto, na largura
    toda. Recusa se a página já tem layout de celular, a menos que
    `replace=True` (aí os visuais fora da lista saem do celular)."""
    report_dir = project.resolve_report_dir(pbip_path)
    page_dir = resolve_page_dir(project.get_definition_dir(report_dir) / "pages", page_name)
    if not page_dir.is_dir():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    all_visuals = _read_visuals(page_dir)
    if visuals is None:
        chosen = sorted(all_visuals, key=lambda n: (all_visuals[n]["position"]["y"], all_visuals[n]["position"]["x"]))
    else:
        missing = [n for n in visuals if n not in all_visuals]
        if missing:
            raise VisualNotFoundError(missing[0], page_name)
        chosen = list(visuals)

    existing = sorted(n for n in all_visuals if (page_dir / "visuals" / n / "mobile.json").is_file())
    if existing and not replace:
        raise MobileLayoutExistsError(
            f"A página '{page_name}' já tem layout de celular ({len(existing)} visuais). "
            "Pra refazer do zero, chame de novo com replace=True -- o layout atual será substituído."
        )

    placed = []
    y = 0.0
    pending_card: str | None = None
    for z, name in enumerate(chosen, start=1):
        visual_type = all_visuals[name]["visual"]["visualType"]
        height = _HEIGHTS.get(visual_type, _DEFAULT_HEIGHT)
        if visual_type in _CARD_TYPES:
            half = (MOBILE_WIDTH - _GAP) / 2
            if pending_card is None:
                position = {"x": 0, "y": y, "z": z, "width": half, "height": height}
                pending_card = name
            else:
                position = {"x": half + _GAP, "y": y, "z": z, "width": half, "height": height}
                pending_card = None
                y += height + _GAP
        else:
            if pending_card is not None:  # cartão sozinho na linha anterior
                y += _HEIGHTS["cardVisual"] + _GAP
                pending_card = None
            position = {"x": 0, "y": y, "z": z, "width": MOBILE_WIDTH, "height": height}
            y += height + _GAP
        placed.append((name, position))

    removed = [n for n in existing if n not in chosen]
    for name in removed:
        (page_dir / "visuals" / name / "mobile.json").unlink()
    for name, position in placed:
        mobile: dict[str, Any] = {"$schema": VISUAL_CONTAINER_MOBILE_SCHEMA, "position": position}
        general = all_visuals[name]["visual"].get("objects", {}).get("general")
        if all_visuals[name]["visual"]["visualType"] == "textbox" and general:
            mobile["objects"] = {"general": general}
        path = page_dir / "visuals" / name / "mobile.json"
        path.write_text(json.dumps(mobile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "page_name": page_name,
        "placed": [{"visual_name": n, "position": p} for n, p in placed],
        "removed": removed,
    }


def _read_visuals(page_dir: Path) -> dict[str, dict[str, Any]]:
    visuals_dir = page_dir / "visuals"
    if not visuals_dir.is_dir():
        return {}
    result = {}
    for visual_dir in sorted(d for d in visuals_dir.iterdir() if d.is_dir()):
        visual_json = visual_dir / "visual.json"
        if visual_json.is_file():
            result[visual_dir.name] = json.loads(visual_json.read_text(encoding="utf-8"))
    return result
