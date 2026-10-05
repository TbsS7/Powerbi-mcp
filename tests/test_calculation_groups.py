"""Testes de modeling.calculation_groups (via FakeTomRuntime -- nenhum
toca .NET). Estrutura conforme a doc oficial de calculation groups
(TMSL/TMDL de exemplo) -- ver docstring do módulo."""

from __future__ import annotations

import pytest

from errors import (
    CalculationGroupNotFoundError,
    CalculationItemAlreadyExistsError,
    CalculationItemNotFoundError,
    ImplicitMeasuresMustBeDiscouragedError,
    InvalidCalculationGroupError,
    NotADateColumnError,
    TableAlreadyExistsError,
    UnknownTimeIntelligenceVariantError,
)
from modeling import calculation_groups, connection, time_intelligence
from modeling.metadata import CalculationItemInfo, ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime

ITEMS = [
    {"name": "Atual", "expression": "SELECTEDMEASURE()"},
    {"name": "Dobro", "expression": "SELECTEDMEASURE() * 2", "format_string_expression": '"0.0"'},
]


@pytest.fixture
def fake() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas")
    runtime.add_table(
        TableInfo(
            name="Datas",
            columns=(
                ColumnInfo(name="Data", data_type="DateTime"),
                ColumnInfo(name="Ano", data_type="Int64"),
            ),
        )
    )
    connection.set_active_runtime(runtime)
    return runtime


# --- DiscourageImplicitMeasures (opt-in explícito) -------------------------


def test_refuses_without_opt_in_when_implicit_measures_allowed(fake: FakeTomRuntime):
    with pytest.raises(ImplicitMeasuresMustBeDiscouragedError):
        calculation_groups.create_calculation_group(table_name="Calculos", items=ITEMS)
    assert fake.written_calls() == []


def test_opt_in_turns_flag_on_and_reports_it(fake: FakeTomRuntime):
    result = calculation_groups.create_calculation_group(
        table_name="Calculos", items=ITEMS, allow_discourage_implicit_measures=True
    )
    assert result["discourage_implicit_measures_enabled_now"] is True
    assert fake.discourage_implicit_measures is True
    names = [c[0] for c in fake.written_calls()]
    assert names.index("set_discourage_implicit_measures") < names.index("create_calculation_group")


def test_no_opt_in_needed_when_flag_already_on(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    result = calculation_groups.create_calculation_group(table_name="Calculos", items=ITEMS)
    assert result["discourage_implicit_measures_enabled_now"] is False
    assert "set_discourage_implicit_measures" not in [c[0] for c in fake.written_calls()]


# --- create_calculation_group ---------------------------------------------


def test_create_assigns_sequential_ordinals_and_defaults(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    result = calculation_groups.create_calculation_group(table_name="Calculos", items=ITEMS, precedence=10)

    call = next(c for c in fake.calls if c[0] == "create_calculation_group")[1]
    assert call["table_name"] == "Calculos"
    assert call["column_name"] == "Calculos"  # default = nome da tabela
    assert call["precedence"] == 10
    assert call["items"] == (
        CalculationItemInfo(name="Atual", expression="SELECTEDMEASURE()", ordinal=0),
        CalculationItemInfo(
            name="Dobro", expression="SELECTEDMEASURE() * 2", ordinal=1, format_string_expression='"0.0"'
        ),
    )
    assert [i["name"] for i in result["items"]] == ["Atual", "Dobro"]


def test_create_saves_then_refreshes(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    result = calculation_groups.create_calculation_group(
        table_name="Calculos", items=ITEMS, column_name="Cálculo"
    )
    names = [c[0] for c in fake.written_calls()]
    assert names[-2:] == ["save_changes", "refresh_table"]
    assert result["refreshed"] is True
    assert result["column_name"] == "Cálculo"


def test_create_save_false_skips_save_and_refresh(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    result = calculation_groups.create_calculation_group(table_name="Calculos", items=ITEMS, save=False)
    assert fake.save_changes_count == 0
    assert result["refreshed"] is False


def test_create_rejects_existing_table(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    with pytest.raises(TableAlreadyExistsError):
        calculation_groups.create_calculation_group(table_name="Datas", items=ITEMS)


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"name": "", "expression": "SELECTEDMEASURE()"}],
        [{"name": "A", "expression": ""}],
        [{"name": "A", "expression": "1"}, {"name": "A", "expression": "2"}],
    ],
)
def test_create_rejects_invalid_items(fake: FakeTomRuntime, items):
    fake.discourage_implicit_measures = True
    with pytest.raises(InvalidCalculationGroupError):
        calculation_groups.create_calculation_group(table_name="Calculos", items=items)
    assert fake.written_calls() == []


# --- itens -------------------------------------------------------------------


@pytest.fixture
def with_group(fake: FakeTomRuntime) -> FakeTomRuntime:
    fake.discourage_implicit_measures = True
    calculation_groups.create_calculation_group(table_name="Calculos", items=ITEMS)
    fake.calls.clear()
    return fake


def test_add_item_gets_next_ordinal(with_group: FakeTomRuntime):
    result = calculation_groups.add_calculation_item(
        table_name="Calculos", item_name="Triplo", expression="SELECTEDMEASURE() * 3"
    )
    assert result["ordinal"] == 2
    assert [c[0] for c in with_group.written_calls()] == [
        "add_calculation_item", "save_changes", "refresh_table",
    ]


def test_add_item_rejects_duplicate(with_group: FakeTomRuntime):
    with pytest.raises(CalculationItemAlreadyExistsError):
        calculation_groups.add_calculation_item(
            table_name="Calculos", item_name="Atual", expression="SELECTEDMEASURE()"
        )


def test_add_item_rejects_non_calculation_group_table(with_group: FakeTomRuntime):
    with pytest.raises(CalculationGroupNotFoundError):
        calculation_groups.add_calculation_item(table_name="Datas", item_name="X", expression="1")


def test_delete_item(with_group: FakeTomRuntime):
    calculation_groups.delete_calculation_item(table_name="Calculos", item_name="Dobro")
    [group] = calculation_groups.list_calculation_groups()
    assert [i["name"] for i in group["items"]] == ["Atual"]


def test_delete_item_rejects_unknown(with_group: FakeTomRuntime):
    with pytest.raises(CalculationItemNotFoundError):
        calculation_groups.delete_calculation_item(table_name="Calculos", item_name="Fantasma")


def test_list_returns_items_ordered_by_ordinal(with_group: FakeTomRuntime):
    [group] = calculation_groups.list_calculation_groups()
    assert group["table_name"] == "Calculos"
    assert group["column_name"] == "Calculos"
    assert [(i["name"], i["ordinal"]) for i in group["items"]] == [("Atual", 0), ("Dobro", 1)]
    assert with_group.written_calls() == []


# --- inteligência de tempo ---------------------------------------------------


def test_calc_item_dax_uses_selectedmeasure():
    assert (
        time_intelligence.build_time_intelligence_calculation_item_dax("Datas", "Data", "YTD")
        == "TOTALYTD(SELECTEDMEASURE(), 'Datas'[Data])"
    )
    assert (
        time_intelligence.build_time_intelligence_calculation_item_dax("Datas", "Data", "PY")
        == "CALCULATE(SELECTEDMEASURE(), SAMEPERIODLASTYEAR('Datas'[Data]))"
    )


def test_time_intelligence_group_builds_items(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    result = calculation_groups.create_time_intelligence_calculation_group(
        table_name="Inteligencia de Tempo", date_table="Datas", date_column="Data",
        variants=["YTD", "PY", "YoY"],
    )

    items = {i["name"]: i for i in result["items"]}
    assert list(items) == ["Atual", "YTD", "PY", "YoY %"]
    assert items["Atual"]["expression"] == "SELECTEDMEASURE()"
    assert items["YTD"]["format_string_expression"] is None
    assert items["YoY %"]["format_string_expression"] == '"0.0%"'
    assert "SELECTEDMEASURE()" in items["YoY %"]["expression"]


def test_time_intelligence_group_without_current_item(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    result = calculation_groups.create_time_intelligence_calculation_group(
        table_name="TI", date_table="Datas", date_column="Data", variants=["YTD"], include_current=False,
    )
    assert [i["name"] for i in result["items"]] == ["YTD"]


def test_time_intelligence_group_validates_date_column(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    with pytest.raises(NotADateColumnError):
        calculation_groups.create_time_intelligence_calculation_group(
            table_name="TI", date_table="Datas", date_column="Ano", variants=["YTD"],
        )
    assert fake.written_calls() == []


def test_time_intelligence_group_rejects_unknown_variant(fake: FakeTomRuntime):
    fake.discourage_implicit_measures = True
    with pytest.raises(UnknownTimeIntelligenceVariantError):
        calculation_groups.create_time_intelligence_calculation_group(
            table_name="TI", date_table="Datas", date_column="Data", variants=["Fantasma"],
        )
