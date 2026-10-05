"""Testes de visuals.validator: resolução de referências "Tabela.Campo"
contra ModelMetadata, e validação de arity/tipo por role do catálogo.

Este é o coração da garantia central do projeto: nenhum visual.json
deve ser escrito com um campo que não existe no modelo.
"""

from __future__ import annotations

import pytest

from errors import InvalidVisualRoleError, UnknownFieldError, UnknownVisualTypeError
from modeling.metadata import ColumnInfo, MeasureInfo, ModelMetadata, RelationshipInfo, TableInfo
from visuals.validator import resolve_field, validate_visual_fields


@pytest.fixture
def metadata() -> ModelMetadata:
    vendas = TableInfo(
        name="Vendas",
        columns=(
            ColumnInfo(name="RegiaoId", data_type="Int64"),
            ColumnInfo(name="Valor", data_type="Double"),
            ColumnInfo(name="Data", data_type="DateTime"),
        ),
    )
    regiao = TableInfo(
        name="Regiao",
        columns=(
            ColumnInfo(name="RegiaoId", data_type="Int64"),
            ColumnInfo(name="Nome", data_type="String"),
        ),
    )
    total_vendas = MeasureInfo(
        table_name="Vendas", name="Total Vendas", dax_expression="SUM(Vendas[Valor])"
    )
    return ModelMetadata(
        tables=(vendas, regiao),
        measures=(total_vendas,),
        relationships=(
            RelationshipInfo(
                from_table="Vendas",
                from_column="RegiaoId",
                to_table="Regiao",
                to_column="RegiaoId",
                cardinality="many_to_one",
                cross_filter_direction="single",
            ),
        ),
    )


# --- resolve_field --------------------------------------------------------


def test_resolves_column_reference(metadata: ModelMetadata):
    resolved = resolve_field(metadata, "Regiao.Nome")

    assert resolved.entity == "Regiao"
    assert resolved.property == "Nome"
    assert resolved.kind == "column"
    assert resolved.query_ref == "Regiao.Nome"
    assert resolved.native_query_ref == "Nome"


def test_resolves_measure_reference(metadata: ModelMetadata):
    resolved = resolve_field(metadata, "Vendas.Total Vendas")

    assert resolved.entity == "Vendas"
    assert resolved.property == "Total Vendas"
    assert resolved.kind == "measure"
    assert resolved.query_ref == "Vendas.Total Vendas"


def test_resolves_measure_using_its_real_home_table_even_if_caller_typed_another(
    metadata: ModelMetadata,
):
    # a medida "Total Vendas" mora em Vendas; alguém referenciando
    # "Regiao.Total Vendas" (nome de medida globalmente único) ainda
    # deve resolver, usando a tabela real da medida na query_ref
    resolved = resolve_field(metadata, "Regiao.Total Vendas")

    assert resolved.kind == "measure"
    assert resolved.entity == "Vendas"
    assert resolved.query_ref == "Vendas.Total Vendas"


def test_raises_when_table_does_not_exist(metadata: ModelMetadata):
    with pytest.raises(UnknownFieldError) as exc_info:
        resolve_field(metadata, "Clientes.Nome")
    assert exc_info.value.entity == "Clientes"
    assert exc_info.value.property == "Nome"


def test_raises_when_column_does_not_exist_in_table(metadata: ModelMetadata):
    with pytest.raises(UnknownFieldError):
        resolve_field(metadata, "Vendas.Desconto")


def test_raises_when_reference_has_no_dot(metadata: ModelMetadata):
    with pytest.raises(UnknownFieldError):
        resolve_field(metadata, "Vendas")


def test_error_includes_suggestions_for_close_match(metadata: ModelMetadata):
    with pytest.raises(UnknownFieldError) as exc_info:
        resolve_field(metadata, "Vendas.Valorr")
    assert any("Valor" in s for s in exc_info.value.suggestions)


# --- validate_visual_fields ------------------------------------------------


def test_validate_visual_fields_resolves_card(metadata: ModelMetadata):
    resolved = validate_visual_fields("card", {"Values": ["Vendas.Total Vendas"]}, metadata)

    assert set(resolved) == {"Values"}
    assert resolved["Values"][0].kind == "measure"


def test_validate_visual_fields_resolves_clustered_column_chart(metadata: ModelMetadata):
    resolved = validate_visual_fields(
        "clusteredColumnChart",
        {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
        metadata,
    )

    assert resolved["Category"][0].property == "Nome"
    assert resolved["Y"][0].property == "Total Vendas"
    assert "Series" not in resolved  # role opcional, não informado


def test_validate_visual_fields_raises_for_unknown_visual_type(metadata: ModelMetadata):
    with pytest.raises(UnknownVisualTypeError):
        validate_visual_fields("gaugeChart", {"Values": ["Vendas.Total Vendas"]}, metadata)


def test_validate_visual_fields_raises_when_required_role_missing(metadata: ModelMetadata):
    with pytest.raises(InvalidVisualRoleError, match="Category"):
        validate_visual_fields("clusteredColumnChart", {"Y": ["Vendas.Total Vendas"]}, metadata)


def test_validate_visual_fields_raises_when_role_exceeds_max_fields(metadata: ModelMetadata):
    with pytest.raises(InvalidVisualRoleError, match="Category"):
        validate_visual_fields(
            "donutChart",  # cartesiano aceita vários (drill); rosca não
            {"Category": ["Regiao.Nome", "Vendas.Data"], "Y": ["Vendas.Total Vendas"]},
            metadata,
        )


def test_validate_visual_fields_raises_when_kind_not_allowed(metadata: ModelMetadata):
    # slicer só aceita coluna, não medida
    with pytest.raises(InvalidVisualRoleError, match="Values"):
        validate_visual_fields("slicer", {"Values": ["Vendas.Total Vendas"]}, metadata)


def test_validate_visual_fields_raises_for_unknown_role_name(metadata: ModelMetadata):
    with pytest.raises(InvalidVisualRoleError, match="Legend"):
        validate_visual_fields(
            "clusteredColumnChart",
            {
                "Category": ["Regiao.Nome"],
                "Y": ["Vendas.Total Vendas"],
                "Legend": ["Regiao.Nome"],
            },
            metadata,
        )


def test_validate_visual_fields_propagates_unknown_field_before_role_checks(
    metadata: ModelMetadata,
):
    with pytest.raises(UnknownFieldError):
        validate_visual_fields("card", {"Values": ["Vendas.NaoExiste"]}, metadata)


def test_validate_visual_fields_donut_has_no_series_role(metadata: ModelMetadata):
    resolved = validate_visual_fields(
        "donutChart", {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]}, metadata
    )
    assert set(resolved) == {"Category", "Y"}
