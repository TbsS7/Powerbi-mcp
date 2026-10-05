"""Testes de modeling.audit.audit_model: auditoria read-only do modelo
(só aponta problemas, nunca corrige -- decisão do usuário). Um modelo
fake com cada problema plantado, e casos "OK" ao lado de cada um pra
provar que a regra não gera falso positivo."""

from __future__ import annotations

import pytest

from errors import DesktopNotFoundError, UnknownAuditRuleError
from modeling import audit, connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime


@pytest.fixture
def fake() -> FakeTomRuntime:
    runtime = FakeTomRuntime(database_name="Vendas")
    runtime.add_table(
        TableInfo(
            name="Vendas",
            columns=(
                ColumnInfo(name="Valor", data_type="Double"),
                ColumnInfo(name="Custo", data_type="Double"),
                ColumnInfo(name="ClienteId", data_type="Int64"),
                ColumnInfo(name="ProdutoKey", data_type="Int64"),
                ColumnInfo(name="Data", data_type="DateTime"),
                ColumnInfo(name="Auxiliar", data_type="String"),
                ColumnInfo(name="MesNome", data_type="String"),
                ColumnInfo(name="OrdemMes", data_type="Int64"),
            ),
        )
    )
    runtime.add_table(
        TableInfo(
            name="Clientes",
            columns=(ColumnInfo(name="ClienteId", data_type="Int64"), ColumnInfo(name="Nome", data_type="String")),
        )
    )
    runtime.add_table(TableInfo(name="LocalDateTable_abc", columns=(ColumnInfo(name="Date", data_type="DateTime"),)))
    runtime.add_table(
        TableInfo(
            name="Metrica",
            columns=(
                ColumnInfo(name="Value1", data_type="String"),
                ColumnInfo(name="Value2", data_type="String"),
            ),
        )
    )
    runtime.add_table(TableInfo(name="Sheet1", columns=(ColumnInfo(name="Data", data_type="DateTime"),)))

    runtime.create_relationship("Vendas", "ClienteId", "Clientes", "ClienteId", "many_to_one", "single")
    runtime.create_relationship("Vendas", "Data", "LocalDateTable_abc", "Date", "many_to_one", "single")
    runtime.create_relationship("Sheet1", "Data", "LocalDateTable_abc", "Date", "many_to_one", "single")

    runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    runtime.create_measure("Vendas", "Qtd", "COUNTROWS(Vendas)", None)
    runtime.create_measure("Vendas", "Total Custo", "SUM(Vendas[Custo])", "#,##0.00")
    runtime.set_measure_metadata("Vendas", "Total Vendas", "Soma do valor vendido", None)

    runtime.set_table_description("Clientes", "Cadastro de clientes")
    runtime.set_column_visibility("Vendas", "Auxiliar", True)  # oculta, sem uso -> achado
    runtime.set_column_visibility("Vendas", "Custo", True)  # oculta, mas usada em medida -> OK
    runtime.set_column_visibility("Vendas", "OrdemMes", True)  # oculta, mas é sort-by -> OK
    runtime.set_column_sort_by("Vendas", "MesNome", "OrdemMes")
    runtime.set_column_visibility("Metrica", "Value2", True)  # field parameter -> OK
    runtime.set_column_extended_property("Metrica", "Value2", "ParameterMetadata", '{"version": 3, "kind": 2}')

    runtime.calls.clear()
    connection.set_active_runtime(runtime)
    return runtime


def _refs(result: dict, code: str) -> set[str]:
    return {i["object_ref"] for i in result["issues"] if i["code"] == code}


def test_medida_sem_format_string(fake: FakeTomRuntime):
    result = audit.audit_model()
    assert _refs(result, "MEDIDA_SEM_FORMAT_STRING") == {"Vendas[Qtd]"}


def test_medida_sem_descricao(fake: FakeTomRuntime):
    result = audit.audit_model()
    assert _refs(result, "MEDIDA_SEM_DESCRICAO") == {"Vendas[Qtd]", "Vendas[Total Custo]"}


def test_tabela_sem_descricao_ignora_tabela_de_sistema(fake: FakeTomRuntime):
    result = audit.audit_model()
    assert _refs(result, "TABELA_SEM_DESCRICAO") == {"Vendas", "Metrica", "Sheet1"}


def test_tabela_desconectada_nao_conta_relacionamento_com_tabela_de_sistema(fake: FakeTomRuntime):
    # Sheet1 só se relaciona com a tabela de data automática -- não
    # conta como conectada a nenhuma outra tabela do modelo.
    result = audit.audit_model()
    assert _refs(result, "TABELA_DESCONECTADA") == {"Metrica", "Sheet1"}


def test_coluna_chave_orfa(fake: FakeTomRuntime):
    result = audit.audit_model()
    assert _refs(result, "COLUNA_CHAVE_ORFA") == {"Vendas[ProdutoKey]"}


def test_coluna_oculta_sem_uso_ignora_sort_by_medida_e_field_parameter(fake: FakeTomRuntime):
    result = audit.audit_model()
    assert _refs(result, "COLUNA_OCULTA_SEM_USO") == {"Vendas[Auxiliar]"}


def test_nenhum_achado_referencia_tabela_de_sistema(fake: FakeTomRuntime):
    result = audit.audit_model()
    assert not any("LocalDateTable_" in i["object_ref"] for i in result["issues"])


def test_row_number_column_is_ignored(fake: FakeTomRuntime):
    fake.add_table(
        TableInfo(
            name="Clientes",
            columns=(
                ColumnInfo(name="RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61", data_type="Int64"),
                ColumnInfo(name="ClienteId", data_type="Int64"),
            ),
        )
    )
    fake.set_column_visibility("Clientes", "RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61", True)
    result = audit.audit_model()
    assert not any("RowNumber-" in i["object_ref"] for i in result["issues"])


def test_summary_counts_by_severity(fake: FakeTomRuntime):
    result = audit.audit_model()
    avisos = sum(1 for i in result["issues"] if i["severity"] == "aviso")
    sugestoes = sum(1 for i in result["issues"] if i["severity"] == "sugestao")
    assert result["summary"] == {"aviso": avisos, "sugestao": sugestoes}
    assert result["total"] == len(result["issues"])
    # avisos vêm antes de sugestões
    severities = [i["severity"] for i in result["issues"]]
    assert severities == sorted(severities, key=lambda s: 0 if s == "aviso" else 1)


def test_rules_filter_runs_only_requested(fake: FakeTomRuntime):
    result = audit.audit_model(rules=["MEDIDA_SEM_FORMAT_STRING"])
    assert result["rules_run"] == ["MEDIDA_SEM_FORMAT_STRING"]
    assert {i["code"] for i in result["issues"]} == {"MEDIDA_SEM_FORMAT_STRING"}


def test_unknown_rule_raises(fake: FakeTomRuntime):
    with pytest.raises(UnknownAuditRuleError):
        audit.audit_model(rules=["FANTASMA"])


def test_is_read_only(fake: FakeTomRuntime):
    audit.audit_model()
    assert fake.written_calls() == []
    assert fake.save_changes_count == 0


def test_clean_model_has_no_issues():
    runtime = FakeTomRuntime(database_name="Limpo")
    runtime.add_table(TableInfo(name="A", columns=(ColumnInfo(name="Id", data_type="Int64"),)))
    runtime.add_table(TableInfo(name="B", columns=(ColumnInfo(name="Id", data_type="Int64"),)))
    runtime.create_relationship("B", "Id", "A", "Id", "many_to_one", "single")
    runtime.set_table_description("A", "a")
    runtime.set_table_description("B", "b")
    runtime.create_measure("A", "Contagem", "COUNTROWS(A)", "0")
    runtime.set_measure_metadata("A", "Contagem", "Linhas de A", None)
    connection.set_active_runtime(runtime)

    result = audit.audit_model()

    assert result["issues"] == []
    assert result["summary"] == {"aviso": 0, "sugestao": 0}


def test_requires_active_connection():
    with pytest.raises(DesktopNotFoundError):
        audit.audit_model()
