"""Testes de visuals.catalog: o registry declarativo dos tipos de
visual suportados e seus roles.
"""

from __future__ import annotations

import pytest

from errors import UnknownVisualTypeError
from visuals.catalog import VISUAL_TYPES, get_visual_spec


def test_all_visual_types_are_registered():
    assert set(VISUAL_TYPES) == {
        "card",
        "clusteredColumnChart",
        "clusteredBarChart",
        "lineChart",
        "donutChart",
        "tableEx",
        "slicer",
        "advancedSlicerVisual", "decompositionTreeVisual", "lineClusteredColumnComboChart",
        "textbox",
        "pivotTable",
        "waterfallChart",
        "scatterChart",
        "columnChart",
        "barChart",
        "areaChart",
        "stackedAreaChart",
        "hundredPercentStackedColumnChart",
        "hundredPercentStackedBarChart",
        "pieChart",
        "treemap",
        "funnel",
        "gauge",
        "kpi",
        "cardVisual",
        "azureMap",
    }


@pytest.mark.parametrize(
    "visual_type",
    [
        "columnChart", "barChart", "areaChart", "stackedAreaChart",
        "hundredPercentStackedColumnChart", "hundredPercentStackedBarChart",
    ],
)
def test_stacked_and_area_charts_share_category_y_series_shape(visual_type: str):
    spec = get_visual_spec(visual_type)
    assert set(spec.roles) == {"Category", "Y", "Series", "Tooltips"}  # Tooltips: doc cartesian.md
    assert (spec.roles["Category"].min_fields, spec.roles["Category"].max_fields) == (1, None)  # vários campos = drill (cartesian.md)
    assert spec.roles["Y"].min_fields == 1
    assert (spec.roles["Series"].min_fields, spec.roles["Series"].max_fields) == (0, 1)


def test_pie_chart_has_category_and_y_but_no_series():
    spec = get_visual_spec("pieChart")
    assert set(spec.roles) == {"Category", "Y"}


def test_treemap_has_group_optional_details_and_values():
    spec = get_visual_spec("treemap")
    assert set(spec.roles) == {"Group", "Details", "Values"}
    assert spec.roles["Group"].min_fields == 1
    assert (spec.roles["Details"].min_fields, spec.roles["Details"].max_fields) == (0, 1)
    assert spec.roles["Values"].min_fields == 1


def test_funnel_has_category_and_single_y():
    spec = get_visual_spec("funnel")
    assert set(spec.roles) == {"Category", "Y"}
    assert (spec.roles["Y"].min_fields, spec.roles["Y"].max_fields) == (1, 1)


def test_gauge_has_y_and_optional_min_max_target():
    spec = get_visual_spec("gauge")
    assert set(spec.roles) == {"Y", "MinValue", "MaxValue", "TargetValue"}
    assert (spec.roles["Y"].min_fields, spec.roles["Y"].max_fields) == (1, 1)
    assert spec.roles["MinValue"].min_fields == 0


def test_kpi_has_required_indicator_and_trendline_and_optional_goal():
    """TrendLine é obrigatório -- validado ao vivo: sem ele, o KPI
    nativo renderiza só o título, sem indicador nem sparkline."""
    spec = get_visual_spec("kpi")
    assert set(spec.roles) == {"Indicator", "TrendLine", "Goal"}
    assert (spec.roles["Indicator"].min_fields, spec.roles["Indicator"].max_fields) == (1, 1)
    assert (spec.roles["TrendLine"].min_fields, spec.roles["TrendLine"].max_fields) == (1, 1)
    assert (spec.roles["Goal"].min_fields, spec.roles["Goal"].max_fields) == (0, 1)


def test_card_visual_has_single_data_role_accepting_many_fields():
    """cardVisual é o visual de cartão atual (o "card" legado que já
    existia continua registrado separadamente, sem mudança)."""
    spec = get_visual_spec("cardVisual")
    assert set(spec.roles) == {"Data"}
    assert spec.roles["Data"].min_fields == 1
    assert spec.roles["Data"].max_fields is None


def test_azure_map_has_required_category_and_optional_size_series_x_y():
    spec = get_visual_spec("azureMap")
    assert set(spec.roles) == {"Category", "Size", "Series", "X", "Y"}
    assert (spec.roles["Category"].min_fields, spec.roles["Category"].max_fields) == (1, 1)
    assert spec.roles["Size"].min_fields == 0


def test_pivot_table_has_rows_columns_and_values_roles():
    """pivotTable é o nome interno real do visual "matriz" no PBIR --
    confirmado contra a referência oficial da Microsoft para autoria de
    PBIR (skills-for-fabric), não suposto."""
    spec = get_visual_spec("pivotTable")
    assert set(spec.roles) == {"Rows", "Columns", "Values"}
    assert spec.roles["Rows"].allowed_kinds == ("column",)
    assert spec.roles["Columns"].allowed_kinds == ("column",)
    assert spec.roles["Values"].min_fields == 1
    assert set(spec.roles["Values"].allowed_kinds) == {"measure", "column"}


def test_waterfall_chart_has_category_y_and_optional_breakdown():
    spec = get_visual_spec("waterfallChart")
    assert set(spec.roles) == {"Category", "Y", "Breakdown"}
    assert (spec.roles["Category"].min_fields, spec.roles["Category"].max_fields) == (1, 1)
    assert (spec.roles["Y"].min_fields, spec.roles["Y"].max_fields) == (1, 1)
    assert (spec.roles["Breakdown"].min_fields, spec.roles["Breakdown"].max_fields) == (0, 1)


def test_scatter_chart_has_category_x_y_and_optional_size_and_series():
    spec = get_visual_spec("scatterChart")
    assert set(spec.roles) == {"Category", "X", "Y", "Size", "Series"}
    assert (spec.roles["Category"].min_fields, spec.roles["Category"].max_fields) == (1, 1)
    assert (spec.roles["X"].min_fields, spec.roles["X"].max_fields) == (1, 1)
    assert (spec.roles["Y"].min_fields, spec.roles["Y"].max_fields) == (1, 1)
    assert spec.roles["Size"].min_fields == 0
    assert spec.roles["Series"].allowed_kinds == ("column",)


def test_textbox_has_no_roles_and_is_marked_as_text_visual():
    """textbox não usa query/fields como os outros -- o conteúdo é texto
    direto (objects.general[].properties.paragraphs), não uma referência
    de campo. Formato confirmado contra referência oficial da Microsoft
    para autoria de PBIR (skills-for-fabric), não suposto."""
    spec = get_visual_spec("textbox")
    assert spec.roles == {}
    assert spec.is_text_visual is True


@pytest.mark.parametrize(
    "visual_type", ["card", "clusteredColumnChart", "donutChart", "tableEx", "slicer"]
)
def test_data_bound_visuals_are_not_text_visuals(visual_type: str):
    assert get_visual_spec(visual_type).is_text_visual is False


def test_card_has_single_required_values_role_accepting_measure_or_column():
    spec = get_visual_spec("card")
    assert set(spec.roles) == {"Values"}
    role = spec.roles["Values"]
    assert role.min_fields == 1
    assert role.max_fields == 1
    assert set(role.allowed_kinds) == {"measure", "column"}


@pytest.mark.parametrize("visual_type", ["clusteredColumnChart", "clusteredBarChart", "lineChart"])
def test_column_bar_line_charts_have_category_y_and_optional_series(visual_type: str):
    spec = get_visual_spec(visual_type)
    assert set(spec.roles) == {"Category", "Y", "Series", "Tooltips"}  # Tooltips: doc cartesian.md

    category = spec.roles["Category"]
    assert (category.min_fields, category.max_fields) == (1, None)  # vários campos = drill (cartesian.md)
    assert category.allowed_kinds == ("column",)

    y = spec.roles["Y"]
    assert y.min_fields == 1
    assert y.max_fields is None
    assert set(y.allowed_kinds) == {"measure", "column"}

    series = spec.roles["Series"]
    assert (series.min_fields, series.max_fields) == (0, 1)
    assert series.allowed_kinds == ("column",)


def test_donut_chart_has_category_and_y_but_no_series():
    spec = get_visual_spec("donutChart")
    assert set(spec.roles) == {"Category", "Y"}
    assert spec.roles["Category"].allowed_kinds == ("column",)
    assert set(spec.roles["Y"].allowed_kinds) == {"measure", "column"}


def test_table_ex_has_single_values_role_accepting_many_fields():
    spec = get_visual_spec("tableEx")
    assert set(spec.roles) == {"Values"}
    role = spec.roles["Values"]
    assert role.min_fields == 1
    assert role.max_fields is None
    assert set(role.allowed_kinds) == {"measure", "column"}


def test_slicer_has_single_values_role_accepting_only_column():
    spec = get_visual_spec("slicer")
    assert set(spec.roles) == {"Values"}
    role = spec.roles["Values"]
    assert (role.min_fields, role.max_fields) == (1, 1)
    assert role.allowed_kinds == ("column",)


def test_get_visual_spec_raises_for_unknown_type():
    with pytest.raises(UnknownVisualTypeError) as exc_info:
        get_visual_spec("gaugeChart")

    assert exc_info.value.visual_type == "gaugeChart"
    assert "card" in exc_info.value.known_types
