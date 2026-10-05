"""Testes das dataclasses que formam o contrato ModelMetadata.

Nenhum tipo .NET deve vazar por aqui: são estruturas Python puras
compartilhadas por XmlaMetadataSource (via TomRuntime), TmdlMetadataSource
e pelo validador de campos da camada de visuais.
"""

from __future__ import annotations

from modeling.metadata import (
    ColumnInfo,
    MeasureInfo,
    ModelMetadata,
    RelationshipInfo,
    TableInfo,
)


def _sample_metadata() -> ModelMetadata:
    vendas = TableInfo(
        name="Vendas",
        columns=(
            ColumnInfo(name="RegiaoId", data_type="int64"),
            ColumnInfo(name="Valor", data_type="double"),
        ),
    )
    regiao = TableInfo(
        name="Regiao",
        columns=(
            ColumnInfo(name="RegiaoId", data_type="int64"),
            ColumnInfo(name="Nome", data_type="string"),
        ),
    )
    total_vendas = MeasureInfo(
        table_name="Vendas",
        name="Total Vendas",
        dax_expression="SUM(Vendas[Valor])",
        format_string="#,##0.00",
    )
    rel = RelationshipInfo(
        from_table="Vendas",
        from_column="RegiaoId",
        to_table="Regiao",
        to_column="RegiaoId",
        cardinality="many_to_one",
        cross_filter_direction="single",
    )
    return ModelMetadata(
        tables=(vendas, regiao),
        measures=(total_vendas,),
        relationships=(rel,),
    )


def test_table_names_lists_all_tables_in_order():
    metadata = _sample_metadata()
    assert metadata.table_names() == ["Vendas", "Regiao"]


def test_measure_names_lists_all_measures():
    metadata = _sample_metadata()
    assert metadata.measure_names() == ["Total Vendas"]


def test_find_table_returns_table_info_case_sensitive_match():
    metadata = _sample_metadata()
    table = metadata.find_table("Regiao")
    assert table is not None
    assert table.name == "Regiao"
    assert [c.name for c in table.columns] == ["RegiaoId", "Nome"]


def test_find_table_returns_none_when_missing():
    metadata = _sample_metadata()
    assert metadata.find_table("Clientes") is None


def test_find_measure_returns_measure_info():
    metadata = _sample_metadata()
    measure = metadata.find_measure("Total Vendas")
    assert measure is not None
    assert measure.table_name == "Vendas"
    assert measure.dax_expression == "SUM(Vendas[Valor])"


def test_find_measure_returns_none_when_missing():
    metadata = _sample_metadata()
    assert metadata.find_measure("Total Regiao") is None


def test_find_column_returns_column_info():
    metadata = _sample_metadata()
    column = metadata.find_column("Vendas", "Valor")
    assert column is not None
    assert column.data_type == "double"


def test_find_column_returns_none_when_table_missing():
    metadata = _sample_metadata()
    assert metadata.find_column("Clientes", "Nome") is None


def test_find_column_returns_none_when_column_missing():
    metadata = _sample_metadata()
    assert metadata.find_column("Vendas", "Desconto") is None


def test_to_dict_is_plain_json_serializable_structure():
    import json

    metadata = _sample_metadata()
    as_dict = metadata.to_dict()
    # não deve levantar - confirma que é serializável sem tipos exóticos
    serialized = json.dumps(as_dict)
    assert "Vendas" in serialized
    assert as_dict["tables"][0]["name"] == "Vendas"
    assert as_dict["measures"][0]["name"] == "Total Vendas"
    assert as_dict["relationships"][0]["from_table"] == "Vendas"
