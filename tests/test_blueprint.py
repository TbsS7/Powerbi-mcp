"""Testes de orchestrator.blueprint: os modelos Pydantic que definem o
shape do blueprint aceito por apply_dashboard_blueprint.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.blueprint import DashboardBlueprint, NewMeasure, NewRelationship, NewTable, PageSpec, VisualSpec


def test_empty_blueprint_is_valid():
    blueprint = DashboardBlueprint()
    assert blueprint.new_tables == []
    assert blueprint.new_measures == []
    assert blueprint.new_relationships == []
    assert blueprint.pages == []


def test_full_blueprint_shape():
    blueprint = DashboardBlueprint(
        new_tables=[NewTable(table_name="Regiao", dax_expression="CALENDAR(DATE(2024,1,1), DATE(2024,12,31))")],
        new_measures=[
            NewMeasure(table_name="Vendas", measure_name="Total Vendas", dax_expression="SUM(Vendas[Valor])")
        ],
        new_relationships=[
            NewRelationship(from_table="Vendas", from_column="RegiaoId", to_table="Regiao", to_column="RegiaoId")
        ],
        pages=[
            PageSpec(
                page_name="Pagina1",
                display_name="Visão Geral",
                visuals=[
                    VisualSpec(
                        visual_type="card", x=0, y=0, width=200, height=100,
                        fields={"Values": ["Vendas.Total Vendas"]},
                    )
                ],
                layout="kpi_row",
            )
        ],
    )
    assert blueprint.new_tables[0].table_name == "Regiao"
    assert blueprint.pages[0].visuals[0].visual_type == "card"


def test_new_table_rejects_unknown_field():
    # Power Query foi removido (decisão de projeto) -- NewTable só
    # aceita table_name/dax_expression; "mode" não existe mais.
    with pytest.raises(ValidationError):
        NewTable(table_name="X", mode="power_query", expression="...")


def test_new_table_requires_dax_expression():
    with pytest.raises(ValidationError):
        NewTable(table_name="X")


def test_new_relationship_defaults():
    rel = NewRelationship(from_table="Vendas", from_column="RegiaoId", to_table="Regiao", to_column="RegiaoId")
    assert rel.cardinality == "many_to_one"
    assert rel.cross_filter_direction == "single"


def test_new_relationship_rejects_invalid_cardinality():
    with pytest.raises(ValidationError):
        NewRelationship(
            from_table="Vendas", from_column="RegiaoId", to_table="Regiao", to_column="RegiaoId",
            cardinality="many_to_many",
        )


def test_page_spec_layout_is_optional():
    page = PageSpec(page_name="Pagina1")
    assert page.layout is None
    assert page.visuals == []


def test_page_spec_rejects_invalid_layout():
    with pytest.raises(ValidationError):
        PageSpec(page_name="Pagina1", layout="carousel")


def test_dashboard_blueprint_rejects_unknown_top_level_field():
    with pytest.raises(ValidationError):
        DashboardBlueprint.model_validate({"totally_unknown_field": True})


def test_dashboard_blueprint_model_json_schema_is_generatable():
    schema = DashboardBlueprint.model_json_schema()
    assert schema["title"] == "DashboardBlueprint"
    assert "properties" in schema


# --- título e fundo da página (acabamento automático) ------------------------


def test_page_title_defaults():
    from orchestrator.blueprint import PageTitle

    page = PageSpec(page_name="Pagina1", title={"text": "Dashboard de Vendas"})

    assert isinstance(page.title, PageTitle)
    assert page.title.text == "Dashboard de Vendas"
    assert page.title.font_size == 20
    assert page.title.bold is True
    assert page.title.color == "#FFFFFF"
    assert page.title.background_color == "#1F3864"
    assert page.title.alignment == "center"
    assert page.title.height == 56
    assert page.background_color is None


def test_page_title_and_background_are_optional():
    page = PageSpec(page_name="Pagina1")
    assert page.title is None
    assert page.background_color is None


@pytest.mark.parametrize("title", [
    {"text": ""},
    {"text": "T", "color": "branco"},
    {"text": "T", "background_color": "1F3864"},
    {"text": "T", "font_size": 7},
    {"text": "T", "font_size": 61},
    {"text": "T", "alignment": "justify"},
    {"text": "T", "height": 0},
    {"text": "T", "height": 400},
    {"text": "T", "cor": "#FFFFFF"},
])
def test_page_title_rejects_invalid_values(title):
    with pytest.raises(ValidationError):
        PageSpec(page_name="Pagina1", title=title)


def test_page_background_color_must_be_hex():
    with pytest.raises(ValidationError):
        PageSpec(page_name="Pagina1", background_color="cinza")
    assert PageSpec(page_name="Pagina1", background_color="#F3F2F1").background_color == "#F3F2F1"
