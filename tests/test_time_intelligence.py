"""Testes de modeling.time_intelligence: build_time_intelligence_dax
(função pura) e create_time_intelligence_measures (composição sobre
modeling.operations.create_measure, via FakeTomRuntime -- nenhum toca
.NET)."""

from __future__ import annotations

import pytest

from errors import (
    ColumnNotFoundError,
    MeasureAlreadyExistsError,
    MeasureNotFoundError,
    NotADateColumnError,
    TableNotFoundError,
    UnknownTimeIntelligenceVariantError,
)
from modeling import connection, time_intelligence
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime


# --- build_time_intelligence_dax (função pura) ------------------------


def test_build_dax_ytd():
    dax = time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "YTD")
    assert dax == "TOTALYTD([Total Vendas], 'Datas'[Data])"


def test_build_dax_qtd():
    dax = time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "QTD")
    assert dax == "TOTALQTD([Total Vendas], 'Datas'[Data])"


def test_build_dax_mtd():
    dax = time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "MTD")
    assert dax == "TOTALMTD([Total Vendas], 'Datas'[Data])"


def test_build_dax_py():
    dax = time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "PY")
    assert dax == "CALCULATE([Total Vendas], SAMEPERIODLASTYEAR('Datas'[Data]))"


def test_build_dax_pm():
    dax = time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "PM")
    assert dax == "CALCULATE([Total Vendas], DATEADD('Datas'[Data], -1, MONTH))"


def test_build_dax_yoy():
    dax = time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "YoY")
    assert dax == (
        "VAR CurrentValue = [Total Vendas] "
        "VAR PriorValue = CALCULATE([Total Vendas], SAMEPERIODLASTYEAR('Datas'[Data])) "
        "RETURN DIVIDE(CurrentValue - PriorValue, PriorValue)"
    )


def test_build_dax_mom():
    dax = time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "MoM")
    assert dax == (
        "VAR CurrentValue = [Total Vendas] "
        "VAR PriorValue = CALCULATE([Total Vendas], DATEADD('Datas'[Data], -1, MONTH)) "
        "RETURN DIVIDE(CurrentValue - PriorValue, PriorValue)"
    )


def test_build_dax_raises_for_unknown_variant():
    with pytest.raises(UnknownTimeIntelligenceVariantError):
        time_intelligence.build_time_intelligence_dax("Total Vendas", "Datas", "Data", "Fantasma")


# --- create_time_intelligence_measures --------------------------------


@pytest.fixture
def fake() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas")
    runtime.add_table(
        TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),))
    )
    runtime.add_table(
        TableInfo(
            name="Datas",
            columns=(
                ColumnInfo(name="Data", data_type="DateTime"),
                ColumnInfo(name="Ano", data_type="Int64"),
            ),
        )
    )
    runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    runtime.calls.clear()
    connection.set_active_runtime(runtime)
    return runtime


def test_creates_one_measure_per_variant_and_saves_once(fake: FakeTomRuntime):
    result = time_intelligence.create_time_intelligence_measures(
        base_measure="Total Vendas", date_table="Datas", date_column="Data",
        variants=["YTD", "PY", "YoY"],
    )

    created_names = [c["measure_name"] for c in result["created"]]
    assert created_names == ["Total Vendas YTD", "Total Vendas PY", "Total Vendas YoY %"]
    assert fake.save_changes_count == 1
    create_calls = [c for c in fake.calls if c[0] == "create_measure"]
    assert len(create_calls) == 3


def test_new_measures_are_created_in_the_base_measures_table(fake: FakeTomRuntime):
    result = time_intelligence.create_time_intelligence_measures(
        base_measure="Total Vendas", date_table="Datas", date_column="Data", variants=["YTD"],
    )

    assert fake.written_calls()[0] == (
        "create_measure",
        {
            "table_name": "Vendas",
            "measure_name": "Total Vendas YTD",
            "dax_expression": "TOTALYTD([Total Vendas], 'Datas'[Data])",
            "format_string": "#,##0.00",
        },
    )
    assert result["created"][0]["measure_name"] == "Total Vendas YTD"


def test_percentage_variants_use_percentage_format_string(fake: FakeTomRuntime):
    time_intelligence.create_time_intelligence_measures(
        base_measure="Total Vendas", date_table="Datas", date_column="Data",
        variants=["YoY", "MoM"],
    )

    formats = {c[1]["measure_name"]: c[1]["format_string"] for c in fake.calls if c[0] == "create_measure"}
    assert formats["Total Vendas YoY %"] == "0.0%"
    assert formats["Total Vendas MoM %"] == "0.0%"


def test_save_false_does_not_save(fake: FakeTomRuntime):
    time_intelligence.create_time_intelligence_measures(
        base_measure="Total Vendas", date_table="Datas", date_column="Data",
        variants=["YTD"], save=False,
    )

    assert fake.save_changes_count == 0


def test_raises_when_base_measure_does_not_exist(fake: FakeTomRuntime):
    with pytest.raises(MeasureNotFoundError):
        time_intelligence.create_time_intelligence_measures(
            base_measure="Fantasma", date_table="Datas", date_column="Data", variants=["YTD"],
        )
    assert fake.written_calls() == []


def test_raises_when_date_table_does_not_exist(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        time_intelligence.create_time_intelligence_measures(
            base_measure="Total Vendas", date_table="Fantasma", date_column="Data",
            variants=["YTD"],
        )
    assert fake.written_calls() == []


def test_raises_when_date_column_does_not_exist(fake: FakeTomRuntime):
    with pytest.raises(ColumnNotFoundError):
        time_intelligence.create_time_intelligence_measures(
            base_measure="Total Vendas", date_table="Datas", date_column="Fantasma",
            variants=["YTD"],
        )
    assert fake.written_calls() == []


def test_raises_when_column_is_not_a_date_column(fake: FakeTomRuntime):
    with pytest.raises(NotADateColumnError):
        time_intelligence.create_time_intelligence_measures(
            base_measure="Total Vendas", date_table="Datas", date_column="Ano",
            variants=["YTD"],
        )
    assert fake.written_calls() == []


def test_raises_for_unknown_variant_before_creating_anything(fake: FakeTomRuntime):
    with pytest.raises(UnknownTimeIntelligenceVariantError):
        time_intelligence.create_time_intelligence_measures(
            base_measure="Total Vendas", date_table="Datas", date_column="Data",
            variants=["YTD", "Fantasma"],
        )
    assert fake.written_calls() == []


def test_raises_when_generated_measure_name_already_exists(fake: FakeTomRuntime):
    fake.create_measure("Vendas", "Total Vendas YTD", "SUM(Vendas[Valor])", None)
    fake.calls.clear()

    with pytest.raises(MeasureAlreadyExistsError):
        time_intelligence.create_time_intelligence_measures(
            base_measure="Total Vendas", date_table="Datas", date_column="Data",
            variants=["YTD"],
        )
