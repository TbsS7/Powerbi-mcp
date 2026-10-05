"""Testes de visuals.filters: construtores puros (sem I/O) do JSON de
filtro com valor (filterConfig.filters[]) de página/relatório.

Estrutura conferida contra a doc oficial de autoria de PBIR
(microsoft/skills-for-fabric, references/authoring/filters.md +
expressions.md) e contra o schema filterConfiguration/semanticQuery
vendorizado -- ver docstring de visuals/filters.py.
"""

from __future__ import annotations

import re

import pytest

from errors import InvalidFilterDefinitionError
from visuals import filters
from visuals.validator import ResolvedField

SEGMENT = ResolvedField(
    entity="financials", property="Segment", kind="column",
    query_ref="financials.Segment", native_query_ref="Segment", data_type="String",
)
YEAR = ResolvedField(
    entity="financials", property="Year", kind="column",
    query_ref="financials.Year", native_query_ref="Year", data_type="Int64",
)
SALES = ResolvedField(
    entity="financials", property="Total Sales", kind="measure",
    query_ref="financials.Total Sales", native_query_ref="Total Sales",
)


def _where_condition(entry: dict) -> dict:
    return entry["filter"]["Where"][0]["Condition"]


# --- nome ---------------------------------------------------------------


def test_filter_name_is_filter_plus_24_hex():
    assert re.fullmatch(r"Filter[0-9a-f]{24}", filters.new_filter_name())


# --- literais -------------------------------------------------------------


def test_string_literal_is_single_quoted():
    assert filters.format_literal("Government", "String") == "'Government'"


def test_string_literal_escapes_single_quote():
    assert filters.format_literal("O'Brien", "String") == "'O''Brien'"


def test_integer_literal_has_L_suffix():
    assert filters.format_literal(2014, "Int64") == "2014L"


def test_double_literal_has_D_suffix():
    assert filters.format_literal(2.5, "Double") == "2.5D"
    assert filters.format_literal(100, "Double") == "100D"


def test_decimal_literal_has_M_suffix():
    assert filters.format_literal(2.4, "Decimal") == "2.4M"


def test_datetime_literal_uses_datetime_prefix():
    assert filters.format_literal("2014-01-01", "DateTime") == "datetime'2014-01-01T00:00:00'"
    assert (
        filters.format_literal("2014-01-01T10:30:00", "DateTime")
        == "datetime'2014-01-01T10:30:00'"
    )


def test_boolean_literal():
    assert filters.format_literal(True, "Boolean") == "true"


def test_unknown_data_type_raises():
    with pytest.raises(InvalidFilterDefinitionError):
        filters.format_literal("x", "Binary")


def test_non_numeric_value_for_integer_raises():
    with pytest.raises(InvalidFilterDefinitionError):
        filters.format_literal("abc", "Int64")


# --- categorical ------------------------------------------------------------


def test_categorical_top_level_field_uses_entity():
    entry = filters.categorical_filter(SEGMENT, ["Government"])
    assert entry["field"] == {
        "Column": {"Expression": {"SourceRef": {"Entity": "financials"}}, "Property": "Segment"}
    }


def test_categorical_where_uses_source_alias_not_entity():
    # A armadilha documentada pela Microsoft: dentro de Where é "Source"
    # (o alias declarado em From), não "Entity".
    entry = filters.categorical_filter(SEGMENT, ["Government"])
    alias = entry["filter"]["From"][0]["Name"]
    column = _where_condition(entry)["In"]["Expressions"][0]["Column"]
    assert column["Expression"]["SourceRef"] == {"Source": alias}
    assert "Entity" not in column["Expression"]["SourceRef"]


def test_categorical_from_declares_alias_entity_and_type_zero():
    entry = filters.categorical_filter(SEGMENT, ["Government"])
    source = entry["filter"]["From"][0]
    assert source["Entity"] == "financials"
    assert source["Type"] == 0
    assert entry["filter"]["Version"] == 2


def test_categorical_has_type_and_how_created_user():
    entry = filters.categorical_filter(SEGMENT, ["Government"])
    assert entry["type"] == "Categorical"
    assert entry["howCreated"] == "User"


def test_categorical_one_values_row_per_value():
    entry = filters.categorical_filter(SEGMENT, ["Government", "Midmarket"])
    assert _where_condition(entry)["In"]["Values"] == [
        [{"Literal": {"Value": "'Government'"}}],
        [{"Literal": {"Value": "'Midmarket'"}}],
    ]


def test_categorical_exclude_wraps_in_with_not():
    entry = filters.categorical_filter(SEGMENT, ["Government"], exclude=True)
    condition = _where_condition(entry)
    assert "In" in condition["Not"]["Expression"]


def test_categorical_empty_values_raises():
    with pytest.raises(InvalidFilterDefinitionError):
        filters.categorical_filter(SEGMENT, [])


def test_filter_on_measure_raises():
    with pytest.raises(InvalidFilterDefinitionError):
        filters.categorical_filter(SALES, ["1"])


# --- between ----------------------------------------------------------------


def test_between_is_advanced_with_lower_and_upper_bound():
    entry = filters.between_filter(YEAR, 2013, 2014)
    assert entry["type"] == "Advanced"
    between = _where_condition(entry)["Between"]
    assert between["LowerBound"] == {"Literal": {"Value": "2013L"}}
    assert between["UpperBound"] == {"Literal": {"Value": "2014L"}}
    assert "Source" in between["Expression"]["Column"]["Expression"]["SourceRef"]


def test_between_without_bounds_raises():
    with pytest.raises(InvalidFilterDefinitionError):
        filters.between_filter(YEAR, None, 2014)


# --- comparison -------------------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "kind"), [("eq", 0), ("gt", 1), ("gte", 2), ("lt", 3), ("lte", 4)]
)
def test_comparison_maps_operator_to_comparison_kind(operator, kind):
    entry = filters.comparison_filter(YEAR, operator, 2014)
    comparison = _where_condition(entry)["Comparison"]
    assert comparison["ComparisonKind"] == kind
    assert comparison["Right"] == {"Literal": {"Value": "2014L"}}
    assert entry["type"] == "Advanced"


def test_comparison_unknown_operator_raises():
    with pytest.raises(InvalidFilterDefinitionError):
        filters.comparison_filter(YEAR, "contains", 2014)


# --- filter_matches ---------------------------------------------------------


def test_filter_matches_respects_how_created():
    entry = filters.categorical_filter(SEGMENT, ["Government"])
    assert filters.filter_matches(entry, "financials", "Segment", "User")
    assert not filters.filter_matches(entry, "financials", "Segment", "Drillthrough")
    assert not filters.filter_matches(entry, "financials", "Country", "User")


# Coluna de tabela calculada (ex: parâmetro de campo) lida do TMDL: o TMDL
# não grava `dataType` nesse caso (o motor deduz), então o tipo chega
# vazio -- o literal é deduzido pelo tipo do valor em Python.
@pytest.mark.parametrize(("value", "expected"), [
    ("Vendas Totais", "'Vendas Totais'"),
    ("D'Ávila", "'D''Ávila'"),
    (True, "true"),
    (3, "3L"),
    (2.5, "2.5D"),
])
def test_format_literal_unknown_type_infers_from_value(value, expected):
    assert filters.format_literal(value, "") == expected
    assert filters.format_literal(value, None) == expected
