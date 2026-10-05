"""Testes de modeling.operations: create_table, create_measure,
create_relationship, e a validação que os antecede.

Todos operam sobre um FakeTomRuntime injetado via
connection.set_active_runtime -- nenhum toca .NET. O fixture autouse em
conftest.py garante que a conexão ativa é limpa entre testes.
"""

from __future__ import annotations

import pytest

from errors import (
    ColumnAlreadyExistsError,
    ColumnAlreadyHiddenError,
    ColumnNotFoundError,
    ColumnNotHiddenError,
    HierarchyAlreadyExistsError,
    HierarchyNotFoundError,
    MeasureNotFoundError,
    RelationshipNotFoundError,
    RoleAlreadyExistsError,
    RoleNotFoundError,
    TableHasRelationshipsError,
    TableNotFoundError,
    TablePermissionAlreadyExistsError,
    TablePermissionNotFoundError,
)
from modeling import connection, operations
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime


@pytest.fixture
def fake() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas")
    connection.set_active_runtime(runtime)
    return runtime


def test_create_table_calls_runtime_and_saves(fake: FakeTomRuntime):
    result = operations.create_table(
        table_name="Datas",
        dax_expression="CALENDAR(DATE(2024,1,1), DATE(2024,12,31))",
    )

    assert result["table_name"] == "Datas"
    assert fake.written_calls()[0][0] == "create_calculated_table"
    assert fake.written_calls()[0][1]["dax_expression"].startswith("CALENDAR")
    # bug 1.4 corrigido (para tabela calculada -- Power Query foi
    # removido do servidor, ver README): depois do save,
    # create_table sempre tenta um refresh_table pra descobrir colunas
    # reais (ver test_create_table_refreshes_and_rereads_columns_after_save)
    # -- save_changes deixou de ser a última chamada.
    assert fake.written_calls()[-1][0] == "refresh_table"
    assert fake.save_changes_count == 1
    assert result["refreshed"] is True
    assert result["refresh_error"] is None


def test_create_table_raises_when_name_already_exists(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(Exception, match="Vendas"):
        operations.create_table(table_name="Vendas", dax_expression="...")

    # nenhuma escrita deve ter ocorrido
    assert fake.written_calls() == []


# --- bug 1.4: refresh + releitura de colunas após create_table ---------


def test_create_table_refreshes_and_rereads_columns_after_save(fake: FakeTomRuntime):
    """Reproduz o bug 1.4: antes, create_table sempre devolvia
    columns=[] -- o TOM só descobre colunas de um construtor de tupla
    sem nome (ex: field parameters) ao processar a expressão, o que
    exige refresh_table depois do save (mesmo padrão de
    field_parameters.create_field_parameter). Aqui simulamos essa
    descoberta subclassando o fake."""

    class RefreshingFakeTomRuntime(FakeTomRuntime):
        def refresh_table(self, table_name: str) -> None:
            super().refresh_table(table_name)
            self._tables[table_name].columns = [ColumnInfo(name="Coluna1", data_type="String")]

    refreshing_fake = RefreshingFakeTomRuntime(database_name="Vendas")
    connection.set_active_runtime(refreshing_fake)

    result = operations.create_table(
        table_name="Datas", dax_expression="CALENDAR(DATE(2024,1,1), DATE(2024,12,31))",
    )

    assert result["refreshed"] is True
    assert result["refresh_error"] is None
    assert result["columns"] == [{"name": "Coluna1", "data_type": "String"}]


def test_create_table_with_refresh_false_skips_refresh_table(fake: FakeTomRuntime):
    result = operations.create_table(
        table_name="Datas", dax_expression="CALENDAR(DATE(2024,1,1), DATE(2024,12,31))",
        refresh=False,
    )

    assert result["refreshed"] is False
    assert result["refresh_error"] is None
    assert "refresh_table" not in [c[0] for c in fake.written_calls()]


def test_create_table_with_save_false_skips_refresh_even_when_refresh_true(fake: FakeTomRuntime):
    result = operations.create_table(
        table_name="Datas", dax_expression="CALENDAR(DATE(2024,1,1), DATE(2024,12,31))",
        save=False,
    )

    assert result["refreshed"] is False
    assert result["refresh_error"] is None
    assert fake.written_calls() == [
        (
            "create_calculated_table",
            {"table_name": "Datas", "dax_expression": "CALENDAR(DATE(2024,1,1), DATE(2024,12,31))"},
        ),
    ]


def test_create_table_captures_refresh_error_without_reverting_table(fake: FakeTomRuntime):
    class RaisingFakeTomRuntime(FakeTomRuntime):
        def refresh_table(self, table_name: str) -> None:
            super().refresh_table(table_name)
            raise RuntimeError("erro ao processar: token inesperado")

    raising_fake = RaisingFakeTomRuntime(database_name="Vendas")
    connection.set_active_runtime(raising_fake)

    result = operations.create_table(
        table_name="Datas", dax_expression="CALENDAR(DATE(2024,1,1), DATE(2024,12,31))",
    )

    assert result["refreshed"] is False
    assert result["refresh_error"] == "erro ao processar: token inesperado"
    # a tabela continua existindo -- decisão de design: falha de refresh
    # não reverte a criação (ver docstring de operations.create_table).
    assert "Datas" in raising_fake._tables


def test_create_measure_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(
        TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="double"),))
    )

    result = operations.create_measure(
        table_name="Vendas",
        measure_name="Total Vendas",
        dax_expression="SUM(Vendas[Valor])",
        format_string="#,##0.00",
    )

    assert result["measure_name"] == "Total Vendas"
    assert fake.written_calls()[0] == (
        "create_measure",
        {
            "table_name": "Vendas",
            "measure_name": "Total Vendas",
            "dax_expression": "SUM(Vendas[Valor])",
            "format_string": "#,##0.00",
        },
    )
    assert fake.calls[-1][0] == "save_changes"


def test_create_measure_raises_when_table_missing(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        operations.create_measure(
            table_name="Clientes",
            measure_name="Total",
            dax_expression="SUM(Clientes[Valor])",
        )
    assert fake.written_calls() == []


def test_create_measure_raises_when_name_already_exists(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    fake.calls.clear()

    with pytest.raises(Exception, match="Total Vendas"):
        operations.create_measure(
            table_name="Vendas",
            measure_name="Total Vendas",
            dax_expression="SUM(Vendas[Valor]) * 2",
        )
    assert fake.written_calls() == []


def test_create_relationship_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(
        TableInfo(name="Vendas", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),))
    )
    fake.add_table(
        TableInfo(
            name="Regiao",
            columns=(
                ColumnInfo(name="RegiaoId", data_type="int64"),
                ColumnInfo(name="Nome", data_type="string"),
            ),
        )
    )

    result = operations.create_relationship(
        from_table="Vendas",
        from_column="RegiaoId",
        to_table="Regiao",
        to_column="RegiaoId",
    )

    assert result["from_table"] == "Vendas"
    assert result["to_table"] == "Regiao"
    assert fake.written_calls()[0][0] == "create_relationship"
    assert fake.calls[-1][0] == "save_changes"


def test_create_relationship_raises_when_from_table_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Regiao", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))

    with pytest.raises(TableNotFoundError):
        operations.create_relationship(
            from_table="Vendas",
            from_column="RegiaoId",
            to_table="Regiao",
            to_column="RegiaoId",
        )
    assert fake.written_calls() == []


def test_create_relationship_raises_when_to_table_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))

    with pytest.raises(TableNotFoundError):
        operations.create_relationship(
            from_table="Vendas",
            from_column="RegiaoId",
            to_table="Regiao",
            to_column="RegiaoId",
        )
    assert fake.written_calls() == []


def test_create_relationship_raises_when_from_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.add_table(TableInfo(name="Regiao", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))

    with pytest.raises(ColumnNotFoundError):
        operations.create_relationship(
            from_table="Vendas",
            from_column="RegiaoId",
            to_table="Regiao",
            to_column="RegiaoId",
        )
    assert fake.written_calls() == []


def test_create_relationship_raises_when_to_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))
    fake.add_table(TableInfo(name="Regiao", columns=()))

    with pytest.raises(ColumnNotFoundError):
        operations.create_relationship(
            from_table="Vendas",
            from_column="RegiaoId",
            to_table="Regiao",
            to_column="RegiaoId",
        )
    assert fake.written_calls() == []


def test_create_measure_raises_clear_error_when_nothing_connected():
    # sem fixture "fake": nenhuma conexão ativa
    with pytest.raises(Exception, match="conex"):
        operations.create_measure(
            table_name="Vendas", measure_name="Total", dax_expression="SUM(Vendas[Valor])"
        )


# --- delete_measure / update_measure ----------------------------------


def test_delete_measure_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    fake.calls.clear()

    result = operations.delete_measure(table_name="Vendas", measure_name="Total Vendas")

    assert result == {"table_name": "Vendas", "measure_name": "Total Vendas", "deleted": True}
    assert fake.written_calls()[0] == (
        "delete_measure", {"table_name": "Vendas", "measure_name": "Total Vendas"}
    )
    assert fake.calls[-1][0] == "save_changes"
    assert fake.list_measures() == ()


def test_delete_measure_raises_when_measure_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(MeasureNotFoundError):
        operations.delete_measure(table_name="Vendas", measure_name="Nada")
    assert fake.written_calls() == []


def test_update_measure_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    fake.calls.clear()

    result = operations.update_measure(
        table_name="Vendas", measure_name="Total Vendas", dax_expression="SUM(Vendas[Valor]) * 2",
    )

    assert result["dax_expression"] == "SUM(Vendas[Valor]) * 2"
    assert result["format_string"] == "#,##0.00"  # não passado -- mantém o que já tinha
    assert fake.written_calls()[0][0] == "update_measure"
    assert fake.calls[-1][0] == "save_changes"


def test_update_measure_raises_when_measure_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(MeasureNotFoundError):
        operations.update_measure(table_name="Vendas", measure_name="Nada", dax_expression="1")
    assert fake.written_calls() == []


# --- delete_relationship ------------------------------------------------


def test_delete_relationship_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))
    fake.add_table(TableInfo(name="Regiao", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))
    fake.create_relationship("Vendas", "RegiaoId", "Regiao", "RegiaoId", "many_to_one", "single")
    fake.calls.clear()

    result = operations.delete_relationship(
        from_table="Vendas", from_column="RegiaoId", to_table="Regiao", to_column="RegiaoId",
    )

    assert result["deleted"] is True
    assert fake.written_calls()[0][0] == "delete_relationship"
    assert fake.calls[-1][0] == "save_changes"
    assert fake.list_relationships() == ()


def test_delete_relationship_raises_when_not_found(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))
    fake.add_table(TableInfo(name="Regiao", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))

    with pytest.raises(RelationshipNotFoundError):
        operations.delete_relationship(
            from_table="Vendas", from_column="RegiaoId", to_table="Regiao", to_column="RegiaoId",
        )
    assert fake.written_calls() == []


# --- delete_table --------------------------------------------------------


def test_delete_table_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    result = operations.delete_table(table_name="Vendas")

    assert result == {"table_name": "Vendas", "deleted": True}
    assert fake.written_calls()[0] == ("delete_table", {"table_name": "Vendas"})
    assert fake.calls[-1][0] == "save_changes"
    assert fake.list_tables() == ()


def test_delete_table_raises_when_table_missing(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        operations.delete_table(table_name="Nada")
    assert fake.written_calls() == []


def test_delete_table_raises_when_relationship_still_references_it(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))
    fake.add_table(TableInfo(name="Regiao", columns=(ColumnInfo(name="RegiaoId", data_type="int64"),)))
    fake.create_relationship("Vendas", "RegiaoId", "Regiao", "RegiaoId", "many_to_one", "single")
    fake.calls.clear()

    with pytest.raises(TableHasRelationshipsError):
        operations.delete_table(table_name="Regiao")
    assert fake.written_calls() == []


# --- create_calculated_column / delete_column ---------------------------


def test_create_calculated_column_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),)))

    result = operations.create_calculated_column(
        table_name="Vendas", column_name="ValorComImposto", dax_expression="Vendas[Valor] * 1.1",
    )

    assert result == {
        "table_name": "Vendas", "column_name": "ValorComImposto", "data_type": "Double",
    }
    assert fake.written_calls()[0] == (
        "create_calculated_column",
        {
            "table_name": "Vendas",
            "column_name": "ValorComImposto",
            "dax_expression": "Vendas[Valor] * 1.1",
            "format_string": None,
        },
    )
    assert fake.calls[-1][0] == "save_changes"


def test_create_calculated_column_raises_when_table_missing(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        operations.create_calculated_column(
            table_name="Nada", column_name="X", dax_expression="1",
        )
    assert fake.written_calls() == []


def test_create_calculated_column_raises_when_column_already_exists(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),)))

    with pytest.raises(ColumnAlreadyExistsError):
        operations.create_calculated_column(
            table_name="Vendas", column_name="Valor", dax_expression="1",
        )
    assert fake.written_calls() == []


def test_delete_column_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),)))

    result = operations.delete_column(table_name="Vendas", column_name="Valor")

    assert result == {"table_name": "Vendas", "column_name": "Valor", "deleted": True}
    assert fake.written_calls()[0] == (
        "delete_column", {"table_name": "Vendas", "column_name": "Valor"}
    )
    assert fake.calls[-1][0] == "save_changes"


def test_delete_column_raises_when_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(ColumnNotFoundError):
        operations.delete_column(table_name="Vendas", column_name="Nada")
    assert fake.written_calls() == []


# --- create_hierarchy / delete_hierarchy / list_hierarchies -------------


def test_create_hierarchy_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(
        TableInfo(
            name="Datas",
            columns=(
                ColumnInfo(name="Ano", data_type="Int64"),
                ColumnInfo(name="Trimestre", data_type="String"),
                ColumnInfo(name="Mes", data_type="String"),
            ),
        )
    )

    result = operations.create_hierarchy(
        table_name="Datas", hierarchy_name="Calendario", levels=["Ano", "Trimestre", "Mes"],
    )

    assert result == {
        "table_name": "Datas", "hierarchy_name": "Calendario",
        "levels": ["Ano", "Trimestre", "Mes"],
    }
    assert fake.written_calls()[0] == (
        "create_hierarchy",
        {"table_name": "Datas", "hierarchy_name": "Calendario", "levels": ["Ano", "Trimestre", "Mes"]},
    )
    assert fake.calls[-1][0] == "save_changes"


def test_create_hierarchy_raises_when_table_missing(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        operations.create_hierarchy(table_name="Nada", hierarchy_name="H", levels=["X"])
    assert fake.written_calls() == []


def test_create_hierarchy_raises_when_level_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Datas", columns=(ColumnInfo(name="Ano", data_type="Int64"),)))

    with pytest.raises(ColumnNotFoundError):
        operations.create_hierarchy(table_name="Datas", hierarchy_name="H", levels=["Ano", "Nada"])
    assert fake.written_calls() == []


def test_create_hierarchy_raises_when_name_already_exists(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Datas", columns=(ColumnInfo(name="Ano", data_type="Int64"),)))
    fake.create_hierarchy("Datas", "Calendario", ["Ano"])
    fake.calls.clear()

    with pytest.raises(HierarchyAlreadyExistsError):
        operations.create_hierarchy(table_name="Datas", hierarchy_name="Calendario", levels=["Ano"])
    assert fake.written_calls() == []


def test_delete_hierarchy_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Datas", columns=(ColumnInfo(name="Ano", data_type="Int64"),)))
    fake.create_hierarchy("Datas", "Calendario", ["Ano"])
    fake.calls.clear()

    result = operations.delete_hierarchy(table_name="Datas", hierarchy_name="Calendario")

    assert result == {"table_name": "Datas", "hierarchy_name": "Calendario", "deleted": True}
    assert fake.written_calls()[0] == (
        "delete_hierarchy", {"table_name": "Datas", "hierarchy_name": "Calendario"}
    )
    assert fake.calls[-1][0] == "save_changes"


def test_delete_hierarchy_raises_when_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Datas", columns=()))

    with pytest.raises(HierarchyNotFoundError):
        operations.delete_hierarchy(table_name="Datas", hierarchy_name="Nada")
    assert fake.written_calls() == []


def test_list_hierarchies_returns_all(fake: FakeTomRuntime):
    fake.add_table(
        TableInfo(
            name="Datas",
            columns=(ColumnInfo(name="Ano", data_type="Int64"), ColumnInfo(name="Mes", data_type="String")),
        )
    )
    fake.create_hierarchy("Datas", "Calendario", ["Ano", "Mes"])

    result = operations.list_hierarchies()

    assert result == [
        {"table_name": "Datas", "hierarchy_name": "Calendario", "levels": ["Ano", "Mes"]}
    ]


# --- create_role / add_table_permission / delete_role / list_roles ------


def test_create_role_calls_runtime_and_saves(fake: FakeTomRuntime):
    result = operations.create_role(role_name="VendedorRegional")

    assert result == {"role_name": "VendedorRegional", "table_permissions": []}
    assert fake.written_calls()[0] == ("create_role", {"role_name": "VendedorRegional"})
    assert fake.calls[-1][0] == "save_changes"


def test_create_role_raises_when_name_already_exists(fake: FakeTomRuntime):
    fake.create_role("VendedorRegional")
    fake.calls.clear()

    with pytest.raises(RoleAlreadyExistsError):
        operations.create_role(role_name="VendedorRegional")
    assert fake.written_calls() == []


def test_add_table_permission_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.create_role("VendedorRegional")
    fake.calls.clear()

    result = operations.add_table_permission(
        role_name="VendedorRegional", table_name="Vendas",
        filter_expression="Vendas[Regiao] = \"Sul\"",
    )

    assert result == {
        "role_name": "VendedorRegional",
        "table_permissions": [
            {"table_name": "Vendas", "filter_expression": 'Vendas[Regiao] = "Sul"', "hidden_columns": []}
        ],
    }
    assert fake.written_calls()[0][0] == "add_table_permission"
    assert fake.calls[-1][0] == "save_changes"


def test_add_table_permission_raises_when_role_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(RoleNotFoundError):
        operations.add_table_permission(
            role_name="Nada", table_name="Vendas", filter_expression="TRUE()",
        )
    assert fake.written_calls() == []


def test_add_table_permission_raises_when_table_missing(fake: FakeTomRuntime):
    fake.create_role("VendedorRegional")
    fake.calls.clear()

    with pytest.raises(TableNotFoundError):
        operations.add_table_permission(
            role_name="VendedorRegional", table_name="Nada", filter_expression="TRUE()",
        )
    assert fake.written_calls() == []


def test_add_table_permission_raises_when_already_set_for_that_table(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.create_role("VendedorRegional")
    fake.add_table_permission("VendedorRegional", "Vendas", "TRUE()")
    fake.calls.clear()

    with pytest.raises(TablePermissionAlreadyExistsError):
        operations.add_table_permission(
            role_name="VendedorRegional", table_name="Vendas", filter_expression="FALSE()",
        )
    assert fake.written_calls() == []


def test_delete_role_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.create_role("VendedorRegional")
    fake.calls.clear()

    result = operations.delete_role(role_name="VendedorRegional")

    assert result == {"role_name": "VendedorRegional", "deleted": True}
    assert fake.written_calls()[0] == ("delete_role", {"role_name": "VendedorRegional"})
    assert fake.calls[-1][0] == "save_changes"


def test_delete_role_raises_when_missing(fake: FakeTomRuntime):
    with pytest.raises(RoleNotFoundError):
        operations.delete_role(role_name="Nada")
    assert fake.written_calls() == []


def test_list_roles_returns_all_with_their_table_permissions(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.create_role("VendedorRegional")
    fake.add_table_permission("VendedorRegional", "Vendas", "Vendas[Regiao] = \"Sul\"")

    result = operations.list_roles()

    assert result == [
        {
            "role_name": "VendedorRegional",
            "table_permissions": [
                {
                    "table_name": "Vendas", "filter_expression": 'Vendas[Regiao] = "Sul"',
                    "hidden_columns": [],
                }
            ],
        }
    ]


# --- refresh_table / refresh_model --------------------------------------


def test_refresh_table_calls_runtime(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    result = operations.refresh_table(table_name="Vendas")

    assert result == {"table_name": "Vendas", "refreshed": True}
    assert fake.written_calls() == [("refresh_table", {"table_name": "Vendas"})]


def test_refresh_table_raises_when_table_missing(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        operations.refresh_table(table_name="Nada")
    assert fake.written_calls() == []


def test_refresh_model_calls_runtime_and_lists_table_names(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.add_table(TableInfo(name="Regiao", columns=()))

    result = operations.refresh_model()

    assert set(result["table_names"]) == {"Vendas", "Regiao"}
    assert result["refreshed"] is True
    assert fake.written_calls() == [("refresh_model", {})]


# --- hide_column / unhide_column (OLS) -----------------------------------


@pytest.fixture
def fake_with_table_permission(fake: FakeTomRuntime) -> FakeTomRuntime:
    fake.add_table(
        TableInfo(
            name="Vendas",
            columns=(ColumnInfo(name="Valor", data_type="Double"), ColumnInfo(name="Custo", data_type="Double")),
        )
    )
    fake.create_role("Vendedor")
    fake.add_table_permission("Vendedor", "Vendas", "TRUE()")
    fake.calls.clear()
    return fake


def test_hide_column_calls_runtime_and_saves(fake_with_table_permission: FakeTomRuntime):
    fake = fake_with_table_permission

    result = operations.hide_column(role_name="Vendedor", table_name="Vendas", column_name="Custo")

    assert result == {
        "role_name": "Vendedor",
        "table_permissions": [
            {"table_name": "Vendas", "filter_expression": "TRUE()", "hidden_columns": ["Custo"]}
        ],
    }
    assert fake.written_calls()[0] == (
        "hide_column", {"role_name": "Vendedor", "table_name": "Vendas", "column_name": "Custo"}
    )
    assert fake.calls[-1][0] == "save_changes"


def test_hide_column_raises_when_role_missing(fake_with_table_permission: FakeTomRuntime):
    with pytest.raises(RoleNotFoundError):
        operations.hide_column(role_name="Nada", table_name="Vendas", column_name="Custo")
    assert fake_with_table_permission.written_calls() == []


def test_hide_column_raises_when_table_permission_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Custo", data_type="Double"),)))
    fake.create_role("Vendedor")
    fake.calls.clear()

    with pytest.raises(TablePermissionNotFoundError):
        operations.hide_column(role_name="Vendedor", table_name="Vendas", column_name="Custo")
    assert fake.written_calls() == []


def test_hide_column_raises_when_column_missing(fake_with_table_permission: FakeTomRuntime):
    with pytest.raises(ColumnNotFoundError):
        operations.hide_column(role_name="Vendedor", table_name="Vendas", column_name="Nada")
    assert fake_with_table_permission.written_calls() == []


def test_hide_column_raises_when_already_hidden(fake_with_table_permission: FakeTomRuntime):
    fake = fake_with_table_permission
    fake.hide_column("Vendedor", "Vendas", "Custo")
    fake.calls.clear()

    with pytest.raises(ColumnAlreadyHiddenError):
        operations.hide_column(role_name="Vendedor", table_name="Vendas", column_name="Custo")
    assert fake.written_calls() == []


def test_unhide_column_calls_runtime_and_saves(fake_with_table_permission: FakeTomRuntime):
    fake = fake_with_table_permission
    fake.hide_column("Vendedor", "Vendas", "Custo")
    fake.calls.clear()

    result = operations.unhide_column(role_name="Vendedor", table_name="Vendas", column_name="Custo")

    assert result == {
        "role_name": "Vendedor",
        "table_permissions": [
            {"table_name": "Vendas", "filter_expression": "TRUE()", "hidden_columns": []}
        ],
    }
    assert fake.written_calls()[0] == (
        "unhide_column", {"role_name": "Vendedor", "table_name": "Vendas", "column_name": "Custo"}
    )
    assert fake.calls[-1][0] == "save_changes"


def test_unhide_column_raises_when_not_hidden(fake_with_table_permission: FakeTomRuntime):
    with pytest.raises(ColumnNotHiddenError):
        operations.unhide_column(role_name="Vendedor", table_name="Vendas", column_name="Custo")
    assert fake_with_table_permission.written_calls() == []


# --- set_table_description / set_column_metadata / set_measure_metadata --


def test_set_table_description_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    result = operations.set_table_description(table_name="Vendas", description="Fato de vendas")

    assert result == {"table_name": "Vendas", "description": "Fato de vendas"}
    assert fake.written_calls()[0] == (
        "set_table_description", {"table_name": "Vendas", "description": "Fato de vendas"}
    )
    assert fake.calls[-1][0] == "save_changes"


def test_set_table_description_raises_when_table_missing(fake: FakeTomRuntime):
    with pytest.raises(TableNotFoundError):
        operations.set_table_description(table_name="Nada", description="X")
    assert fake.written_calls() == []


def test_set_column_metadata_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),)))

    result = operations.set_column_metadata(
        table_name="Vendas", column_name="Valor", description="Valor bruto", display_folder="Financeiro",
    )

    assert result == {
        "table_name": "Vendas", "column_name": "Valor",
        "description": "Valor bruto", "display_folder": "Financeiro",
    }
    assert fake.written_calls()[0] == (
        "set_column_metadata",
        {
            "table_name": "Vendas", "column_name": "Valor",
            "description": "Valor bruto", "display_folder": "Financeiro",
        },
    )
    assert fake.calls[-1][0] == "save_changes"


def test_set_column_metadata_raises_when_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(ColumnNotFoundError):
        operations.set_column_metadata(table_name="Vendas", column_name="Nada", description="X")
    assert fake.written_calls() == []


def test_set_measure_metadata_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    fake.calls.clear()

    result = operations.set_measure_metadata(
        table_name="Vendas", measure_name="Total Vendas",
        description="Soma bruta", display_folder="Totais",
    )

    assert result == {
        "table_name": "Vendas", "measure_name": "Total Vendas",
        "description": "Soma bruta", "display_folder": "Totais",
    }
    assert fake.written_calls()[0][0] == "set_measure_metadata"
    assert fake.calls[-1][0] == "save_changes"


def test_set_measure_metadata_raises_when_measure_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(MeasureNotFoundError):
        operations.set_measure_metadata(table_name="Vendas", measure_name="Nada", description="X")
    assert fake.written_calls() == []


# --- set_column_sort_by ---------------------------------------------------


def test_set_column_sort_by_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(
        TableInfo(
            name="Datas",
            columns=(
                ColumnInfo(name="NomeMes", data_type="String"),
                ColumnInfo(name="NumeroMes", data_type="Int64"),
            ),
        )
    )

    result = operations.set_column_sort_by(
        table_name="Datas", column_name="NomeMes", sort_by_column="NumeroMes"
    )

    assert result == {"table_name": "Datas", "column_name": "NomeMes", "sort_by_column": "NumeroMes"}
    assert fake.written_calls()[0] == (
        "set_column_sort_by",
        {"table_name": "Datas", "column_name": "NomeMes", "sort_by_column": "NumeroMes"},
    )
    assert fake.calls[-1][0] == "save_changes"


def test_set_column_sort_by_none_clears_it(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Datas", columns=(ColumnInfo(name="NomeMes", data_type="String"),)))

    operations.set_column_sort_by(table_name="Datas", column_name="NomeMes", sort_by_column=None)

    assert fake.written_calls()[0] == (
        "set_column_sort_by",
        {"table_name": "Datas", "column_name": "NomeMes", "sort_by_column": None},
    )


def test_set_column_sort_by_raises_when_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Datas", columns=()))

    with pytest.raises(ColumnNotFoundError):
        operations.set_column_sort_by(table_name="Datas", column_name="Nada", sort_by_column=None)
    assert fake.written_calls() == []


def test_set_column_sort_by_raises_when_sort_by_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Datas", columns=(ColumnInfo(name="NomeMes", data_type="String"),)))

    with pytest.raises(ColumnNotFoundError):
        operations.set_column_sort_by(
            table_name="Datas", column_name="NomeMes", sort_by_column="Fantasma"
        )
    assert fake.written_calls() == []


# --- set_column_format -----------------------------------------------------


def test_set_column_format_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Site", data_type="String"),)))

    result = operations.set_column_format(
        table_name="Vendas", column_name="Site", data_category="WebUrl",
    )

    assert result == {
        "table_name": "Vendas", "column_name": "Site",
        "format_string": None, "data_category": "WebUrl",
    }
    assert fake.written_calls()[0] == (
        "set_column_format",
        {
            "table_name": "Vendas", "column_name": "Site",
            "format_string": None, "data_category": "WebUrl",
        },
    )
    assert fake.calls[-1][0] == "save_changes"


def test_set_column_format_raises_when_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(ColumnNotFoundError):
        operations.set_column_format(table_name="Vendas", column_name="Nada", format_string="0.0%")
    assert fake.written_calls() == []


# --- set_column_visibility --------------------------------------------------


def test_set_column_visibility_calls_runtime_and_saves(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Helper", data_type="String"),)))

    result = operations.set_column_visibility(
        table_name="Vendas", column_name="Helper", is_hidden=True
    )

    assert result == {"table_name": "Vendas", "column_name": "Helper", "is_hidden": True}
    assert fake.written_calls()[0] == (
        "set_column_visibility",
        {"table_name": "Vendas", "column_name": "Helper", "is_hidden": True},
    )
    assert fake.calls[-1][0] == "save_changes"


def test_set_column_visibility_raises_when_column_missing(fake: FakeTomRuntime):
    fake.add_table(TableInfo(name="Vendas", columns=()))

    with pytest.raises(ColumnNotFoundError):
        operations.set_column_visibility(table_name="Vendas", column_name="Nada", is_hidden=True)
    assert fake.written_calls() == []


