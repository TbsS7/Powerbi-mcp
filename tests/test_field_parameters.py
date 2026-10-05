"""Testes de modeling.field_parameters: build_field_parameter_dax
(função pura) e create_field_parameter (composição sobre
modeling.operations, via FakeTomRuntime -- nenhum toca .NET)."""

from __future__ import annotations

import pytest

from errors import (
    ColumnNotFoundError,
    FieldParameterError,
    TableAlreadyExistsError,
    TableNotFoundError,
)
from modeling import connection, field_parameters
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime


# --- build_field_parameter_dax (função pura) --------------------------


def test_build_dax_one_entry():
    dax = field_parameters.build_field_parameter_dax([("Total Vendas", "Vendas", "Total Vendas")])
    assert dax == '{("Total Vendas", NAMEOF(\'Vendas\'[Total Vendas]), 0)}'


def test_build_dax_multiple_entries_in_order():
    dax = field_parameters.build_field_parameter_dax(
        [
            ("Cliente", "Clientes", "Nome"),
            ("Categoria", "Produtos", "Categoria"),
        ]
    )
    assert dax == (
        '{("Cliente", NAMEOF(\'Clientes\'[Nome]), 0), '
        '("Categoria", NAMEOF(\'Produtos\'[Categoria]), 1)}'
    )


# --- create_field_parameter ---------------------------------------------


@pytest.fixture
def fake() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas")
    runtime.add_table(
        TableInfo(
            name="Vendas",
            columns=(ColumnInfo(name="Valor", data_type="Double"),),
        )
    )
    runtime.add_table(
        TableInfo(
            name="Produtos",
            columns=(
                ColumnInfo(name="Categoria", data_type="String"),
                ColumnInfo(name="Nome", data_type="String"),
            ),
        )
    )
    runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    runtime.create_measure("Vendas", "Total Custo", "SUM(Vendas[Custo])", "#,##0.00")
    runtime.calls.clear()
    connection.set_active_runtime(runtime)
    return runtime


def test_creates_table_with_hidden_helper_columns_and_sort(fake: FakeTomRuntime):
    result = field_parameters.create_field_parameter(
        table_name="Metricas",
        fields=["Vendas.Total Vendas", "Vendas.Total Custo"],
    )

    assert result == {
        "table_name": "Metricas",
        "fields": ["Vendas.Total Vendas", "Vendas.Total Custo"],
        "display_names": ["Total Vendas", "Total Custo"],
        "display_column": "Value1",
    }

    create_call = next(c for c in fake.calls if c[0] == "create_calculated_table")
    assert create_call[1]["table_name"] == "Metricas"
    assert create_call[1]["dax_expression"] == (
        '{("Total Vendas", NAMEOF(\'Vendas\'[Total Vendas]), 0), '
        '("Total Custo", NAMEOF(\'Vendas\'[Total Custo]), 1)}'
    )

    # confirmado ao vivo: sem isso a tabela existe mas evaluate_dax
    # recusa com "does not hold any data" -- refresh_table precisa vir
    # depois de criar e antes de configurar as colunas.
    refresh_call = next(c for c in fake.calls if c[0] == "refresh_table")
    assert refresh_call[1] == {"table_name": "Metricas"}
    assert fake.calls.index(refresh_call) > fake.calls.index(create_call)

    visibility_calls = [c[1] for c in fake.calls if c[0] == "set_column_visibility"]
    assert visibility_calls == [
        {"table_name": "Metricas", "column_name": "Value2", "is_hidden": True},
        {"table_name": "Metricas", "column_name": "Value3", "is_hidden": True},
    ]

    sort_call = next(c for c in fake.calls if c[0] == "set_column_sort_by")
    assert sort_call[1] == {
        "table_name": "Metricas", "column_name": "Value1", "sort_by_column": "Value3",
    }

    # confirmado ao vivo: sem essas duas propriedades, um cartão/gráfico
    # vinculado ao parâmetro dá "Missing_References" -- ver docstring
    # do módulo.
    related_call = next(c for c in fake.calls if c[0] == "set_column_related_column")
    assert related_call[1] == {
        "table_name": "Metricas", "column_name": "Value1", "grouping_column_name": "Value2",
    }
    ext_prop_call = next(c for c in fake.calls if c[0] == "set_column_extended_property")
    assert ext_prop_call[1] == {
        "table_name": "Metricas", "column_name": "Value2",
        "property_name": "ParameterMetadata", "json_value": '{\n  "version": 3,\n  "kind": 2\n}',
    }

    assert fake.calls[-1][0] == "save_changes"
    assert fake.save_changes_count == 2  # create_table salva sozinho + o save final


def test_uses_custom_display_names(fake: FakeTomRuntime):
    result = field_parameters.create_field_parameter(
        table_name="Metricas",
        fields=["Vendas.Total Vendas", "Vendas.Total Custo"],
        display_names=["Receita", "Custo"],
    )

    assert result["display_names"] == ["Receita", "Custo"]
    create_call = next(c for c in fake.calls if c[0] == "create_calculated_table")
    assert '"Receita"' in create_call[1]["dax_expression"]
    assert '"Custo"' in create_call[1]["dax_expression"]


def test_resolves_a_column_field(fake: FakeTomRuntime):
    result = field_parameters.create_field_parameter(
        table_name="Dimensoes", fields=["Produtos.Categoria"],
    )

    assert result["fields"] == ["Produtos.Categoria"]
    assert result["display_names"] == ["Categoria"]


def test_save_false_skips_only_the_final_save(fake: FakeTomRuntime):
    field_parameters.create_field_parameter(
        table_name="Metricas", fields=["Vendas.Total Vendas"], save=False,
    )

    # create_table sempre salva (precisa processar pra descobrir as
    # colunas Value1/2/3) -- só o save final é que respeita save=False.
    assert fake.save_changes_count == 1


def test_raises_for_empty_fields(fake: FakeTomRuntime):
    with pytest.raises(FieldParameterError):
        field_parameters.create_field_parameter(table_name="Metricas", fields=[])
    assert fake.written_calls() == []


def test_raises_when_display_names_length_mismatches_fields(fake: FakeTomRuntime):
    with pytest.raises(FieldParameterError):
        field_parameters.create_field_parameter(
            table_name="Metricas",
            fields=["Vendas.Total Vendas", "Vendas.Total Custo"],
            display_names=["Só um nome"],
        )
    assert fake.written_calls() == []


def test_raises_when_a_field_does_not_exist(fake: FakeTomRuntime):
    with pytest.raises(ColumnNotFoundError):
        field_parameters.create_field_parameter(table_name="Metricas", fields=["Vendas.Fantasma"])
    assert fake.written_calls() == []


def test_raises_when_field_table_does_not_exist(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        field_parameters.create_field_parameter(table_name="Metricas", fields=["Fantasma.Coisa"])
    assert fake.written_calls() == []


def test_raises_for_reference_without_dot(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        field_parameters.create_field_parameter(table_name="Metricas", fields=["TotalVendas"])
    assert fake.written_calls() == []


def test_raises_when_table_name_already_exists(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Metricas", columns=()))
    fake.calls.clear()

    with pytest.raises(TableAlreadyExistsError):
        field_parameters.create_field_parameter(table_name="Metricas", fields=["Vendas.Total Vendas"])
    assert fake.written_calls() == []
