"""Gera visuals/formatting_spec.json a partir do schema OFICIAL de tema
de relatório (tests/schemas/reportThemeSchema.2.157.json,
microsoft/powerbi-desktop-samples).

Esse schema descreve, POR TIPO DE VISUAL, cada objeto de formatação
(`labels`, `legend`, `categoryAxis`, `valueAxis`, ...) com os nomes exatos
das propriedades, o tipo, os valores válidos (`oneOf` de `const`) e os
limites (`minimum`/`maximum`). A doc oficial de autoria de PBIR avisa que
"property names vary by visual type" -- por isso as tools de formatação
(visuals/formatting.py) validam contra esta especificação em vez de uma
lista escrita à mão.

Só as propriedades usadas pelas tools entram (_CURATED). Rodar de novo
sempre que o schema vendorizado ou o catálogo de visuais mudar:

    ".venv/Scripts/python" -m scripts.generate_formatting_spec

tests/test_formatting_spec.py regenera em memória e compara com o arquivo
commitado -- se divergir, a suíte quebra.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
THEME_SCHEMA_PATH = ROOT / "tests" / "schemas" / "reportThemeSchema.2.157.json"
SPEC_PATH = ROOT / "visuals" / "formatting_spec.json"

_CURATED: dict[str, tuple[str, ...]] = {
    "labels": (
        "show", "labelPosition", "labelDisplayUnits", "labelPrecision", "fontSize", "color",
        "bold", "fontFamily", "labelStyle",
    ),
    # rosca/pizza: número grande no meio da rosca
    "centerValue": ("show",),
    # cartão legado ("card"): texto de baixo do valor; árvore de
    # decomposição: nome de cada barra (categoryLabelFontColor)
    "categoryLabels": ("show", "fontSize", "color", "bold", "categoryLabelFontColor", "categoryLabelFontSize"),
    # árvore de decomposição (decompositionTreeVisual)
    "dataBars": ("positiveBarColor", "dataBarColor", "dataBarBackgroundColor"),
    "dataLabels": ("dataLabelFontColor", "dataLabelDisplayUnits", "dataLabelPrecision", "dataLabelFontSize"),
    "levelHeader": ("levelHeaderBackgroundColor", "levelTitleFontColor", "levelSubtitleFontColor"),
    "tree": ("connectorDefaultColor", "accentColor", "barsPerLevel", "density"),
    # cartão atual ("cardVisual"): valor e texto de baixo (doc card.md)
    "value": ("fontSize", "fontColor", "bold", "fontFamily", "labelDisplayUnits", "labelPrecision"),
    "label": ("show", "fontSize", "fontColor", "bold", "text"),
    # cardVisual: preenchimento interno e borda interna (doc card-part-03.md)
    "fillCustom": ("show", "fillColor", "transparency"),
    "outline": ("show",),
    "legend": ("show", "position", "showTitle", "titleText", "fontSize"),
    "categoryAxis": (
        "show", "showAxisTitle", "titleText", "fontSize", "invertAxis",
        "start", "end", "labelDisplayUnits", "gridlineShow", "preferredCategoryWidth", "axisType",
    ),
    # cor de gráfico de série única (doc color-strategy.md, "Single-Series Default Color")
    "dataPoint": ("defaultColor",),
    # slicer clássico: cabeçalho e itens
    "header": ("show", "fontColor", "textSize"),
    "items": ("fontColor", "background", "textSize"),
    "valueAxis": (
        "show", "showAxisTitle", "titleText", "fontSize", "invertAxis",
        "start", "end", "labelDisplayUnits", "gridlineShow",
    ),
}


def build_formatting_spec(theme_schema: dict[str, Any], visual_types: list[str]) -> dict[str, Any]:
    """{visual_type: {objeto: {propriedade: {type, enum?, minimum?, maximum?}}}}
    -- só tipos/objetos/propriedades que existem no schema."""
    definitions = theme_schema["definitions"]

    def resolve(node: Any) -> Any:
        while isinstance(node, dict) and "$ref" in node:
            node = definitions[node["$ref"].split("/")[-1]]
        return node

    def properties_of(node: Any) -> dict[str, Any]:
        node = resolve(node)
        merged = dict(node.get("properties", {}))
        for key in ("allOf", "anyOf", "oneOf"):
            for sub in node.get(key, []):
                merged.update(properties_of(sub))
        return merged

    spec: dict[str, Any] = {}
    for visual_type in sorted(visual_types):
        definition = definitions.get(f"visual-{visual_type}")
        if definition is None:
            continue
        objects = properties_of(definition)
        for object_name, wanted in _CURATED.items():
            if object_name not in objects:
                continue
            item = resolve(objects[object_name])
            available = properties_of(resolve(item.get("items", item)))
            described = {
                prop: _describe(resolve(available[prop]), resolve)
                for prop in wanted
                if prop in available
            }
            if described:
                spec.setdefault(visual_type, {})[object_name] = described
    return spec


def _describe(node: dict[str, Any], resolve: Any) -> dict[str, Any]:
    if "solid" in json.dumps(node):
        return {"type": "color"}
    kind = node.get("type")
    if isinstance(kind, list):
        kind = "number" if "number" in kind else kind[0]
    described: dict[str, Any] = {"type": kind}
    enum = [resolve(o)["const"] for o in node.get("oneOf", []) if "const" in resolve(o)]
    if enum:
        described["enum"] = enum
    for bound in ("minimum", "maximum"):
        if bound in node:
            described[bound] = node[bound]
    return described


def main() -> None:
    from visuals.catalog import VISUAL_TYPES

    schema = json.loads(THEME_SCHEMA_PATH.read_text(encoding="utf-8"))
    spec = build_formatting_spec(schema, list(VISUAL_TYPES))
    SPEC_PATH.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{SPEC_PATH} -- {len(spec)} tipos de visual")


if __name__ == "__main__":
    main()
