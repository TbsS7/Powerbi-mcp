"""Testes de orchestrator.planner: plan_dashboard não escreve nada, só
reúne metadata + schema do blueprint + catálogo de visuais.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from errors import SemanticModelNotFoundError
from orchestrator.planner import plan_dashboard

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pbip"


def test_plan_dashboard_includes_model_metadata_from_tmdl():
    result = plan_dashboard(
        description="dashboard de vendas por região", pbip_path=str(FIXTURE_ROOT / "Vendas.pbip")
    )

    table_names = {t["name"] for t in result["model_metadata"]["tables"]}
    assert table_names == {"Vendas", "Regiao"}


def test_plan_dashboard_includes_blueprint_schema():
    result = plan_dashboard(description="x", pbip_path=str(FIXTURE_ROOT / "Vendas.pbip"))

    schema = result["blueprint_schema"]
    assert schema["title"] == "DashboardBlueprint"
    assert "new_tables" in schema["properties"]
    assert "pages" in schema["properties"]


def test_plan_dashboard_includes_visual_catalog_with_all_data_bound_types():
    result = plan_dashboard(description="x", pbip_path=str(FIXTURE_ROOT / "Vendas.pbip"))

    catalog = result["visual_catalog"]
    assert set(catalog) == {
        "card", "clusteredColumnChart", "clusteredBarChart", "lineChart",
        "donutChart", "tableEx", "slicer", "pivotTable", "waterfallChart",
        "scatterChart", "columnChart", "barChart", "areaChart",
        "stackedAreaChart", "hundredPercentStackedColumnChart",
        "hundredPercentStackedBarChart", "pieChart", "treemap", "funnel",
        "gauge", "kpi", "cardVisual", "azureMap", "advancedSlicerVisual", "decompositionTreeVisual", "lineClusteredColumnComboChart",
    }
    assert catalog["card"]["Values"]["min_fields"] == 1
    assert catalog["card"]["Values"]["allowed_kinds"] == ["measure", "column"]


def test_plan_dashboard_includes_layout_options():
    result = plan_dashboard(description="x", pbip_path=str(FIXTURE_ROOT / "Vendas.pbip"))
    assert set(result["layout_options"]) == {"grid", "kpi_row"}


def test_plan_dashboard_echoes_description():
    result = plan_dashboard(description="dashboard de vendas", pbip_path=str(FIXTURE_ROOT / "Vendas.pbip"))
    assert result["description"] == "dashboard de vendas"


def test_plan_dashboard_raises_when_no_metadata_source(tmp_path: Path):
    empty_dir = tmp_path / "nao-e-um-projeto"
    empty_dir.mkdir()

    with pytest.raises(SemanticModelNotFoundError):
        plan_dashboard(description="x", pbip_path=str(empty_dir))


def test_plan_dashboard_recommends_title_and_current_card_visual():
    from orchestrator.planner import _INSTRUCTIONS

    assert "PageSpec.title" in _INSTRUCTIONS
    assert "cardVisual" in _INSTRUCTIONS
