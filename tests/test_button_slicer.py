"""Testes do slicer de botões (`advancedSlicerVisual`): catálogo +
set_button_slicer_style (visuals.formatting).

Fontes:
- doc oficial slicers.md (skills-for-fabric): "ButtonSlicer ... visualType
  is advancedSlicerVisual. 'Values' only allow one field with Column
  Expression. 'Label' only allow one field with Measure".
- schema oficial de tema (visual-advancedSlicerVisual): selection
  (singleSelect), layout (maxTiles, cellPadding), fillCustom (fillColor,
  transparency), value (fontColor, fontSize, bold, transparency),
  outline (show, lineColor, weight), shapeCustomRectangle
  (rectangleRoundedCurve).
- doc button-part-02.md "Dual-Entry Pattern": `show` numa entrada SEM
  selector, estilo em entradas COM selector de estado ("putting all
  properties in one entry ... causes formatting to silently fail").
- tema base do próprio Desktop (Fluent2-CY26SU08.json, no projeto de
  teste): ids de estado do advancedSlicerVisual são "default" e
  "selection:selected" (a tabela da doc formatting.md abrevia pra
  "selected"); `layout` sem $id. NÃO confirmado ao vivo ainda.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError, InvalidVisualRoleError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_visual_json
from visuals import formatting, page_writer, visual_writer


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Datas", columns=(ColumnInfo(name="Ano", data_type="Int64"),)))
    fake.create_measure("Datas", "Total Vendas", "1", None)
    connection.set_active_runtime(fake)
    return fake


def _slicer(project_dir: Path, fields=None) -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="advancedSlicerVisual",
        x=0, y=0, width=200, height=40, fields=fields or {"Values": ["Datas.Ano"]},
    )["visual_name"]


def _visual(project_dir: Path, name: str) -> dict:
    data = json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json")
        .read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    return data


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def _color(hex_color: str) -> dict:
    return {"solid": {"color": _lit(f"'{hex_color}'")}}


_DEFAULT = {"id": "default"}
_SELECTED = {"id": "selection:selected"}


def test_button_slicer_accepts_one_column_and_optional_label_measure(project_dir):
    name = _slicer(project_dir, {"Values": ["Datas.Ano"], "Label": ["Datas.Total Vendas"]})
    visual = _visual(project_dir, name)
    assert visual["visual"]["visualType"] == "advancedSlicerVisual"
    assert set(visual["visual"]["query"]["queryState"]) == {"Values", "Label"}


@pytest.mark.parametrize("fields", [
    {"Values": ["Datas.Total Vendas"]},          # medida em Values
    {"Values": ["Datas.Ano", "Datas.Ano"]},      # mais de uma coluna
    {"Label": ["Datas.Total Vendas"]},           # sem Values
])
def test_button_slicer_roles_are_validated(project_dir, fields):
    with pytest.raises(InvalidVisualRoleError):
        _slicer(project_dir, fields)


def test_style_writes_dual_entries_per_state(project_dir):
    name = _slicer(project_dir)

    formatting.set_button_slicer_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        single_select=True, tiles_per_row=3,
        tile_color="#303030", selected_tile_color="#D9956B",
        text_color="#EDEDED", selected_text_color="#FFFFFF", text_size=10, text_bold=True,
        outline_show=False, corner_radius=6,
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["selection"] == [{"properties": {"singleSelect": _lit("true")}}]
    assert objects["layout"] == [{"properties": {"columnCount": _lit("3L"), "autoGrid": _lit("false")}}]
    assert objects["fillCustom"] == [
        {"properties": {"show": _lit("true")}},
        {"properties": {"fillColor": _color("#303030")}, "selector": _DEFAULT},
        {"properties": {"fillColor": _color("#D9956B")}, "selector": _SELECTED},
    ]
    assert objects["value"] == [
        {"properties": {"fontColor": _color("#EDEDED"), "fontSize": _lit("10D"), "bold": _lit("true")}, "selector": _DEFAULT},
        {"properties": {"fontColor": _color("#FFFFFF")}, "selector": _SELECTED},
    ]
    assert objects["outline"] == [{"properties": {"show": _lit("false")}}]
    assert objects["shapeCustomRectangle"] == [
        {"properties": {"tileShape": _lit("'rectangleRoundedByPixel'"), "rectangleRoundedCurve": _lit("6L")},
         "selector": _DEFAULT},
    ]


def test_transparent_tiles_with_selected_outline_for_overlay(project_dir):
    """Uso "por cima de um desenho" (ex: cartões desenhados no fundo):
    ladrilho e texto invisíveis, só o contorno do selecionado aparece."""
    name = _slicer(project_dir)

    formatting.set_button_slicer_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        tile_transparency=100, selected_tile_transparency=100, text_transparency=100,
        outline_show=True, outline_transparency=100, selected_outline_color="#D9956B", outline_weight=4,
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["fillCustom"][1] == {"properties": {"transparency": _lit("100D")}, "selector": _DEFAULT}
    assert objects["fillCustom"][2] == {"properties": {"transparency": _lit("100D")}, "selector": _SELECTED}
    assert objects["value"][0] == {"properties": {"transparency": _lit("100D")}, "selector": _DEFAULT}
    assert objects["outline"] == [
        {"properties": {"show": _lit("true")}},
        {"properties": {"transparency": _lit("100D"), "weight": _lit("4D")}, "selector": _DEFAULT},
        {"properties": {"lineColor": _color("#D9956B"), "transparency": _lit("0D"), "show": _lit("true")},
         "selector": _SELECTED},
    ]


def test_style_updates_existing_entries_in_place(project_dir):
    name = _slicer(project_dir)
    formatting.set_button_slicer_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
                                       tile_color="#111111")
    formatting.set_button_slicer_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
                                       tile_color="#222222", selected_tile_color="#333333")

    fill = _visual(project_dir, name)["visual"]["objects"]["fillCustom"]
    assert fill == [
        {"properties": {"show": _lit("true")}},
        {"properties": {"fillColor": _color("#222222")}, "selector": _DEFAULT},
        {"properties": {"fillColor": _color("#333333")}, "selector": _SELECTED},
    ]


@pytest.mark.parametrize("kwargs", [
    {"tile_color": "laranja"},
    {"tile_transparency": 101},
    {"tiles_per_row": 0},
    {"text_size": 7},
    {},
])
def test_invalid_style_is_rejected_without_writing(project_dir, kwargs):
    name = _slicer(project_dir)
    before = _visual(project_dir, name)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_button_slicer_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, **kwargs)
    assert _visual(project_dir, name) == before


def test_style_only_for_button_slicer(project_dir):
    name = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="slicer",
        x=0, y=0, width=200, height=40, fields={"Values": ["Datas.Ano"]},
    )["visual_name"]
    with pytest.raises(InvalidVisualFormattingError, match="advancedSlicerVisual"):
        formatting.set_button_slicer_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
                                           tile_color="#111111")


def test_force_selection_uses_strict_single_select(project_dir):
    """"Forçar seleção" (sempre um item marcado): selection.strictSingleSelect
    do schema oficial de tema -- sem isso, um field parameter sem seleção
    mostra TODAS as métricas no gráfico."""
    name = _slicer(project_dir)
    formatting.set_button_slicer_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, single_select=True, force_selection=True,
    )
    assert _visual(project_dir, name)["visual"]["objects"]["selection"] == [
        {"properties": {"singleSelect": _lit("true"), "strictSingleSelect": _lit("true")}}
    ]



def test_selected_outline_is_turned_on_in_its_own_state(project_dir):
    """Achado ao vivo (2026-09-30): o tema base do Desktop (Fluent2) põe
    `outline.show = false` NO ESTADO "selection:selected", e isso vence o
    `show` geral -- o contorno do cartão selecionado não aparecia. Ligar
    o contorno do selecionado exige `show: true` no próprio estado."""
    name = _slicer(project_dir)
    formatting.set_button_slicer_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, selected_outline_color="#D9956B",
    )
    outline = _visual(project_dir, name)["visual"]["objects"]["outline"]
    selected = next(e for e in outline if e.get("selector") == _SELECTED)
    assert selected["properties"]["show"] == _lit("true")



def test_rows_and_columns_turn_off_auto_grid(project_dir):
    """Achado ao vivo (2026-09-30): `maxTiles` NÃO define ladrilhos por
    linha -- com maxTiles=5 o Desktop manteve a grade padrão de 3 colunas.
    O schema oficial tem columnCount/rowCount/autoGrid (grade automática)."""
    name = _slicer(project_dir)
    formatting.set_button_slicer_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, tiles_per_row=5, rows=1,
    )
    assert _visual(project_dir, name)["visual"]["objects"]["layout"] == [
        {"properties": {"columnCount": _lit("5L"), "autoGrid": _lit("false"), "rowCount": _lit("1L")}}
    ]


def test_tile_spacing_is_cell_padding(project_dir):
    """Espaço entre ladrilhos = layout.cellPadding (schema oficial; o tema
    base do Desktop usa 8). Achado ao vivo: pra alinhar com cartões
    desenhados com 18px de vão, o espaço precisa ser igual ao do desenho."""
    name = _slicer(project_dir)
    formatting.set_button_slicer_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, tile_spacing=18,
    )
    assert _visual(project_dir, name)["visual"]["objects"]["layout"] == [
        {"properties": {"cellPadding": _lit("18L")}}
    ]
