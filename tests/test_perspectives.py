"""Testes de modeling.perspectives: perspectivas (recorte do modelo com
só algumas tabelas/colunas/medidas/hierarquias).

Fontes: doc oficial "Let users personalize visuals" (Microsoft Learn) --
o TMDL de exemplo com `perspectiveTable` (+ `includeAll`),
`perspectiveColumn`, `perspectiveMeasure`, `perspectiveHierarchy`, e o
aviso de que perspectiva NÃO é segurança; reflexão .NET das DLLs do TOM
(Model.Perspectives -> Perspective -> PerspectiveTable(Table, IncludeAll)
-> PerspectiveColumn/Measure/Hierarchy). Sonda ao vivo (2026-09-29):
setar `Table`/`Column`/`Measure` já preenche o `Name` sozinho.
"""

from __future__ import annotations

import pytest

from errors import (
    InvalidPerspectiveError,
    ModelObjectNotFoundError,
    PerspectiveAlreadyExistsError,
    PerspectiveNotFoundError,
)
from modeling import connection, perspectives
from modeling.metadata import ColumnInfo, PerspectiveInfo, PerspectiveTableInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime


@pytest.fixture
def fake() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas")
    runtime.add_table(TableInfo(name="Vendas", columns=(
        ColumnInfo(name="Valor", data_type="Double"),
        ColumnInfo(name="Regiao", data_type="String"),
        ColumnInfo(name="Ano", data_type="Int64"),
        ColumnInfo(name="Mes", data_type="String"),
    )))
    runtime.add_table(TableInfo(name="Produto", columns=(ColumnInfo(name="Nome", data_type="String"),)))
    runtime.add_table(TableInfo(name="Parametro", columns=(ColumnInfo(name="Opcao", data_type="String"),)))
    runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    runtime.create_measure("Vendas", "Margem", "1", None)
    runtime.create_hierarchy("Vendas", "Calendario", ["Ano", "Mes"])
    connection.set_active_runtime(runtime)
    return runtime


def _created(fake: FakeTomRuntime) -> PerspectiveInfo:
    [call] = [c for c in fake.calls if c[0] == "create_perspective"]
    return call[1]["perspective"]


def test_whole_tables_and_individual_fields(fake):
    result = perspectives.create_perspective(
        name="Vendas",
        tables=["Produto"],
        fields=["Vendas.Regiao", "Vendas.Total Vendas", "Vendas.Calendario"],
        description="Só o que o time comercial usa",
    )

    perspective = _created(fake)
    assert perspective.name == "Vendas"
    assert perspective.description == "Só o que o time comercial usa"
    by_table = {t.table_name: t for t in perspective.tables}
    assert by_table["Produto"] == PerspectiveTableInfo(table_name="Produto", include_all=True)
    assert by_table["Vendas"] == PerspectiveTableInfo(
        table_name="Vendas", include_all=False,
        columns=("Regiao",), measures=("Total Vendas",), hierarchies=("Calendario",),
    )
    assert "Parametro" not in by_table
    assert result["name"] == "Vendas"
    assert fake.save_changes_count == 1


def test_field_of_a_whole_table_is_not_duplicated(fake):
    perspectives.create_perspective(name="P", tables=["Vendas"], fields=["Vendas.Total Vendas"])

    [table] = _created(fake).tables
    assert table == PerspectiveTableInfo(table_name="Vendas", include_all=True)


def test_list_and_delete(fake):
    perspectives.create_perspective(name="P", fields=["Vendas.Total Vendas"])

    listed = perspectives.list_perspectives()
    assert listed == [{
        "name": "P", "description": None,
        "tables": [{"table_name": "Vendas", "include_all": False, "columns": [], "measures": ["Total Vendas"], "hierarchies": []}],
    }]

    assert perspectives.delete_perspective("P") == {"name": "P", "deleted": True}
    assert perspectives.list_perspectives() == []


def test_duplicate_name_is_rejected(fake):
    perspectives.create_perspective(name="P", tables=["Produto"])
    with pytest.raises(PerspectiveAlreadyExistsError):
        perspectives.create_perspective(name="P", tables=["Vendas"])


def test_delete_unknown_is_rejected(fake):
    with pytest.raises(PerspectiveNotFoundError):
        perspectives.delete_perspective("NaoExiste")


@pytest.mark.parametrize("kwargs", [
    {"name": "P"},
    {"name": "P", "tables": [], "fields": []},
    {"name": "  ", "tables": ["Produto"]},
])
def test_empty_perspective_or_name_is_rejected(fake, kwargs):
    with pytest.raises(InvalidPerspectiveError):
        perspectives.create_perspective(**kwargs)
    assert not [c for c in fake.calls if c[0] == "create_perspective"]


@pytest.mark.parametrize("kwargs", [
    {"tables": ["NaoExiste"]},
    {"fields": ["Vendas.NaoExiste"]},
    {"fields": ["SemPonto"]},
])
def test_unknown_table_or_field_is_rejected_before_writing(fake, kwargs):
    with pytest.raises(ModelObjectNotFoundError):
        perspectives.create_perspective(name="P", **kwargs)
    assert not [c for c in fake.calls if c[0] == "create_perspective"]


def test_table_name_with_dot_resolves_by_longest_existing_table(fake):
    fake.add_table(TableInfo(name="Dim.Cliente", columns=(ColumnInfo(name="Nome", data_type="String"),)))

    perspectives.create_perspective(name="P", fields=["Dim.Cliente.Nome"])

    [table] = _created(fake).tables
    assert (table.table_name, table.columns) == ("Dim.Cliente", ("Nome",))


def test_internal_row_number_column_is_not_a_valid_field(fake):
    fake.add_table(TableInfo(name="T", columns=(
        ColumnInfo(name="RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61", data_type="Int64"),
    )))
    with pytest.raises(ModelObjectNotFoundError):
        perspectives.create_perspective(name="P", fields=["T.RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61"])


def test_create_perspective_is_listed_by_runtime(fake):
    perspectives.create_perspective(name="P", tables=["Produto"])
    assert fake.list_perspectives() == (
        PerspectiveInfo(name="P", description=None, tables=(PerspectiveTableInfo(table_name="Produto", include_all=True),)),
    )
