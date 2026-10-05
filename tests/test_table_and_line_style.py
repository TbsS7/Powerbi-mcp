"""Testes de drill-down em gráfico cartesiano, barras de dados em tabela e
estilo de linha por série.

Fontes oficiais (microsoft/skills-for-fabric, references/authoring):
- cartesian.md, "Category Drill Hierarchy": vários campos no role
  `Category` formam a hierarquia de drill; `active: true` só na primeira
  projeção = gráfico abre no nível de cima.
- conditional-formatting-part-06.md, "Type 4: Data Bars": entrada em
  `columnFormatting` (NÃO `values`) com seletor SÓ `metadata`;
  propriedades positiveColor/negativeColor/axisColor/reverseDirection/
  hideText (+ totalMatchingOption "0L" pra desenhar no total).
- cartesian-part-02.md, "lineStyles": entrada com seletor `metadata`
  estiliza uma série (ex: `lineStyle 'dashed'`).

Todo visual.json escrito é validado contra o schema oficial
visualContainer/2.7.0.
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
        ColumnInfo(name="Produto", data_type="String"),
    )))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    fake.create_measure("Vendas", "Vendas PY", "0", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _add(project_dir: Path, visual_type: str, fields: dict) -> str:
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=visual_type,
        x=0, y=0, width=400, height=300, fields=fields,
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


# --- drill-down -------------------------------------------------------------


def test_bar_chart_with_two_category_fields_becomes_drill_hierarchy(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {
        "Category": ["Vendas.Segmento", "Vendas.Produto"], "Y": ["Vendas.Total Vendas"],
    })

    projections = _visual(project_dir, name)["visual"]["query"]["queryState"]["Category"]["projections"]
    assert [p["queryRef"] for p in projections] == ["Vendas.Segmento", "Vendas.Produto"]
    assert projections[0]["active"] is True
    assert "active" not in projections[1]


def test_single_category_field_has_no_active_flag(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    projection = _visual(project_dir, name)["visual"]["query"]["queryState"]["Category"]["projections"][0]
    assert "active" not in projection


def test_table_never_gets_active_flag(project_dir: Path):
    name = _add(project_dir, "tableEx", {"Values": ["Vendas.Segmento", "Vendas.Produto", "Vendas.Total Vendas"]})

    projections = _visual(project_dir, name)["visual"]["query"]["queryState"]["Values"]["projections"]
    assert all("active" not in p for p in projections)


def test_donut_still_accepts_only_one_category(project_dir: Path):
    with pytest.raises(InvalidVisualRoleError):
        _add(project_dir, "donutChart", {"Category": ["Vendas.Segmento", "Vendas.Produto"], "Y": ["Vendas.Total Vendas"]})


# --- barras de dados --------------------------------------------------------


def _table(project_dir: Path) -> str:
    return _add(project_dir, "tableEx", {"Values": ["Vendas.Segmento", "Vendas.Total Vendas"]})


def test_data_bars_written_in_column_formatting_with_metadata_selector(project_dir: Path):
    name = _table(project_dir)

    result = formatting.set_table_data_bars(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        field="Vendas.Total Vendas", color="#6B6F80",
    )

    entries = _visual(project_dir, name)["visual"]["objects"]["columnFormatting"]
    assert entries == [{
        "properties": {"dataBars": {
            "positiveColor": _color("#6B6F80"),
            "negativeColor": _color("#D64554"),
            "axisColor": _color("#999999"),
            "reverseDirection": _lit("false"),
            "hideText": _lit("false"),
        }},
        "selector": {"metadata": "Vendas.Total Vendas"},
    }]
    assert result["field"] == "Vendas.Total Vendas"


def test_data_bars_options_bar_only_and_totals(project_dir: Path):
    name = _table(project_dir)

    formatting.set_table_data_bars(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        field="Vendas.Total Vendas", color="#6B6F80", negative_color="#FF0000",
        axis_color="#000000", show_bar_only=True, include_totals=True,
    )

    bars = _visual(project_dir, name)["visual"]["objects"]["columnFormatting"][0]["properties"]["dataBars"]
    assert bars["negativeColor"] == _color("#FF0000")
    assert bars["axisColor"] == _color("#000000")
    assert bars["hideText"] == _lit("true")
    assert bars["totalMatchingOption"] == _lit("0L")


def test_data_bars_second_call_replaces_and_keeps_other_column_formatting(project_dir: Path):
    name = _table(project_dir)
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual"]["objects"] = {"columnFormatting": [{
        "properties": {"alignment": _lit("'Right'")}, "selector": {"metadata": "Vendas.Total Vendas"},
    }]}
    path.write_text(json.dumps(data), encoding="utf-8")

    for color in ("#111111", "#222222"):
        formatting.set_table_data_bars(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            field="Vendas.Total Vendas", color=color,
        )

    entries = _visual(project_dir, name)["visual"]["objects"]["columnFormatting"]
    assert len(entries) == 1
    assert entries[0]["properties"]["alignment"] == _lit("'Right'")
    assert entries[0]["properties"]["dataBars"]["positiveColor"] == _color("#222222")


def test_data_bars_remove(project_dir: Path):
    name = _table(project_dir)
    kwargs = dict(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, field="Vendas.Total Vendas")
    formatting.set_table_data_bars(color="#111111", **kwargs)

    formatting.set_table_data_bars(remove=True, **kwargs)

    assert _visual(project_dir, name)["visual"]["objects"].get("columnFormatting", []) == []


def test_data_bars_refuse_field_not_in_table(project_dir: Path):
    name = _table(project_dir)

    with pytest.raises(InvalidVisualFormattingError, match="Vendas.Produto"):
        formatting.set_table_data_bars(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            field="Vendas.Produto", color="#111111",
        )


def test_data_bars_refuse_non_table_visual(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualFormattingError, match="tabela"):
        formatting.set_table_data_bars(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            field="Vendas.Total Vendas", color="#111111",
        )


def test_data_bars_require_color_unless_removing(project_dir: Path):
    name = _table(project_dir)

    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_table_data_bars(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, field="Vendas.Total Vendas",
        )
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_table_data_bars(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            field="Vendas.Total Vendas", color="azul",
        )


# --- estilo de linha --------------------------------------------------------


def _line(project_dir: Path) -> str:
    return _add(project_dir, "lineChart", {
        "Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas", "Vendas.Vendas PY"],
    })


def test_line_style_for_one_series_uses_metadata_selector(project_dir: Path):
    name = _line(project_dir)

    formatting.set_line_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        series="Vendas.Vendas PY", line_style="dashed", width=2, show_marker=True,
    )

    entries = _visual(project_dir, name)["visual"]["objects"]["lineStyles"]
    assert entries == [{
        "properties": {
            "lineStyle": _lit("'dashed'"),
            "strokeWidth": _lit("2D"),
            "showMarker": _lit("true"),
        },
        "selector": {"metadata": "Vendas.Vendas PY"},
    }]


def test_line_style_without_series_goes_to_base_entry(project_dir: Path):
    name = _line(project_dir)

    formatting.set_line_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, interpolation="smooth",
    )
    formatting.set_line_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, series="Vendas.Vendas PY", line_style="dotted",
    )
    formatting.set_line_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, series="Vendas.Vendas PY", line_style="dashed",
    )

    entries = _visual(project_dir, name)["visual"]["objects"]["lineStyles"]
    assert entries[0] == {"properties": {"lineChartType": _lit("'smooth'")}}
    assert len(entries) == 2
    assert entries[1]["properties"]["lineStyle"] == _lit("'dashed'")


def test_line_style_rejects_bad_values_and_unknown_series(project_dir: Path):
    name = _line(project_dir)
    kwargs = dict(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name)

    with pytest.raises(InvalidVisualFormattingError, match="line_style"):
        formatting.set_line_style(line_style="wavy", **kwargs)
    with pytest.raises(InvalidVisualFormattingError, match="interpolation"):
        formatting.set_line_style(interpolation="curvy", **kwargs)
    with pytest.raises(InvalidVisualFormattingError, match="Vendas.Segmento"):
        formatting.set_line_style(series="Vendas.Segmento", line_style="dashed", **kwargs)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_line_style(**kwargs)


def test_line_style_refuses_bar_chart(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualFormattingError, match="linha"):
        formatting.set_line_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, line_style="dashed",
        )


# --- estilo de tabela/matriz (doc oficial table.md) --------------------------


def test_table_style_writes_regions_and_style_preset_none(project_dir: Path):
    name = _table(project_dir)

    formatting.set_table_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        header_font_color="#EDEDED", header_background="#303030", header_bold=True,
        row_font_color="#EDEDED", row_background="#303030",
        total_font_color="#FFFFFF", total_background="#262626", total_bold=True, font_size=9,
    )

    visual = _visual(project_dir, name)["visual"]
    objects = visual["objects"]
    assert objects["columnHeaders"] == [{"properties": {
        "fontColor": _color("#EDEDED"), "backColor": _color("#303030"), "bold": _lit("true"),
        "fontSize": _lit("9D"), "autoSizeColumnWidth": _lit("true"), "columnAdjustment": _lit("'growToFit'"),
    }}]
    assert objects["values"] == [{"properties": {
        "fontColorPrimary": _color("#EDEDED"), "fontColorSecondary": _color("#EDEDED"),
        "backColorPrimary": _color("#303030"), "backColorSecondary": _color("#303030"), "fontSize": _lit("9D"),
    }}]
    assert objects["total"] == [{"properties": {
        "fontColor": _color("#FFFFFF"), "backColor": _color("#262626"), "bold": _lit("true"), "fontSize": _lit("9D"),
    }}]
    assert visual["visualContainerObjects"]["stylePreset"] == [{"properties": {"name": _lit("'None'")}}]


def test_table_style_alternate_row_background(project_dir: Path):
    name = _table(project_dir)

    formatting.set_table_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        row_background="#303030", alt_row_background="#383838",
    )

    values = _visual(project_dir, name)["visual"]["objects"]["values"][0]["properties"]
    assert values["backColorPrimary"] == _color("#303030")
    assert values["backColorSecondary"] == _color("#383838")


def test_matrix_total_uses_row_and_column_total_and_row_headers(project_dir: Path):
    name = _add(project_dir, "pivotTable", {"Rows": ["Vendas.Segmento"], "Values": ["Vendas.Total Vendas"]})

    formatting.set_table_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        row_font_color="#EDEDED", row_background="#303030", total_font_color="#FFFFFF",
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert "total" not in objects
    assert objects["rowTotal"] == [{"properties": {"fontColor": _color("#FFFFFF")}}]
    assert objects["columnTotal"] == [{"properties": {"fontColor": _color("#FFFFFF")}}]
    assert objects["rowHeaders"] == [{"properties": {"fontColor": _color("#EDEDED"), "backColor": _color("#303030")}}]


def test_table_style_keeps_data_bars_and_other_entries(project_dir: Path):
    name = _table(project_dir)
    formatting.set_table_data_bars(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, field="Vendas.Total Vendas", color="#6B6F80",
    )

    formatting.set_table_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, row_font_color="#EDEDED")

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["columnFormatting"][0]["properties"]["dataBars"]["positiveColor"] == _color("#6B6F80")


def test_table_style_validation(project_dir: Path):
    table = _table(project_dir)
    chart = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_table_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=table)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_table_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=table, row_font_color="branco")
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_table_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=table, font_size=100)
    with pytest.raises(InvalidVisualFormattingError, match="tabela"):
        formatting.set_table_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=chart, row_font_color="#FFFFFF")


# --- formato de coluna de tabela, rótulo de rosca, largura de categoria -------


def test_table_column_format_display_units_and_precision(project_dir: Path):
    name = _table(project_dir)
    formatting.set_table_data_bars(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, field="Vendas.Total Vendas", color="#6B6F80",
    )

    formatting.set_table_column_format(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        field="Vendas.Total Vendas", display_units="millions", precision=2,
    )

    entries = _visual(project_dir, name)["visual"]["objects"]["columnFormatting"]
    assert len(entries) == 1
    props = entries[0]["properties"]
    assert props["labelDisplayUnits"] == _lit("1000000D")
    assert props["labelPrecision"] == _lit("2L")
    assert "dataBars" in props
    assert entries[0]["selector"] == {"metadata": "Vendas.Total Vendas"}


def test_table_column_format_validation(project_dir: Path):
    name = _table(project_dir)
    kwargs = dict(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name)

    with pytest.raises(InvalidVisualFormattingError, match="display_units"):
        formatting.set_table_column_format(field="Vendas.Total Vendas", display_units="auto", **kwargs)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_table_column_format(field="Vendas.Total Vendas", **kwargs)
    with pytest.raises(InvalidVisualFormattingError, match="Vendas.Produto"):
        formatting.set_table_column_format(field="Vendas.Produto", precision=1, **kwargs)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_table_column_format(field="Vendas.Total Vendas", precision=-1, **kwargs)


def test_donut_label_style_and_center_value(project_dir: Path):
    name = _add(project_dir, "donutChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    formatting.set_visual_data_labels(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        show=True, style="Percent of total", show_center_value=False,
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["labels"][0]["properties"]["labelStyle"] == _lit("'Percent of total'")
    assert objects["centerValue"] == [{"properties": {"show": _lit("false")}}]


def test_center_value_refused_on_bar_chart(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualFormattingError, match="centerValue"):
        formatting.set_visual_data_labels(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, show_center_value=False,
        )


def test_category_axis_min_category_width(project_dir: Path):
    name = _line(project_dir)

    formatting.set_visual_axis(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, axis="category", min_category_width=10,
    )

    props = _visual(project_dir, name)["visual"]["objects"]["categoryAxis"][0]["properties"]
    assert props["preferredCategoryWidth"] == _lit("10D")


# --- renomear campo só no visual (schema visualConfiguration: RoleProjection.displayName) ---


def test_rename_visual_field_sets_projection_display_name(project_dir: Path):
    name = _table(project_dir)

    result = visual_writer.set_visual_field_name(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        field="Vendas.Total Vendas", display_name="Vendas",
    )

    projections = _visual(project_dir, name)["visual"]["query"]["queryState"]["Values"]["projections"]
    renamed = next(p for p in projections if p["queryRef"] == "Vendas.Total Vendas")
    assert renamed["displayName"] == "Vendas"
    assert result["display_name"] == "Vendas"


def test_rename_visual_field_empty_name_restores_model_name(project_dir: Path):
    name = _table(project_dir)
    kwargs = dict(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, field="Vendas.Total Vendas")
    visual_writer.set_visual_field_name(display_name="Vendas", **kwargs)

    visual_writer.set_visual_field_name(display_name="", **kwargs)

    projections = _visual(project_dir, name)["visual"]["query"]["queryState"]["Values"]["projections"]
    assert all("displayName" not in p for p in projections)


def test_rename_visual_field_unknown_field(project_dir: Path):
    name = _table(project_dir)

    with pytest.raises(InvalidVisualRoleError, match="Vendas.Produto"):
        visual_writer.set_visual_field_name(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
            field="Vendas.Produto", display_name="Produto",
        )


# --- campos extras na dica de ferramenta (doc cartesian.md: role "Tooltips", kind Measure) ---


def test_bar_chart_accepts_tooltip_measures(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {
        "Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"], "Tooltips": ["Vendas.Vendas PY"],
    })

    tooltips = _visual(project_dir, name)["visual"]["query"]["queryState"]["Tooltips"]["projections"]
    assert [p["queryRef"] for p in tooltips] == ["Vendas.Vendas PY"]


def test_tooltip_role_accepts_only_measures(project_dir: Path):
    with pytest.raises(InvalidVisualRoleError, match="Tooltips"):
        _add(project_dir, "clusteredBarChart", {
            "Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"], "Tooltips": ["Vendas.Produto"],
        })


# --- estilo da dica de ferramenta -------------------------------------------
# Formato copiado do Desktop (usuário formatou a dica pela UI e salvou,
# 2026-09-30): VCO `visualTooltip` com themedTitleFontColor (rótulo),
# themedValueFontColor (valor) e themedBackground (fundo).


def test_tooltip_style_writes_themed_colors_and_keeps_tooltip_page(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual"]["visualContainerObjects"] = {"visualTooltip": [{"properties": {"type": _lit("'Canvas'")}}]}
    path.write_text(json.dumps(data), encoding="utf-8")

    formatting.set_visual_tooltip_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        label_color="#FFFFFF", value_color="#D9956B", background_color="#1E1E1E",
    )

    entries = _visual(project_dir, name)["visual"]["visualContainerObjects"]["visualTooltip"]
    assert entries == [{"properties": {
        "type": _lit("'Canvas'"),
        "themedTitleFontColor": _color("#FFFFFF"),
        "themedValueFontColor": _color("#D9956B"),
        "themedBackground": _color("#1E1E1E"),
    }}]


def test_tooltip_style_validation(project_dir: Path):
    name = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})
    kwargs = dict(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name)

    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_tooltip_style(**kwargs)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_visual_tooltip_style(background_color="preto", **kwargs)


def test_update_visual_fields_keeps_formatting_filters_and_visibility(project_dir: Path):
    name = _line(project_dir)
    visual_writer.set_visual_color(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, query_ref="Vendas.Total Vendas", hex_color="#F0C9A8",
    )
    visual_writer.set_visual_title(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, text="Tendência")
    from visuals import filter_writer
    filter_writer.add_visual_filter(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        query_ref="Vendas.Segmento", filter_type="categorical", values=["Government"],
    )
    visual_writer.set_visual_hidden(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, hidden=True)
    before = _visual(project_dir, name)

    visual_writer.update_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        fields={"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"], "Tooltips": ["Vendas.Vendas PY"]},
    )

    after = _visual(project_dir, name)
    assert after["visual"]["objects"] == before["visual"]["objects"]
    assert after["visual"]["visualContainerObjects"] == before["visual"]["visualContainerObjects"]
    assert after["filterConfig"] == before["filterConfig"]
    assert after["isHidden"] is True
    assert after["position"] == before["position"]
    assert "Tooltips" in after["visual"]["query"]["queryState"]


# --- árvore de decomposição (melhor esforço: roles do visual nativo) ---------


def test_decomposition_tree_analyze_and_explain_by(project_dir: Path):
    name = _add(project_dir, "decompositionTreeVisual", {
        "Analyze": ["Vendas.Total Vendas"], "ExplainBy": ["Vendas.Segmento", "Vendas.Produto"],
    })

    query = _visual(project_dir, name)["visual"]["query"]["queryState"]
    assert [p["queryRef"] for p in query["Analyze"]["projections"]] == ["Vendas.Total Vendas"]
    assert [p["queryRef"] for p in query["ExplainBy"]["projections"]] == ["Vendas.Segmento", "Vendas.Produto"]


def test_decomposition_tree_role_rules(project_dir: Path):
    with pytest.raises(InvalidVisualRoleError, match="Analyze"):
        _add(project_dir, "decompositionTreeVisual", {"Analyze": ["Vendas.Segmento"], "ExplainBy": ["Vendas.Produto"]})
    with pytest.raises(InvalidVisualRoleError, match="ExplainBy"):
        _add(project_dir, "decompositionTreeVisual", {"Analyze": ["Vendas.Total Vendas"], "ExplainBy": ["Vendas.Vendas PY"]})


# Formato copiado do Desktop (usuário abriu os níveis pela UI e salvou,
# 2026-10-01): `active` por nível em ExplainBy + `expansionStates` com
# isPinned/identityKeys por nível e o item aberto em root.children.


def _tree(project_dir: Path) -> str:
    return _add(project_dir, "decompositionTreeVisual", {
        "Analyze": ["Vendas.Total Vendas"], "ExplainBy": ["Vendas.Segmento", "Vendas.Produto"],
    })


def test_expand_tree_opens_first_level_and_one_item(project_dir: Path):
    name = _tree(project_dir)

    visual_writer.expand_decomposition_tree(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, path=["Government"],
    )

    visual = _visual(project_dir, name)["visual"]
    explain = visual["query"]["queryState"]["ExplainBy"]["projections"]
    assert [p["active"] for p in explain] == [True, True]
    segment_key = {"Column": {"Expression": {"SourceRef": {"Entity": "Vendas"}}, "Property": "Segmento"}}
    assert visual["expansionStates"] == [{
        "roles": ["ExplainBy"],
        "levels": [
            {"queryRefs": ["Vendas.Segmento"], "isCollapsed": True, "identityKeys": [segment_key], "isPinned": True},
            {"queryRefs": ["Vendas.Produto"], "isCollapsed": True, "isPinned": True},
        ],
        "root": {"children": [{"identityValues": [{"Literal": {"Value": "'Government'"}}], "isToggled": True}]},
    }]


def test_expand_tree_without_path_opens_only_first_level(project_dir: Path):
    name = _tree(project_dir)

    visual_writer.expand_decomposition_tree(pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, path=[])

    visual = _visual(project_dir, name)["visual"]
    assert [p["active"] for p in visual["query"]["queryState"]["ExplainBy"]["projections"]] == [True, False]
    (state,) = visual["expansionStates"]
    assert state["levels"][0] == {"queryRefs": ["Vendas.Segmento"], "isCollapsed": True, "isPinned": True}
    assert state["levels"][1] == {"queryRefs": ["Vendas.Produto"], "isCollapsed": True}
    assert "root" not in state


def test_expand_tree_validation(project_dir: Path):
    tree = _tree(project_dir)
    bars = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualRoleError, match="níveis"):
        visual_writer.expand_decomposition_tree(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=tree, path=["Government", "Paseo"],
        )
    with pytest.raises(InvalidVisualRoleError, match="árvore"):
        visual_writer.expand_decomposition_tree(pbip_path=str(project_dir), page_name="Pagina1", visual_name=bars, path=[])


# --- estilo da árvore (nomes do schema oficial de tema, visual-decompositionTreeVisual) ---


def test_tree_style_writes_each_object(project_dir: Path):
    name = _tree(project_dir)

    formatting.set_decomposition_tree_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name,
        bar_color="#F0C9A8", bar_background_color="#3A3A3A", label_color="#EDEDED", value_color="#FFFFFF",
        value_display_units="millions", value_precision=1, header_background="#303030",
        header_title_color="#EDEDED", header_subtitle_color="#9A9A9A", connector_color="#9A9A9A",
        bars_per_level=5, density="dense",
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["dataBars"][0]["properties"] == {
        "positiveBarColor": _color("#F0C9A8"), "dataBarColor": _color("#F0C9A8"),
        "dataBarBackgroundColor": _color("#3A3A3A"),
    }
    assert objects["categoryLabels"][0]["properties"] == {"categoryLabelFontColor": _color("#EDEDED")}
    assert objects["dataLabels"][0]["properties"] == {
        "dataLabelFontColor": _color("#FFFFFF"), "dataLabelDisplayUnits": _lit("1000000D"),
        "dataLabelPrecision": _lit("1L"),
    }
    assert objects["levelHeader"][0]["properties"] == {
        "levelHeaderBackgroundColor": _color("#303030"), "levelTitleFontColor": _color("#EDEDED"),
        "levelSubtitleFontColor": _color("#9A9A9A"),
    }
    assert objects["tree"][0]["properties"] == {
        "connectorDefaultColor": _color("#9A9A9A"), "barsPerLevel": _lit("5L"), "density": _lit("'dense'"),
    }


def test_tree_style_refuses_other_visuals_and_empty_call(project_dir: Path):
    tree = _tree(project_dir)
    bars = _add(project_dir, "clusteredBarChart", {"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"]})

    with pytest.raises(InvalidVisualFormattingError, match="árvore"):
        formatting.set_decomposition_tree_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=bars, bar_color="#FFFFFF")
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_decomposition_tree_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=tree)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_decomposition_tree_style(pbip_path=str(project_dir), page_name="Pagina1", visual_name=tree, density="apertado")


def test_tree_style_accent_color(project_dir: Path):
    name = _tree(project_dir)

    formatting.set_decomposition_tree_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, accent_color="#D9956B",
    )

    assert _visual(project_dir, name)["visual"]["objects"]["tree"][0]["properties"] == {"accentColor": _color("#D9956B")}


def test_tree_style_font_sizes(project_dir: Path):
    name = _tree(project_dir)

    formatting.set_decomposition_tree_style(
        pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, label_font_size=9, value_font_size=9,
    )

    objects = _visual(project_dir, name)["visual"]["objects"]
    assert objects["categoryLabels"][0]["properties"] == {"categoryLabelFontSize": _lit("9D")}
    assert objects["dataLabels"][0]["properties"] == {"dataLabelFontSize": _lit("9D")}
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_decomposition_tree_style(
            pbip_path=str(project_dir), page_name="Pagina1", visual_name=name, label_font_size=4,
        )
