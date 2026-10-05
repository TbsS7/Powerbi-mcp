"""Testes de modeling.metadata.list_model_metadata: a orquestração entre
a fonte XMLA (conexão TOM ativa) e a fonte TMDL (leitura offline).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modeling import connection
from modeling.metadata import MetadataSourceUnavailableError, list_model_metadata
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pbip"


def test_uses_active_xmla_connection_when_present():
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Clientes", columns=(ColumnInfo(name="Id", data_type="Int64"),)))
    connection.set_active_runtime(fake)

    result = list_model_metadata(pbip_path=str(FIXTURE_ROOT / "Vendas.pbip"))

    # veio do fake (Clientes), não do fixture em disco (Vendas/Regiao)
    assert [t["name"] for t in result["tables"]] == ["Clientes"]


def test_xmla_read_ressyncs_metadata_before_reading():
    """Achado ao vivo: o objeto Model do TOM é um snapshot do momento
    do connect() -- uma tabela criada por outra conexão (ex: pela UI do
    Desktop) depois disso não aparecia em list_model_metadata até
    reconectar. Confirmado com Model.Sync() ao vivo (ver
    TomRuntime.refresh_metadata); aqui só garantimos que
    list_model_metadata sempre passa por ele antes de ler."""
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Clientes", columns=()))
    connection.set_active_runtime(fake)

    list_model_metadata(pbip_path=str(FIXTURE_ROOT / "Vendas.pbip"))

    assert "refresh_metadata" in [c[0] for c in fake.calls]


def test_falls_back_to_tmdl_when_no_active_connection():
    result = list_model_metadata(pbip_path=str(FIXTURE_ROOT / "Vendas.pbip"))

    assert sorted(t["name"] for t in result["tables"]) == ["Regiao", "Vendas"]
    assert result["measures"][0]["name"] == "Total Vendas"


def test_raises_when_no_connection_and_no_pbip_path():
    with pytest.raises(MetadataSourceUnavailableError):
        list_model_metadata(pbip_path=None)
