"""Cor de série única (dataPoint.defaultColor), tipo do eixo de categorias
(categoryAxis.axisType) e estilo do slicer clássico (header/items).

Fontes: doc oficial color-strategy.md ("Pattern: Single-Series Default
Color": gráfico de uma medida usa `defaultColor`, não `fill` com seletor
`metadata`, que é ignorado) + schema oficial de tema (visual-*.dataPoint.
defaultColor, categoryAxis.axisType 'Scalar'/'Categorical', visual-slicer
header/items). Achado ao vivo no dashboard Cristallo (2026-10-03): barra
de série única ficou azul com o seletor metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_visual_json
from visuals import formatting, visual_writer


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    report_dir = root / "Vendas.Report"
    pages_dir = report_dir / "definition" / "pages"
    page_dir = pages_dir / "Pagina1"
    page_dir.mkdir(parents=True)
    (page_dir / "page.json").write_text("{}", encoding="utf-8")
    (pages_dir / "pages.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "version.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "report.json").write_text("{}", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Vendas", columns=(
        ColumnInfo(name="Valor", data_type="Double"),
        ColumnInfo(name="Segmento", data_type="String"),
        ColumnInfo(name="Ano", data_type="Int64"),
    )))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _add(project_dir: Path, visual_type: str, fields: dict) -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=visual_type,
        x=0, y=0, width=300, height=200, fields=fields,
    )["visual_name"]


def _visual(project_dir: Path, name: str) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def _color(hex_color: str) -> dict:
    return {"solid": {"color": _lit(f"'{hex_color}'")}}


def test_default_color_goes_to_base_data_point_and_keeps_series_colors(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})
    visual_writer.set_visual_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, query_ref="Vendas.Total Vendas", hex_color="#111111",
    )

    formatting.set_visual_default_color(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, color="#E8825C")

    points = _visual(project_dir, name)["visual"]["objects"]["dataPoint"]
    assert points[0] == {"properties": {"defaultColor": _color("#E8825C")}}
    assert points[1]["selector"] == {"metadata": "Vendas.Total Vendas"}


def test_default_color_rejects_bad_hex(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_default_color(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, color="laranja")


def test_category_axis_type_categorical(project_dir: Path):
    name = _add(project_dir, "clusteredColumnChart", {"Category": ["Vendas.Ano"], "Y": ["Vendas.Total Vendas"]})

    formatting.set_visual_axis(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, axis="category", axis_type="categorical",
    )

    props = _visual(project_dir, name)["visual"]["objects"]["categoryAxis"][0]["properties"]
    assert props["axisType"] == _lit("'Categorical'")
    with pytest.raises(InvalidVisualFormattingError, match="axis_type"):
        formatting.set_visual_axis(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, axis="category", axis_type="diagonal",
        )


def test_slicer_style_header_and_items(project_dir: Path):
    name = _add(project_dir, "slicer", {"Values": ["Vendas.Segmento"]})

    formatting.set_slicer_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, header_show=False,
        items_font_color="#F2F2F2", items_background="#1C1C1C", items_text_size=10,
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["header"][0]["properties"] == {"show": _lit("false")}
    assert objects["items"][0]["properties"] == {
        "fontColor": _color("#F2F2F2"), "background": _color("#1C1C1C"), "textSize": _lit("10D"),
    }


def test_slicer_style_refuses_other_visuals(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualFormattingError, match="slicer"):
        formatting.set_slicer_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, header_show=False)


# --- cor condicional no cartão (doc conditional-formatting.md: cardVisual ->
# value.fontColor com selector {"id": "default"}) ----------------------------


def test_conditional_color_on_card_goes_to_value_font_color_default_entry(project_dir: Path, fake_runtime: FakeTomRuntime):
    fake_runtime.create_measure("Vendas", "Variação", "0", "0%")
    name = _add(project_dir, "cardVisual", {"Data": ["Vendas.Total Vendas"]})
    formatting.set_card_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, value_font_size=9)

    visual_writer.set_visual_conditional_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, query_ref="Vendas.Variação",
        rules=[{"operator": ">=", "value": 0, "color": "#5FBF77"}], default_color="#E05A5A",
    )

    entries = _visual(project_dir, name)["visual"]["objects"]["value"]
    assert len(entries) == 1
    assert entries[0]["selector"] == {"id": "default"}
    props = entries[0]["properties"]
    assert props["fontSize"] == _lit("9D")
    conditional = props["fontColor"]["solid"]["color"]["expr"]["Conditional"]
    assert conditional["DefaultValue"] == {"Literal": {"Value": "'#E05A5A'"}}
    case = conditional["Cases"][0]
    assert case["Value"] == {"Literal": {"Value": "'#5FBF77'"}}
    assert case["Condition"]["Comparison"]["Left"]["Measure"]["Property"] == "Variação"


def test_slicer_style_is_all_or_nothing(project_dir: Path):
    # revisão final: o cabeçalho era gravado e só depois o tamanho dos itens
    # (fora de 8-60) falhava, deixando o visual meio alterado.
    name = _add(project_dir, "slicer", {"Values": ["Vendas.Segmento"]})
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    before = path.read_text(encoding="utf-8")

    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_slicer_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            header_font_color="#FFFFFF", items_text_size=100,
        )
    assert path.read_text(encoding="utf-8") == before
