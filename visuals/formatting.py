"""Formatação de conteúdo de visual: rótulos de dado, legenda e eixos.

Fontes (regra do projeto -- nada inventado):
- ONDE fica: doc oficial de autoria de PBIR (microsoft/skills-for-fabric,
  `formatting.md` e `cartesian.md`): `visual.objects.<objeto>` é um ARRAY
  de `{"properties": {...}, "selector"?: {...}}`; a entrada sem
  `selector` é a formatação base do visual inteiro, entradas com
  `selector` (ex: `{"metadata": "<queryRef>"}`) formatam uma série
  específica. Estas tools só mexem na entrada base e preservam as outras.
- O QUE vale por tipo de visual: visuals/formatting_spec.json, GERADO do
  schema oficial de tema (scripts/generate_formatting_spec.py) -- nomes
  exatos das propriedades, valores válidos e limites. A doc avisa que
  "property names vary by visual type"; ex: o cartão não tem legenda nem
  `labels.show`, tabela/matriz/slicer não têm nenhum destes objetos.
- COMO escrever o valor: tabela de sufixos de literal da doc
  (formatting.md, "Literal Values"): booleano `"true"`, texto `"'...'"`,
  número `"11D"` (Double), inteiro `"2L"` (Long); cor em
  `{"solid": {"color": {"expr": {"Literal": {"Value": "'#hex'"}}}}}`.
  `labelDisplayUnits` segue o exemplo da doc (`"1000D"`, Double) e
  `labelPrecision` também (`"2L"`, Long).

CONFIRMADO AO VIVO (2026-09-25, ver README "Validação real"): rótulos
fora da barra em milhões com 1 casa, título e unidade do eixo de
valores, linhas de grade desligadas, legenda embaixo centralizada sem
título -- tudo aplicado pelo Desktop exatamente como escrito.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from errors import InvalidVisualFormattingError, PageNotFoundError
from visuals import project
from visuals.names import resolve_page_dir
from visuals.visual_writer import _resolve_visual_dir

_SPEC_PATH = Path(__file__).with_name("formatting_spec.json")
_SPEC: dict[str, Any] = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))

_AXIS_OBJECTS = {"category": "categoryAxis", "value": "valueAxis"}
_AXIS_TYPES = {"categorical": "Categorical", "continuous": "Scalar"}
_DISPLAY_UNITS = {
    "auto": 0, "none": 1, "thousands": 1000, "millions": 1000000,
    "billions": 1000000000, "trillions": 1000000000000,
}
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
# Sufixo por propriedade inteira (ver docstring): doc usa D em
# labelDisplayUnits e L em labelPrecision.
_INTEGER_SUFFIX = {"labelDisplayUnits": "D", "labelPrecision": "L", "dataLabelDisplayUnits": "D"}


def set_visual_data_labels(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    show: bool | None = None,
    position: str | None = None,
    display_units: str | None = None,
    precision: int | None = None,
    font_size: float | None = None,
    color: str | None = None,
    style: str | None = None,
    show_center_value: bool | None = None,
) -> dict[str, Any]:
    """Rótulos de dado (o número em cima de cada barra/fatia/ponto).
    `style` (rosca/pizza) = o que o rótulo mostra ("Percent of total",
    "Category", ...); `show_center_value` (rosca) = número grande no meio."""
    updates = {
        "show": show,
        "labelPosition": position,
        "labelDisplayUnits": _display_units(display_units),
        "labelPrecision": precision,
        "fontSize": font_size,
        "color": color,
        "labelStyle": style,
    }
    result: dict[str, Any] = {}
    if show_center_value is not None:
        result = _apply(pbip_path, page_name, visual_name, "centerValue", {"show": show_center_value})
    if any(v is not None for v in updates.values()) or show_center_value is None:
        result = _apply(pbip_path, page_name, visual_name, "labels", updates)
    if show_center_value is not None:
        result.setdefault("changed", {})["show_center_value"] = show_center_value
    return result


def set_visual_legend(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    show: bool | None = None,
    position: str | None = None,
    show_title: bool | None = None,
    title: str | None = None,
    font_size: float | None = None,
) -> dict[str, Any]:
    """Legenda do visual."""
    updates = {
        "show": show,
        "position": position,
        "showTitle": show_title,
        "titleText": title,
        "fontSize": font_size,
    }
    return _apply(pbip_path, page_name, visual_name, "legend", updates)


def set_visual_axis(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    axis: str,
    show: bool | None = None,
    show_title: bool | None = None,
    title: str | None = None,
    font_size: float | None = None,
    invert: bool | None = None,
    start: float | None = None,
    end: float | None = None,
    display_units: str | None = None,
    gridlines: bool | None = None,
    min_category_width: float | None = None,
    axis_type: str | None = None,
) -> dict[str, Any]:
    """Eixo de categorias (`axis="category"`) ou de valores
    (`axis="value"`). Num gráfico de barras HORIZONTAL o eixo de
    categorias é o vertical."""
    if axis not in _AXIS_OBJECTS:
        raise InvalidVisualFormattingError(
            f"axis '{axis}' inválido. Use 'category' (eixo das categorias) ou 'value' (eixo dos valores)."
        )
    updates = {
        "show": show,
        "showAxisTitle": show_title,
        "titleText": title,
        "fontSize": font_size,
        "invertAxis": invert,
        "start": start,
        "end": end,
        "labelDisplayUnits": _display_units(display_units),
        "gridlineShow": gridlines,
        # "Minimum category width": menor = cabem mais categorias sem barra de rolagem
        "preferredCategoryWidth": min_category_width,
        "axisType": _AXIS_TYPES.get(axis_type) if axis_type is not None else None,
    }
    if axis_type is not None and axis_type not in _AXIS_TYPES:
        raise InvalidVisualFormattingError(
            f"axis_type '{axis_type}' inválido. Use 'categorical' (um rótulo por categoria) ou 'continuous'."
        )
    return _apply(pbip_path, page_name, visual_name, _AXIS_OBJECTS[axis], updates)


# --- texto de textbox e moldura (container) -----------------------------------
#
# Fontes: doc oficial textbox.md (skills-for-fabric) -- título com
# `textStyle` {fontFamily, fontSize "24px"/"20pt", fontWeight "bold",
# color "#hex"} por textRun e `horizontalTextAlignment` por parágrafo, e
# `visualContainerObjects.background/border` no mesmo exemplo;
# formatting.md (tabela VCO: background = show/color/transparency,
# border = show/color/radius/width); schema oficial de tema (fontStyle
# "italic", textDecoration "underline", fontSize 8-60).
# CONFIRMADO AO VIVO (2026-09-27): "center" em horizontalTextAlignment
# (a doc só mostrava "left"), tamanho/negrito/cor por linha, e fundo +
# borda arredondada do container -- tudo aplicado pelo Desktop como
# escrito. "right" segue a mesma convenção, mas não foi testado ao vivo.

_TEXT_ALIGNMENTS = ("left", "center", "right")
_FONT_SIZE_RANGE = (8, 60)  # definitions.fontSize do schema oficial de tema


def set_textbox_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    font_size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    color: str | None = None,
    font_family: str | None = None,
    alignment: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    """Formata o texto de um textbox: tamanho (pt), negrito, itálico,
    sublinhado, cor, fonte e alinhamento. Aplica em todas as linhas, ou
    só na linha `line` (1 = primeira). Só o que for passado muda; o
    texto em si não é tocado. update_visual com `text` novo recria o
    textbox com o estilo padrão -- aplique o estilo depois."""
    if all(v is None for v in (font_size, bold, italic, underline, color, font_family, alignment)):
        raise InvalidVisualFormattingError("Nenhuma propriedade de texto foi informada.")
    if font_size is not None:
        _check_range("font_size", font_size, *_FONT_SIZE_RANGE)
    if color is not None:
        _check_hex(color)
    if alignment is not None and alignment not in _TEXT_ALIGNMENTS:
        raise InvalidVisualFormattingError(
            f"alignment '{alignment}' inválido -- use um de: {', '.join(_TEXT_ALIGNMENTS)}."
        )

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    if instance["visual"]["visualType"] != "textbox":
        raise InvalidVisualFormattingError(
            f"set_textbox_style só funciona em textbox (o visual '{visual_name}' é "
            f"'{instance['visual']['visualType']}'). Pra título de gráfico, use set_visual_title."
        )

    paragraphs = instance["visual"]["objects"]["general"][0]["properties"]["paragraphs"]
    if line is not None and not 1 <= line <= len(paragraphs):
        raise InvalidVisualFormattingError(
            f"line {line} não existe -- o textbox tem {len(paragraphs)} linha(s)."
        )
    targets = [line] if line is not None else list(range(1, len(paragraphs) + 1))

    for index in targets:
        paragraph = paragraphs[index - 1]
        if alignment is not None:
            paragraph["horizontalTextAlignment"] = alignment
        for run in paragraph.get("textRuns", []):
            style = run.setdefault("textStyle", {})
            if font_size is not None:
                style["fontSize"] = f"{_number_text(float(font_size))}pt"
            if bold is not None:
                style["fontWeight"] = "bold" if bold else "normal"
            if italic is not None:
                style["fontStyle"] = "italic" if italic else "normal"
            if underline is not None:
                if underline:
                    style["textDecoration"] = "underline"
                else:
                    style.pop("textDecoration", None)
            if color is not None:
                style["color"] = color
            if font_family is not None:
                style["fontFamily"] = font_family

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name, "lines": targets}


def set_visual_container_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    background_show: bool | None = None,
    background_color: str | None = None,
    background_transparency: float | None = None,
    border_show: bool | None = None,
    border_color: str | None = None,
    border_width: float | None = None,
    border_radius: float | None = None,
    padding: float | None = None,
) -> dict[str, Any]:
    """Moldura de QUALQUER visual (`visualContainerObjects`): fundo
    (mostrar, cor, transparência 0-100), borda (mostrar, cor, largura,
    arredondamento) e `padding` (espaço interno, px, os 4 lados --
    schema oficial de tema, commonCards.padding). Informar uma cor de
    fundo/borda liga o fundo/borda automaticamente, a menos que `*_show`
    seja passado explicitamente."""
    background: dict[str, Any] = {}
    border: dict[str, Any] = {}
    spacing: dict[str, Any] = {}
    if padding is not None:
        _check_range("padding", padding, 0, None)
        spacing = {side: _literal(f"{_number_text(float(padding))}D") for side in ("top", "bottom", "left", "right")}

    if background_color is not None:
        _check_hex(background_color)
        background["color"] = {"solid": {"color": _literal(f"'{background_color}'")}}
    if background_transparency is not None:
        _check_range("background_transparency", background_transparency, 0, 100)
        background["transparency"] = _literal(f"{_number_text(float(background_transparency))}D")
    if background_show is not None:
        background["show"] = _literal("true" if background_show else "false")
    elif background_color is not None:
        background["show"] = _literal("true")

    if border_color is not None:
        _check_hex(border_color)
        border["color"] = {"solid": {"color": _literal(f"'{border_color}'")}}
    for prop, value in (("width", border_width), ("radius", border_radius)):
        if value is not None:
            _check_range(f"border_{prop}", value, 0, None)
            border[prop] = _literal(f"{_number_text(float(value))}D")
    if border_show is not None:
        border["show"] = _literal("true" if border_show else "false")
    elif border_color is not None:
        border["show"] = _literal("true")

    if not background and not border and not spacing:
        raise InvalidVisualFormattingError("Nenhuma propriedade de fundo/borda/padding foi informada.")

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    vco = instance["visual"].setdefault("visualContainerObjects", {})
    for object_name, props in (("background", background), ("border", border), ("padding", spacing)):
        if not props:
            continue
        entries = vco.setdefault(object_name, [])
        base = next((e for e in entries if "selector" not in e), None)
        if base is None:
            base = {"properties": {}}
            entries.insert(0, base)
        base.setdefault("properties", {}).update(props)

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "visual_name": visual_name,
        "page_name": page_name,
        "visual_type": instance["visual"]["visualType"],
        "changed": sorted(
            [f"background.{k}" for k in background] + [f"border.{k}" for k in border]
            + [f"padding.{k}" for k in spacing]
        ),
    }


def set_visual_alt_text(pbip_path: str, page_name: str, visual_name: str, text: str) -> dict[str, Any]:
    """Texto alternativo do visual (lido por leitor de tela):
    `visualContainerObjects.general[].properties.altText` -- doc oficial
    conditional-formatting.md e schema visualConfiguration/2.3.0. Texto
    vazio remove."""
    literal = _literal("'" + text.replace("'", "''") + "'") if text else None
    return _set_vco_property(pbip_path, page_name, visual_name, "general", "altText", literal) | {
        "alt_text": text or None
    }


def set_visual_tooltip_page(
    pbip_path: str, page_name: str, visual_name: str, tooltip_page: str | None
) -> dict[str, Any]:
    """Liga o visual a uma página de tooltip (criada com
    create_report_page(tooltip=True)): ao passar o mouse, aparece a
    página em vez da dica padrão. `None` volta pra dica padrão.

    Grava só `visualTooltip.section` = nome da página, exatamente como o
    Desktop gravou ao fazer isso pela UI (comparação de 2026-09-29 --
    sem `type`/`show`)."""
    literal = None
    if tooltip_page:
        report_dir = project.resolve_report_dir(pbip_path)
        target = resolve_page_dir(project.get_definition_dir(report_dir) / "pages", tooltip_page) / "page.json"
        if not target.is_file():
            raise PageNotFoundError(f"Página '{tooltip_page}' não existe em '{report_dir}'.")
        if json.loads(target.read_text(encoding="utf-8")).get("type") != "Tooltip":
            raise InvalidVisualFormattingError(
                f"A página '{tooltip_page}' não é uma página de tooltip -- crie uma com "
                "create_report_page(tooltip=True) ou ative 'Permitir uso como dica de ferramenta' nela."
            )
        literal = _literal(f"'{tooltip_page}'")
    return _set_vco_property(pbip_path, page_name, visual_name, "visualTooltip", "section", literal) | {
        "tooltip_page": tooltip_page or None
    }


def set_visual_tooltip_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    label_color: str | None = None,
    value_color: str | None = None,
    background_color: str | None = None,
) -> dict[str, Any]:
    """Cores da dica de ferramenta (a caixa que aparece ao passar o mouse):
    texto do rótulo, texto do valor e fundo.

    Formato copiado do Desktop (técnica de comparação, 2026-09-30): o
    usuário formatou a dica pela UI e o Desktop gravou
    `visualContainerObjects.visualTooltip` com `themedTitleFontColor`,
    `themedValueFontColor` e `themedBackground` -- NÃO as versões sem
    "themed" (`titleFontColor`/`background`), que também existem no schema
    de tema. Gravamos o hex em `Literal` (o Desktop gravou `ThemeDataColor`
    porque a cor foi escolhida da paleta do tema)."""
    colors = {
        "themedTitleFontColor": label_color,
        "themedValueFontColor": value_color,
        "themedBackground": background_color,
    }
    colors = {k: v for k, v in colors.items() if v is not None}
    if not colors:
        raise InvalidVisualFormattingError("Informe label_color, value_color e/ou background_color.")
    for color in colors.values():
        _check_hex(color)

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    entries = instance["visual"].setdefault("visualContainerObjects", {}).setdefault("visualTooltip", [])
    base = next((e for e in entries if "selector" not in e), None)
    if base is None:
        base = {"properties": {}}
        entries.insert(0, base)
    base.setdefault("properties", {}).update(
        {prop: {"solid": {"color": _literal(f"'{color}'")}} for prop, color in colors.items()}
    )
    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name,
            "changed": {"label_color": label_color, "value_color": value_color, "background_color": background_color}}


def _set_vco_property(
    pbip_path: str, page_name: str, visual_name: str, object_name: str, prop: str, value: dict[str, Any] | None
) -> dict[str, Any]:
    """Grava (ou remove, com `value=None`) uma propriedade na entrada base
    de `visualContainerObjects.<object_name>`; limpa a entrada/objeto que
    ficar vazio."""
    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    vco = instance["visual"].setdefault("visualContainerObjects", {})
    entries = vco.setdefault(object_name, [])
    base = next((e for e in entries if "selector" not in e), None)
    if value is not None:
        if base is None:
            base = {"properties": {}}
            entries.insert(0, base)
        base.setdefault("properties", {})[prop] = value
    elif base is not None:
        base.get("properties", {}).pop(prop, None)
        if not base.get("properties"):
            entries.remove(base)
    if not entries:
        vco.pop(object_name)
    if not vco:
        instance["visual"].pop("visualContainerObjects")

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name, "visual_type": instance["visual"]["visualType"]}


# --- slicer de botões (advancedSlicerVisual) --------------------------------
#
# Fontes: schema oficial de tema (visual-advancedSlicerVisual) pros nomes;
# doc button-part-02.md pro "dual-entry" (`show` numa entrada sem
# selector, estilo por estado em entradas com selector -- junto numa só
# "silently fail[s]"); tema base do próprio Desktop (Fluent2-CY26SU08)
# pros ids de estado: "default" e "selection:selected" (a doc
# formatting.md abrevia pra "selected") e `layout` sem selector.
# NÃO confirmado ao vivo ainda -- ver README "Validação real".
_BUTTON_DEFAULT = {"id": "default"}
_BUTTON_SELECTED = {"id": "selection:selected"}


def set_button_slicer_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    single_select: bool | None = None,
    force_selection: bool | None = None,
    tiles_per_row: int | None = None,
    rows: int | None = None,
    tile_spacing: int | None = None,
    tile_color: str | None = None,
    tile_transparency: float | None = None,
    selected_tile_color: str | None = None,
    selected_tile_transparency: float | None = None,
    text_color: str | None = None,
    selected_text_color: str | None = None,
    text_size: float | None = None,
    text_bold: bool | None = None,
    text_transparency: float | None = None,
    outline_show: bool | None = None,
    outline_color: str | None = None,
    outline_weight: float | None = None,
    outline_transparency: float | None = None,
    selected_outline_color: str | None = None,
    corner_radius: int | None = None,
) -> dict[str, Any]:
    """Formata um slicer de botões: seleção única, ladrilhos por linha,
    cor/transparência do ladrilho e do texto (normal e selecionado),
    contorno e cantos. Tudo validado antes de gravar."""
    def color(value):
        _check_hex(value)
        return {"solid": {"color": _literal(f"'{value}'")}}

    def number(name, value, low, high):
        _check_range(name, value, low, high)
        return _literal(f"{_number_text(float(value))}D")

    def integer(name, value, low):
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidVisualFormattingError(f"{name} precisa ser um número inteiro.")
        _check_range(name, value, low, None)
        return _literal(f"{value}L")

    def boolean(value):
        return _literal("true" if value else "false")

    # (objeto, selector) -> propriedades
    changes: dict[tuple[str, str | None], dict[str, Any]] = {}

    def put(obj, selector, prop, encoded):
        changes.setdefault((obj, selector), {})[prop] = encoded

    if single_select is not None:
        put("selection", None, "singleSelect", boolean(single_select))
    if force_selection is not None:
        # "Forçar seleção" do Desktop -- sempre um item marcado
        put("selection", None, "strictSingleSelect", boolean(force_selection))
    # achado ao vivo: `maxTiles` NÃO é "ladrilhos por linha" (com 5 o Desktop
    # manteve a grade padrão de 3 colunas); columnCount/rowCount com a
    # grade automática desligada (schema oficial de tema).
    if tiles_per_row is not None:
        put("layout", None, "columnCount", integer("tiles_per_row", tiles_per_row, 1))
        put("layout", None, "autoGrid", boolean(False))
    if rows is not None:
        put("layout", None, "rowCount", integer("rows", rows, 1))
        put("layout", None, "autoGrid", boolean(False))
    if tile_spacing is not None:
        put("layout", None, "cellPadding", integer("tile_spacing", tile_spacing, 0))
    if tile_color is not None:
        put("fillCustom", "default", "fillColor", color(tile_color))
    if tile_transparency is not None:
        put("fillCustom", "default", "transparency", number("tile_transparency", tile_transparency, 0, 100))
    if selected_tile_color is not None:
        put("fillCustom", "selected", "fillColor", color(selected_tile_color))
    if selected_tile_transparency is not None:
        put("fillCustom", "selected", "transparency",
            number("selected_tile_transparency", selected_tile_transparency, 0, 100))
    if any(k[0] == "fillCustom" for k in changes):
        put("fillCustom", None, "show", boolean(True))
    if text_color is not None:
        put("value", "default", "fontColor", color(text_color))
    if text_size is not None:
        put("value", "default", "fontSize", number("text_size", text_size, 8, 60))
    if text_bold is not None:
        put("value", "default", "bold", boolean(text_bold))
    if text_transparency is not None:
        put("value", "default", "transparency", number("text_transparency", text_transparency, 0, 100))
    if selected_text_color is not None:
        put("value", "selected", "fontColor", color(selected_text_color))
    if outline_show is not None:
        put("outline", None, "show", boolean(outline_show))
    if outline_color is not None:
        put("outline", "default", "lineColor", color(outline_color))
    if outline_transparency is not None:
        put("outline", "default", "transparency", number("outline_transparency", outline_transparency, 0, 100))
    if outline_weight is not None:
        put("outline", "default", "weight", number("outline_weight", outline_weight, 0, 20))
    if selected_outline_color is not None:
        put("outline", "selected", "lineColor", color(selected_outline_color))
        # sem isso, um contorno transparente no normal esconde o do selecionado
        put("outline", "selected", "transparency", _literal("0D"))
        # achado ao vivo: o tema base do Desktop (Fluent2) põe outline.show
        # = false NO ESTADO selecionado, e isso vence o `show` geral
        put("outline", "selected", "show", boolean(True))
    if corner_radius is not None:
        put("shapeCustomRectangle", "default", "tileShape", _literal("'rectangleRoundedByPixel'"))
        put("shapeCustomRectangle", "default", "rectangleRoundedCurve", integer("corner_radius", corner_radius, 0))
    if not changes:
        raise InvalidVisualFormattingError("Nenhuma propriedade do slicer de botões foi informada.")

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    if instance["visual"]["visualType"] != "advancedSlicerVisual":
        raise InvalidVisualFormattingError(
            f"O visual '{visual_name}' é do tipo '{instance['visual']['visualType']}' -- esta tool é só pro "
            "slicer de botões (advancedSlicerVisual). Pro slicer comum, use set_slicer_config."
        )

    selectors = {None: None, "default": _BUTTON_DEFAULT, "selected": _BUTTON_SELECTED}
    order = [None, "default", "selected"]
    objects = instance["visual"].setdefault("objects", {})
    for (obj, key), props in changes.items():
        entries = objects.setdefault(obj, [])
        selector = selectors[key]
        entry = next((e for e in entries if e.get("selector") == selector), None)
        if entry is None:
            entry = {"properties": {}}
            if selector is not None:
                entry["selector"] = dict(selector)
            entries.append(entry)
        entry.setdefault("properties", {}).update(props)
        entries.sort(key=lambda e: order.index(next(
            (k for k, v in selectors.items() if v == e.get("selector")), None
        )) if e.get("selector") in selectors.values() else len(order))

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "visual_name": visual_name,
        "page_name": page_name,
        "changed": sorted(f"{obj}{'' if key is None else '[' + key + ']'}.{prop}"
                          for (obj, key), props in changes.items() for prop in props),
    }


# Nome do objeto/propriedade por tipo de cartão:(objeto do valor,
# objeto do texto de baixo, propriedade de cor, selector). cardVisual:
# doc oficial card-part-03.md -- `value`/`label` exigem
# `selector: {"id": "default"}`, sem ele a formatação é ignorada em
# silêncio. card (legado): schema oficial de tema, entrada base sem
# selector.
_CARD_OBJECTS: dict[str, tuple[str, str, str, dict[str, str] | None]] = {
    "cardVisual": ("value", "label", "fontColor", {"id": "default"}),
    "card": ("labels", "categoryLabels", "color", None),
}


def set_card_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    value_font_size: float | None = None,
    value_color: str | None = None,
    value_bold: bool | None = None,
    value_font_family: str | None = None,
    value_display_units: str | None = None,
    value_precision: int | None = None,
    label_show: bool | None = None,
    label_font_size: float | None = None,
    label_color: str | None = None,
    label_bold: bool | None = None,
    label_text: str | None = None,
    card_background_show: bool | None = None,
    card_background_color: str | None = None,
    card_background_transparency: float | None = None,
    outline_show: bool | None = None,
    image_path: str | None = None,
    image_show: bool | None = None,
) -> dict[str, Any]:
    """Cartão (`cardVisual` atual ou `card` legado): valor principal e o
    texto de baixo (nome da medida). Tudo é validado antes de gravar --
    um valor inválido não deixa nada pela metade.

    Só no cardVisual: preenchimento interno (`fillCustom`) e borda
    interna (`outline`), com selector id default (doc card-part-03.md).
    Achado na réplica de dashboard (2026-09-30): com o fundo da moldura
    desligado, o cardVisual ainda mostra uma caixa branca atrás do
    número -- é esse preenchimento interno."""
    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]
    if visual_type not in _CARD_OBJECTS:
        raise InvalidVisualFormattingError(
            f"O visual '{visual_name}' é do tipo '{visual_type}', não um cartão "
            f"(set_card_style aceita {', '.join(sorted(_CARD_OBJECTS))})."
        )
    value_object, label_object, color_prop, selector = _CARD_OBJECTS[visual_type]
    if label_text is not None and visual_type == "card":
        raise InvalidVisualFormattingError(
            "Trocar o texto de baixo (label_text) só é possível no cartão atual (cardVisual); "
            "o cartão legado ('card') sempre mostra o nome da medida."
        )
    inner = (card_background_show, card_background_color, card_background_transparency, outline_show)
    if visual_type == "card" and any(v is not None for v in inner):
        raise InvalidVisualFormattingError(
            "Preenchimento/borda internos só existem no cartão atual (cardVisual); no cartão "
            "legado ('card'), use set_visual_container_style pro fundo e a borda."
        )
    if visual_type == "card" and (image_path is not None or image_show is not None):
        raise InvalidVisualFormattingError(
            "Imagem/ícone dentro do cartão só existe no cartão atual (cardVisual); no cartão "
            "legado ('card'), use add_image por cima dele."
        )
    if card_background_show is None and card_background_color is not None:
        card_background_show = True

    updates = {
        value_object: {
            "fontSize": value_font_size, color_prop: value_color, "bold": value_bold,
            "fontFamily": value_font_family, "labelDisplayUnits": _display_units(value_display_units),
            "labelPrecision": value_precision,
        },
        label_object: {
            "show": label_show, "fontSize": label_font_size, color_prop: label_color,
            "bold": label_bold, "text": label_text,
        },
    }
    if visual_type == "cardVisual":
        updates["fillCustom"] = {
            "show": card_background_show, "fillColor": card_background_color,
            "transparency": card_background_transparency,
        }
        updates["outline"] = {"show": outline_show}
    encoded: dict[str, dict[str, Any]] = {}
    for object_name, props in updates.items():
        allowed = _SPEC.get(visual_type, {}).get(object_name, {})
        changes = {prop: value for prop, value in props.items() if value is not None}
        if changes:
            encoded[object_name] = {
                prop: _encode(visual_type, object_name, prop, value, allowed) for prop, value in changes.items()
            }
    # Imagem/ícone no cardVisual: formato copiado do que o Desktop gravou
    # (comparação de 2026-09-30) -- objeto `cardImage` (não `image`), `show` +
    # `image.image.{name, url, scaling}` na mesma entrada com selector default.
    if image_path is not None:
        source = _check_image_file(image_path)
        report_dir = project.resolve_report_dir(pbip_path)
        resource_name, _ = _register_image(report_dir, project.get_definition_dir(report_dir), source)
        encoded["cardImage"] = {
            "show": _literal("true" if image_show is not False else "false"),
            "image": {"image": {
                "name": _literal("'" + source.name.replace("'", "''") + "'"),
                "url": {"expr": {"ResourcePackageItem": {
                    "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": resource_name,
                }}},
                "scaling": _literal("'Fit'"),
            }},
        }
    elif image_show is not None:
        encoded["cardImage"] = {"show": _literal("true" if image_show else "false")}
    if not encoded:
        raise InvalidVisualFormattingError("Nenhuma propriedade de cartão foi informada.")

    objects = instance["visual"].setdefault("objects", {})
    for object_name, props in encoded.items():
        entries = objects.setdefault(object_name, [])
        base = next((e for e in entries if e.get("selector") == selector), None)
        if base is None:
            base = {"properties": {}}
            if selector is not None:
                base["selector"] = dict(selector)
            entries.insert(0, base)
        base.setdefault("properties", {}).update(props)

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "visual_name": visual_name,
        "page_name": page_name,
        "visual_type": visual_type,
        "changed": sorted(f"{name}.{prop}" for name, props in encoded.items() for prop in props),
    }


def set_page_background(
    pbip_path: str,
    page_name: str,
    color: str | None = None,
    transparency: float | None = None,
    wallpaper_color: str | None = None,
    wallpaper_transparency: float | None = None,
) -> dict[str, Any]:
    """Cor de fundo da página: a tela atrás dos visuais (`background`) e
    o papel de parede fora dela (`outspace`), em `page.json -> objects`.

    Fonte: doc oficial page-formatting.md (skills-for-fabric) -- cada um
    é `[{"properties": {"color": ..., "transparency": "<n>D"}}]`, SEM
    `show` (o schema page/1.4.0 recusa). A transparência padrão da tela
    no Desktop é 100%, então passar só a cor sem transparência grava
    transparência 0 (senão a cor não apareceria)."""
    layers = {
        "background": _page_layer("color", color, "transparency", transparency),
        "outspace": _page_layer("wallpaper_color", wallpaper_color, "wallpaper_transparency", wallpaper_transparency),
    }
    if not any(layers.values()):
        raise InvalidVisualFormattingError("Nenhuma cor/transparência de fundo foi informada.")

    report_dir = project.resolve_report_dir(pbip_path)
    page_dir = resolve_page_dir(project.get_definition_dir(report_dir) / "pages", page_name)
    page_json_path = page_dir / "page.json"
    if not page_json_path.is_file():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    objects = page.setdefault("objects", {})
    for object_name, props in layers.items():
        if not props:
            continue
        entries = objects.setdefault(object_name, [])
        base = next((e for e in entries if "selector" not in e), None)
        if base is None:
            base = {"properties": {}}
            entries.insert(0, base)
        base.setdefault("properties", {}).update(props)

    page_json_path.write_text(json.dumps(page, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "page_name": page_name,
        "changed": sorted(f"{name}.{prop}" for name, props in layers.items() for prop in props),
    }


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg"}
_IMAGE_SCALING = ("Fit", "Fill", "Stretch")
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


def set_page_background_image(
    pbip_path: str,
    page_name: str,
    image_path: str | None,
    scaling: str = "Fit",
    transparency: float = 0,
    wallpaper: bool = False,
) -> dict[str, Any]:
    """Imagem de fundo da página (tela) ou do papel de parede
    (`wallpaper=True`). `image_path=None` tira a imagem (a cor fica).

    Fontes: doc oficial page-formatting.md ("Background Images") e
    image.md (skills-for-fabric) -- ver tests/test_page_background_image.py.
    A imagem é copiada pra StaticResources/RegisteredResources/ com um
    sufixo numérico único (como o Desktop faz), registrada como item
    "Image" em report.json, e referenciada por ResourcePackageItem dentro
    de `image.image` (aninhado -- achatado "silently fail[s] to render",
    diz a doc). A mesma imagem já registrada é reaproveitada, sem cópia
    duplicada."""
    if scaling not in _IMAGE_SCALING:
        raise InvalidVisualFormattingError(
            f"scaling '{scaling}' inválido -- use 'Fit' (ajustar, sem cortar), 'Fill' "
            "(preencher, pode cortar) ou 'Stretch' (esticar)."
        )
    _check_range("transparency", transparency, 0, 100)

    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_json_path = resolve_page_dir(definition_dir / "pages", page_name) / "page.json"
    if not page_json_path.is_file():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    object_name = "outspace" if wallpaper else "background"
    result: dict[str, Any] = {"page_name": page_name, "target": "wallpaper" if wallpaper else "canvas"}

    if image_path is None:
        image_property = None
    else:
        source = _check_image_file(image_path)
        resource_name, reused = _register_image(report_dir, definition_dir, source)
        image_property = {"image": {
            "name": _literal("'" + source.name.replace("'", "''") + "'"),
            "url": {"expr": {"ResourcePackageItem": {
                "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": resource_name,
            }}},
            "scaling": _literal(f"'{scaling}'"),
        }}
        result.update(resource_name=resource_name, reused=reused, scaling=scaling)

    page = json.loads(page_json_path.read_text(encoding="utf-8"))
    objects = page.setdefault("objects", {})
    entries = objects.setdefault(object_name, [])
    base = next((e for e in entries if "selector" not in e), None)
    if image_property is not None:
        if base is None:
            base = {"properties": {}}
            entries.insert(0, base)
        base.setdefault("properties", {})["image"] = image_property
        base["properties"]["transparency"] = _literal(f"{_number_text(float(transparency))}D")
    elif base is not None:
        base.get("properties", {}).pop("image", None)
        if not base.get("properties"):
            entries.remove(base)
    if not entries:
        objects.pop(object_name)
    if not objects:
        page.pop("objects")
    page_json_path.write_text(json.dumps(page, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def _check_image_file(image_path: str) -> Path:
    source = Path(image_path)
    if not source.is_file():
        raise InvalidVisualFormattingError(f"Imagem '{image_path}' não encontrada.")
    if source.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise InvalidVisualFormattingError(
            f"'{source.name}' não é uma imagem suportada (use {', '.join(sorted(_IMAGE_EXTENSIONS))})."
        )
    if source.stat().st_size > _MAX_IMAGE_BYTES:
        raise InvalidVisualFormattingError(f"'{source.name}' passa de 20 MB -- reduza a imagem.")
    return source


# Nomes que o usuário vê na tela -> valor interno de imageScalingType. O
# schema oficial de tema (visual-image) tem os nomes TROCADOS: "Normal" é
# o "Fit" (Ajustar) da tela, "Fit" é o "Stretch" (Esticar).
_IMAGE_FIT = {"fit": "Normal", "stretch": "Fit", "fill": "Fill"}


def add_image(
    pbip_path: str,
    page_name: str,
    image_path: str,
    x: float,
    y: float,
    width: float,
    height: float,
    fit: str | None = None,
) -> dict[str, Any]:
    """Visual "Imagem" a partir de um arquivo do usuário (ícone, logo) --
    doc oficial image.md, "Local file path to the image": `general.
    imageUrl` = ResourcePackageItem; o arquivo é copiado e registrado como
    em set_page_background_image (imagem igual já registrada é
    reaproveitada). Vai por cima dos visuais que já existem."""
    import uuid

    from visuals.schema_urls import VISUAL_CONTAINER_SCHEMA
    from visuals.visual_writer import _next_layer

    if fit is not None and fit not in _IMAGE_FIT:
        raise InvalidVisualFormattingError(
            f"fit '{fit}' inválido -- use 'fit' (ajustar, sem cortar), 'stretch' (esticar) ou 'fill' (preencher)."
        )
    source = _check_image_file(image_path)
    report_dir = project.resolve_report_dir(pbip_path)
    definition_dir = project.get_definition_dir(report_dir)
    page_dir = resolve_page_dir(definition_dir / "pages", page_name)
    if not (page_dir / "page.json").is_file():
        raise PageNotFoundError(f"Página '{page_name}' não existe em '{report_dir}'.")

    resource_name, reused = _register_image(report_dir, definition_dir, source)
    objects: dict[str, Any] = {"general": [{"properties": {"imageUrl": {"expr": {"ResourcePackageItem": {
        "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": resource_name,
    }}}}}]}
    if fit is not None:
        objects["imageScaling"] = [{"properties": {"imageScalingType": _literal(f"'{_IMAGE_FIT[fit]}'")}}]

    visual_name = uuid.uuid4().hex[:20]
    layer = _next_layer(page_dir)
    instance = {
        "$schema": VISUAL_CONTAINER_SCHEMA,
        "name": visual_name,
        "position": {"x": x, "y": y, "z": layer, "width": width, "height": height, "tabOrder": layer},
        "visual": {"visualType": "image", "objects": objects, "drillFilterOtherVisuals": True},
    }
    visual_dir = page_dir / "visuals" / visual_name
    visual_dir.mkdir(parents=True)
    (visual_dir / "visual.json").write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name, "resource_name": resource_name, "reused": reused}


def _register_image(report_dir: Path, definition_dir: Path, source: Path) -> tuple[str, bool]:
    """Copia a imagem pra RegisteredResources e registra em report.json;
    se a mesma imagem (mesmos bytes) já estiver registrada, reaproveita."""
    import time

    resources_dir = report_dir / "StaticResources" / "RegisteredResources"
    report_json_path = definition_dir / "report.json"
    report = json.loads(report_json_path.read_text(encoding="utf-8"))
    packages = report.setdefault("resourcePackages", [])
    package = next((p for p in packages if p.get("type") == "RegisteredResources"), None)
    content = source.read_bytes()

    if package is not None:
        for item in package.get("items", []):
            existing = resources_dir / item.get("path", "")
            if item.get("type") == "Image" and existing.is_file() and existing.read_bytes() == content:
                return item["name"], True

    stem = re.sub(r"[^A-Za-z0-9_-]", "_", source.stem) or "imagem"
    resource_name = f"{stem}{time.time_ns()}{source.suffix.lower()}"
    resources_dir.mkdir(parents=True, exist_ok=True)
    (resources_dir / resource_name).write_bytes(content)

    if package is None:
        package = {"name": "RegisteredResources", "type": "RegisteredResources", "items": []}
        packages.append(package)
    package.setdefault("items", []).append({"name": resource_name, "path": resource_name, "type": "Image"})
    report_json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return resource_name, False


def _page_layer(color_name: str, color: str | None, transparency_name: str, transparency: float | None) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if color is not None:
        _check_hex(color)
        props["color"] = {"solid": {"color": _literal(f"'{color}'")}}
        if transparency is None:
            transparency = 0
    if transparency is not None:
        _check_range(transparency_name, transparency, 0, 100)
        props["transparency"] = _literal(f"{_number_text(float(transparency))}D")
    return props


def _check_hex(color: str) -> None:
    if not isinstance(color, str) or not _HEX_COLOR.match(color):
        raise InvalidVisualFormattingError(f"Cor '{color}' inválida -- use hexadecimal com '#', ex: '#1F3864'.")


def _check_range(name: str, value: Any, minimum: float, maximum: float | None) -> None:
    number = _as_number(value, "", name)
    if number < minimum or (maximum is not None and number > maximum):
        limit = f"{minimum} a {maximum}" if maximum is not None else f">= {minimum}"
        raise InvalidVisualFormattingError(f"{name} = {value} fora do limite ({limit}).")


# --- cor de série única e estilo do slicer clássico ------------------------------


def set_visual_default_color(pbip_path: str, page_name: str, visual_name: str, color: str) -> dict[str, Any]:
    """Cor de um gráfico de UMA série (uma medida, sem legenda): vai em
    `dataPoint.defaultColor`, entrada sem seletor. Fonte: doc oficial
    color-strategy.md ("Single-Series Default Color") -- `fill` com seletor
    `metadata` é ignorado em série única (achado ao vivo: barra ficou azul)."""
    _check_hex(color)
    return _apply(pbip_path, page_name, visual_name, "dataPoint", {"defaultColor": color})


def set_slicer_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    header_show: bool | None = None,
    header_font_color: str | None = None,
    header_text_size: float | None = None,
    items_font_color: str | None = None,
    items_background: str | None = None,
    items_text_size: float | None = None,
) -> dict[str, Any]:
    """Cabeçalho e itens do slicer clássico (lista/suspenso): mostrar o
    cabeçalho, cores e tamanho do texto. Nomes do schema oficial de tema
    (visual-slicer.header/items)."""
    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    visual_type = json.loads(visual_json_path.read_text(encoding="utf-8"))["visual"]["visualType"]
    if visual_type != "slicer":
        raise InvalidVisualFormattingError(f"Estilo de slicer só vale pra slicer clássico; '{visual_name}' é '{visual_type}'.")
    groups = {
        "header": {"show": header_show, "fontColor": header_font_color, "textSize": header_text_size},
        "items": {"fontColor": items_font_color, "background": items_background, "textSize": items_text_size},
    }
    if all(v is None for props in groups.values() for v in props.values()):
        raise InvalidVisualFormattingError("Nenhuma propriedade de slicer foi informada.")
    # valida os dois grupos ANTES de gravar: tudo ou nada
    for object_name, props in groups.items():
        allowed = _SPEC.get("slicer", {}).get(object_name, ())
        for prop, value in props.items():
            if value is not None:
                _encode("slicer", object_name, prop, value, allowed)
    changed = {}
    for object_name, props in groups.items():
        if any(v is not None for v in props.values()):
            changed[object_name] = _apply(pbip_path, page_name, visual_name, object_name, props)["changed"]
    return {"visual_name": visual_name, "page_name": page_name, "changed": changed}


# --- árvore de decomposição ---------------------------------------------------
#
# Nomes e tipos do schema oficial de tema (visual-decompositionTreeVisual):
# dataBars, categoryLabels, dataLabels, levelHeader, tree. Sem exemplo na
# doc de autoria PBIR. A cor da barra existe em DOIS nomes no schema
# (`positiveBarColor` e `dataBarColor`) -- gravamos os dois com a mesma cor
# até a comparação ao vivo dizer qual vale.


def set_decomposition_tree_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    bar_color: str | None = None,
    bar_background_color: str | None = None,
    label_color: str | None = None,
    value_color: str | None = None,
    value_display_units: str | None = None,
    value_precision: int | None = None,
    header_background: str | None = None,
    header_title_color: str | None = None,
    header_subtitle_color: str | None = None,
    connector_color: str | None = None,
    bars_per_level: int | None = None,
    density: str | None = None,
    accent_color: str | None = None,
    label_font_size: float | None = None,
    value_font_size: float | None = None,
) -> dict[str, Any]:
    """Cores e layout de uma árvore de decomposição: barras, nomes, valores,
    cabeçalho dos níveis, conectores, quantas barras por nível e densidade."""
    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    visual_type = json.loads(visual_json_path.read_text(encoding="utf-8"))["visual"]["visualType"]
    if visual_type != "decompositionTreeVisual":
        raise InvalidVisualFormattingError(
            f"Estilo de árvore só vale pra árvore de decomposição; '{visual_name}' é '{visual_type}'."
        )
    groups = {
        "dataBars": {"positiveBarColor": bar_color, "dataBarColor": bar_color,
                     "dataBarBackgroundColor": bar_background_color},
        "categoryLabels": {"categoryLabelFontColor": label_color, "categoryLabelFontSize": label_font_size},
        "dataLabels": {"dataLabelFontColor": value_color, "dataLabelDisplayUnits": _display_units(value_display_units),
                       "dataLabelPrecision": value_precision, "dataLabelFontSize": value_font_size},
        "levelHeader": {"levelHeaderBackgroundColor": header_background, "levelTitleFontColor": header_title_color,
                        "levelSubtitleFontColor": header_subtitle_color},
        "tree": {"connectorDefaultColor": connector_color, "accentColor": accent_color,
                 "barsPerLevel": bars_per_level, "density": density},
    }
    if all(v is None for props in groups.values() for v in props.values()):
        raise InvalidVisualFormattingError("Nenhuma propriedade da árvore foi informada.")
    changed: dict[str, Any] = {}
    for object_name, props in groups.items():
        if any(v is not None for v in props.values()):
            changed[object_name] = _apply(pbip_path, page_name, visual_name, object_name, props)["changed"]
    return {"visual_name": visual_name, "page_name": page_name, "changed": changed}


# --- barras de dados em tabela/matriz -----------------------------------------
#
# Fonte: doc oficial conditional-formatting-part-06.md ("Type 4: Data
# Bars"): entrada no array `columnFormatting` (NÃO `values`) com seletor
# SÓ `metadata` -- `dataViewWildcard` faz as barras sumirem; propriedades
# positiveColor/negativeColor/axisColor/reverseDirection/hideText como no
# exemplo completo da doc; `totalMatchingOption` "0L" desenha também na
# linha de total (padrão: só nas linhas de dado). Nomes conferidos no
# schema oficial de tema (visual-tableEx.columnFormatting.dataBars).

_TABLE_TYPES = ("tableEx", "pivotTable")


def set_table_data_bars(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    field: str,
    color: str | None = None,
    negative_color: str = "#D64554",
    axis_color: str = "#999999",
    show_bar_only: bool = False,
    include_totals: bool = False,
    remove: bool = False,
) -> dict[str, Any]:
    """Barra de dados (barrinha dentro da célula) numa coluna numérica de
    tabela/matriz. `field` = queryRef da coluna na tabela (ex:
    "financials.Total Sales"); `remove=True` tira a barra dessa coluna."""
    if not remove:
        if color is None:
            raise InvalidVisualFormattingError("Informe `color` (cor da barra) -- ou remove=True pra tirar a barra.")
        for hex_color in (color, negative_color, axis_color):
            _check_hex(hex_color)

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]
    if visual_type not in _TABLE_TYPES:
        raise InvalidVisualFormattingError(
            f"Barras de dados só existem em tabela/matriz; '{visual_name}' é '{visual_type}'."
        )
    _require_projection(instance, visual_name, field, roles=None)

    objects = instance["visual"].setdefault("objects", {})
    entries = objects.setdefault("columnFormatting", [])
    selector = {"metadata": field}
    entry = next((e for e in entries if e.get("selector") == selector), None)

    if remove:
        if entry is not None:
            entry.get("properties", {}).pop("dataBars", None)
            if not entry.get("properties"):
                entries.remove(entry)
    else:
        bars = {
            "positiveColor": {"solid": {"color": _literal(f"'{color}'")}},
            "negativeColor": {"solid": {"color": _literal(f"'{negative_color}'")}},
            "axisColor": {"solid": {"color": _literal(f"'{axis_color}'")}},
            "reverseDirection": _literal("false"),
            "hideText": _literal("true" if show_bar_only else "false"),
        }
        if include_totals:
            bars["totalMatchingOption"] = _literal("0L")
        if entry is None:
            entry = {"properties": {}, "selector": selector}
            entries.append(entry)
        entry.setdefault("properties", {})["dataBars"] = bars

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "visual_name": visual_name, "page_name": page_name, "field": field,
        "data_bars": "removidas" if remove else {"color": color, "show_bar_only": show_bar_only,
                                                  "include_totals": include_totals},
    }


# --- cores/fonte de tabela e matriz -------------------------------------------
#
# Fonte: doc oficial table.md ("Table/Matrix Formatting Regions", "Full
# Table Example with Custom Styling"): cabeçalho = `columnHeaders`
# (fontColor/backColor); linhas = `values` com fontColorPrimary/Secondary e
# backColorPrimary/Secondary (em `values`, `fontColor`/`backColor` são
# slots de formatação condicional e cor fixa ali NÃO funciona); total da
# tabela = `total`; na matriz = `rowTotal` + `columnTotal` (lá `total` é
# slot condicional) e rótulos de linha em `rowHeaders`. Obrigatório
# `visualContainerObjects.stylePreset = 'None'`, senão o estilo padrão
# sobrescreve as cores em silêncio. `autoSizeColumnWidth` +
# `columnAdjustment 'growToFit'` = regra padrão da doc ("Grow to Fit").


def set_table_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    header_font_color: str | None = None,
    header_background: str | None = None,
    header_bold: bool | None = None,
    row_font_color: str | None = None,
    row_background: str | None = None,
    alt_row_background: str | None = None,
    total_font_color: str | None = None,
    total_background: str | None = None,
    total_bold: bool | None = None,
    font_size: float | None = None,
) -> dict[str, Any]:
    """Cores e fonte de tabela/matriz: cabeçalho, linhas (com zebra
    opcional) e total. Só os parâmetros passados mudam."""
    colors = {
        "header_font_color": header_font_color, "header_background": header_background,
        "row_font_color": row_font_color, "row_background": row_background,
        "alt_row_background": alt_row_background, "total_font_color": total_font_color,
        "total_background": total_background,
    }
    for color in colors.values():
        if color is not None:
            _check_hex(color)
    if font_size is not None:
        _check_range("font_size", font_size, *_FONT_SIZE_RANGE)
    if all(v is None for v in (*colors.values(), header_bold, total_bold, font_size)):
        raise InvalidVisualFormattingError("Nenhuma propriedade de tabela foi informada.")

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]
    if visual_type not in _TABLE_TYPES:
        raise InvalidVisualFormattingError(
            f"Estilo de tabela só vale pra tabela/matriz; '{visual_name}' é '{visual_type}'."
        )

    def fill(color: str | None) -> dict[str, Any] | None:
        return None if color is None else {"solid": {"color": _literal(f"'{color}'")}}

    def boolean(value: bool | None) -> dict[str, Any] | None:
        return None if value is None else _literal("true" if value else "false")

    size = None if font_size is None else _literal(f"{_number_text(float(font_size))}D")
    alt_background = alt_row_background or row_background
    regions: dict[str, dict[str, Any]] = {
        "columnHeaders": {"fontColor": fill(header_font_color), "backColor": fill(header_background),
                          "bold": boolean(header_bold), "fontSize": size},
        "values": {"fontColorPrimary": fill(row_font_color), "fontColorSecondary": fill(row_font_color),
                   "backColorPrimary": fill(row_background), "backColorSecondary": fill(alt_background),
                   "fontSize": size},
    }
    total = {"fontColor": fill(total_font_color), "backColor": fill(total_background),
             "bold": boolean(total_bold), "fontSize": size}
    if visual_type == "pivotTable":
        regions["rowTotal"] = total
        regions["columnTotal"] = dict(total)
        regions["rowHeaders"] = {"fontColor": fill(row_font_color), "backColor": fill(row_background)}
    else:
        regions["total"] = total

    objects = instance["visual"].setdefault("objects", {})
    changed = []
    for object_name, props in regions.items():
        props = {k: v for k, v in props.items() if v is not None}
        if not props:
            continue
        if object_name == "columnHeaders":
            props["autoSizeColumnWidth"] = _literal("true")
            props["columnAdjustment"] = _literal("'growToFit'")
        entries = objects.setdefault(object_name, [])
        base = next((e for e in entries if "selector" not in e), None)
        if base is None:
            base = {"properties": {}}
            entries.insert(0, base)
        base.setdefault("properties", {}).update(props)
        changed.append(object_name)

    instance["visual"].setdefault("visualContainerObjects", {})["stylePreset"] = [
        {"properties": {"name": _literal("'None'")}}
    ]

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name, "visual_type": visual_type, "objects": changed}


# Formato do número por coluna (mesmo `columnFormatting` das barras de dados,
# seletor `metadata`): `labelDisplayUnits` (displayUnitsWithoutAuto -- sem
# "auto") e `labelPrecision`, nomes do schema oficial de tema
# (visual-tableEx.columnFormatting).

_COLUMN_DISPLAY_UNITS = {k: v for k, v in _DISPLAY_UNITS.items() if k != "auto"}


def set_table_column_format(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    field: str,
    display_units: str | None = None,
    precision: int | None = None,
) -> dict[str, Any]:
    """Formato do número de UMA coluna de tabela/matriz: unidade
    (mil/milhão...) e casas decimais -- ex: 24,887,654.88 -> 24.89M."""
    if display_units is not None and display_units not in _COLUMN_DISPLAY_UNITS:
        raise InvalidVisualFormattingError(
            f"display_units '{display_units}' inválido. Use um de: {', '.join(_COLUMN_DISPLAY_UNITS)}."
        )
    if precision is not None:
        _check_range("precision", precision, 0, None)
    if display_units is None and precision is None:
        raise InvalidVisualFormattingError("Informe display_units e/ou precision.")

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]
    if visual_type not in _TABLE_TYPES:
        raise InvalidVisualFormattingError(
            f"Formato de coluna só vale pra tabela/matriz; '{visual_name}' é '{visual_type}'."
        )
    _require_projection(instance, visual_name, field, roles=None)

    props: dict[str, Any] = {}
    if display_units is not None:
        props["labelDisplayUnits"] = _literal(f"{_COLUMN_DISPLAY_UNITS[display_units]}D")
    if precision is not None:
        props["labelPrecision"] = _literal(f"{int(precision)}L")

    entries = instance["visual"].setdefault("objects", {}).setdefault("columnFormatting", [])
    selector = {"metadata": field}
    entry = next((e for e in entries if e.get("selector") == selector), None)
    if entry is None:
        entry = {"properties": {}, "selector": selector}
        entries.append(entry)
    entry.setdefault("properties", {}).update(props)

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"visual_name": visual_name, "page_name": page_name, "field": field,
            "changed": {k: v for k, v in {"display_units": display_units, "precision": precision}.items()
                        if v is not None}}


# --- estilo de linha por série --------------------------------------------------
#
# Fonte: doc oficial cartesian-part-02.md ("lineStyles -- Line Specific"):
# entrada sem selector = todas as linhas; entrada com `{"metadata":
# "<queryRef>"}` = uma série (exemplo da doc com `lineStyle 'dashed'`).
# Enums conferidos no schema oficial de tema (visual-lineChart.lineStyles).

_LINE_TYPES = ("lineChart", "areaChart", "stackedAreaChart")
_LINE_STYLES = ("solid", "dashed", "dotted")
_LINE_INTERPOLATIONS = ("linear", "smooth", "step")


def set_line_style(
    pbip_path: str,
    page_name: str,
    visual_name: str,
    series: str | None = None,
    line_style: str | None = None,
    width: float | None = None,
    show_marker: bool | None = None,
    interpolation: str | None = None,
) -> dict[str, Any]:
    """Estilo das linhas de um gráfico de linha/área: tracejada/pontilhada,
    espessura, marcadores e curva (linear/suave/degrau). Com `series` (queryRef
    de uma medida do eixo Y) muda só aquela linha; sem, muda todas."""
    if line_style is not None and line_style not in _LINE_STYLES:
        raise InvalidVisualFormattingError(f"line_style '{line_style}' inválido. Use um de: {', '.join(_LINE_STYLES)}.")
    if interpolation is not None and interpolation not in _LINE_INTERPOLATIONS:
        raise InvalidVisualFormattingError(
            f"interpolation '{interpolation}' inválido. Use um de: {', '.join(_LINE_INTERPOLATIONS)}."
        )
    if width is not None:
        _check_range("width", width, 0, None)

    props: dict[str, Any] = {}
    if line_style is not None:
        props["lineStyle"] = _literal(f"'{line_style}'")
    if width is not None:
        props["strokeWidth"] = _literal(f"{_number_text(float(width))}D")
    if show_marker is not None:
        props["showMarker"] = _literal("true" if show_marker else "false")
    if interpolation is not None:
        props["lineChartType"] = _literal(f"'{interpolation}'")
    if not props:
        raise InvalidVisualFormattingError("Nenhuma propriedade de linha foi informada.")

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]
    if visual_type not in _LINE_TYPES:
        raise InvalidVisualFormattingError(
            f"Estilo de linha só vale pra gráfico de linha/área; '{visual_name}' é '{visual_type}'."
        )
    if series is not None:
        _require_projection(instance, visual_name, series, roles=("Y",))

    entries = instance["visual"].setdefault("objects", {}).setdefault("lineStyles", [])
    if series is None:
        entry = next((e for e in entries if "selector" not in e), None)
        if entry is None:
            entry = {"properties": {}}
            entries.insert(0, entry)
    else:
        selector = {"metadata": series}
        entry = next((e for e in entries if e.get("selector") == selector), None)
        if entry is None:
            entry = {"properties": {}, "selector": selector}
            entries.append(entry)
    entry.setdefault("properties", {}).update(props)

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "visual_name": visual_name, "page_name": page_name, "series": series or "(todas)",
        "changed": {k: v for k, v in {"line_style": line_style, "width": width, "show_marker": show_marker,
                                      "interpolation": interpolation}.items() if v is not None},
    }


def _require_projection(
    instance: dict[str, Any], visual_name: str, query_ref: str, roles: tuple[str, ...] | None
) -> None:
    query_state = instance["visual"].get("query", {}).get("queryState", {})
    refs = [
        p.get("queryRef")
        for role, data in query_state.items() if roles is None or role in roles
        for p in data.get("projections", [])
    ]
    if query_ref not in refs:
        raise InvalidVisualFormattingError(
            f"'{query_ref}' não está no visual '{visual_name}'. Campos disponíveis: {', '.join(refs) or '(nenhum)'}."
        )


# --- internos ---------------------------------------------------------------


def _display_units(value: str | None) -> int | None:
    if value is None:
        return None
    if value not in _DISPLAY_UNITS:
        raise InvalidVisualFormattingError(
            f"display_units '{value}' inválido. Use um de: {', '.join(_DISPLAY_UNITS)}."
        )
    return _DISPLAY_UNITS[value]


def _apply(
    pbip_path: str, page_name: str, visual_name: str, object_name: str, updates: dict[str, Any]
) -> dict[str, Any]:
    changes = {prop: value for prop, value in updates.items() if value is not None}
    if not changes:
        raise InvalidVisualFormattingError("Nenhuma propriedade de formatação foi informada.")

    visual_json_path = _resolve_visual_dir(pbip_path, page_name, visual_name) / "visual.json"
    instance = json.loads(visual_json_path.read_text(encoding="utf-8"))
    visual_type = instance["visual"]["visualType"]

    allowed = _SPEC.get(visual_type, {}).get(object_name)
    if allowed is None:
        supported = sorted(_SPEC.get(visual_type, {}))
        raise InvalidVisualFormattingError(
            f"O visual '{visual_name}' é do tipo '{visual_type}', que não tem '{object_name}' "
            f"(schema oficial de tema). Objetos disponíveis pra esse tipo: "
            f"{', '.join(supported) or '(nenhum destes)'}."
        )

    encoded = {prop: _encode(visual_type, object_name, prop, value, allowed) for prop, value in changes.items()}

    objects = instance["visual"].setdefault("objects", {})
    entries = objects.setdefault(object_name, [])
    base = next((e for e in entries if "selector" not in e), None)
    if base is None:
        base = {"properties": {}}
        entries.insert(0, base)
    base.setdefault("properties", {}).update(encoded)

    visual_json_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "visual_name": visual_name,
        "page_name": page_name,
        "visual_type": visual_type,
        "object": object_name,
        "changed": changes,
    }


def _encode(visual_type: str, object_name: str, prop: str, value: Any, allowed: dict[str, Any]) -> dict[str, Any]:
    rule = allowed.get(prop)
    if rule is None:
        raise InvalidVisualFormattingError(
            f"'{object_name}.{prop}' não existe pro tipo '{visual_type}' (schema oficial de tema). "
            f"Propriedades disponíveis: {', '.join(sorted(allowed))}."
        )

    enum = rule.get("enum")
    if enum is not None and value not in enum:
        raise InvalidVisualFormattingError(
            f"Valor '{value}' inválido pra '{object_name}.{prop}' em '{visual_type}'. "
            f"Valores aceitos: {', '.join(str(v) for v in enum)}."
        )

    kind = rule["type"]
    if kind == "boolean":
        return _literal("true" if value else "false")
    if kind == "string":
        return _literal("'" + str(value).replace("'", "''") + "'")
    if kind == "color":
        if not isinstance(value, str) or not _HEX_COLOR.match(value):
            raise InvalidVisualFormattingError(
                f"Cor '{value}' inválida -- use hexadecimal com '#', ex: '#333333'."
            )
        return {"solid": {"color": _literal(f"'{value}'")}}
    if kind in ("number", "integer"):
        number = _as_number(value, object_name, prop)
        for bound, check in (("minimum", number < rule.get("minimum", number)),
                             ("maximum", number > rule.get("maximum", number))):
            if check:
                raise InvalidVisualFormattingError(
                    f"'{object_name}.{prop}' = {value} fora do limite do schema oficial "
                    f"({rule.get('minimum')} a {rule.get('maximum')})."
                )
        if kind == "integer":
            return _literal(f"{int(number)}{_INTEGER_SUFFIX.get(prop, 'L')}")
        return _literal(f"{_number_text(number)}D")
    raise InvalidVisualFormattingError(f"Tipo de propriedade '{kind}' não suportado ({object_name}.{prop}).")


def _as_number(value: Any, object_name: str, prop: str) -> float:
    if isinstance(value, bool):
        raise InvalidVisualFormattingError(f"'{object_name}.{prop}' precisa ser um número.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidVisualFormattingError(f"'{object_name}.{prop}' precisa ser um número.") from exc


def _number_text(number: float) -> str:
    return str(int(number)) if number.is_integer() else repr(number)


def _literal(value: str) -> dict[str, Any]:
    return {"expr": {"Literal": {"Value": value}}}
