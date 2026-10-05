"""visuals/formatting_spec.json é GERADO do schema oficial de tema
(scripts/generate_formatting_spec.py). Este teste regenera em memória e
compara com o arquivo commitado -- se o schema vendorizado ou o catálogo
de visuais mudar sem regenerar, a suíte quebra."""

from __future__ import annotations

import json

from scripts.generate_formatting_spec import SPEC_PATH, THEME_SCHEMA_PATH, build_formatting_spec
from visuals.catalog import VISUAL_TYPES


def test_committed_spec_matches_official_schema():
    schema = json.loads(THEME_SCHEMA_PATH.read_text(encoding="utf-8"))
    expected = build_formatting_spec(schema, list(VISUAL_TYPES))
    committed = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert committed == expected, (
        "visuals/formatting_spec.json desatualizado -- rode "
        '".venv/Scripts/python" -m scripts.generate_formatting_spec'
    )


def test_spec_reflects_known_per_type_differences():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    # gráfico de colunas tem os 4 objetos
    assert set(spec["clusteredColumnChart"]) == {"labels", "legend", "categoryAxis", "valueAxis", "dataPoint"}
    # cartão legado: valor (sem "show" -- sempre aparece) + texto de baixo
    assert set(spec["card"]) == {"labels", "categoryLabels"}
    assert "show" not in spec["card"]["labels"]
    # cartão atual usa outros nomes (value/label, cor = fontColor)
    assert set(spec["cardVisual"]) == {"value", "label", "fillCustom", "outline"}
    assert "fontColor" in spec["cardVisual"]["value"]
    # tabela/matriz não têm nenhum desses objetos; o slicer clássico só
    # tem cabeçalho e itens (set_slicer_style)
    for visual_type in ("tableEx", "pivotTable"):
        assert visual_type not in spec
    assert set(spec["slicer"]) == {"header", "items"}
