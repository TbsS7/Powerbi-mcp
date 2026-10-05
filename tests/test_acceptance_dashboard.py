"""Teste de aceitação: simula a geração de um dashboard simples (2
tabelas, 1 relacionamento, 1 medida criada, 3 visuais) sem Power BI
Desktop real, exercitando o fluxo completo em duas etapas
(plan_dashboard -> apply_dashboard_blueprint).

Nota de design: as duas tabelas (Vendas, Regiao) já existem no modelo
*antes* deste teste -- como estariam num projeto real após um usuário
tê-las carregado no Power BI Desktop (o que envolve o motor de Power
Query avaliar a expressão M de verdade, algo que nem este servidor nem
o FakeTomRuntime simulam). O blueprint deste teste cria o que falta
*depois* de as tabelas existirem: a medida, o relacionamento, e os 3
visuais -- exatamente o que orchestrator.applier documenta como a
fronteira do que dá para automatizar num único blueprint (ver
_reject_new_table_column_references em orchestrator/applier.py).

Confirma:
1. As operações TOM esperadas chegaram ao FakeTomRuntime, na ordem certa.
2. A árvore de arquivos criada bate exatamente com a estrutura PBIR.
3. Cada visual.json valida contra o schema oficial do PBIR.
4. Cada queryRef/nativeQueryRef de cada visual corresponde a um campo
   que realmente existe no metadata final do modelo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo, get_model_metadata
from orchestrator.applier import apply_dashboard_blueprint
from orchestrator.planner import plan_dashboard
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_page_json, validate_pages_metadata_json, validate_visual_json


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    return root


@pytest.fixture
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas", port=51999, compatibility_level=1601)
    fake.add_table(
        TableInfo(
            name="Vendas",
            columns=(
                ColumnInfo(name="RegiaoId", data_type="Int64"),
                ColumnInfo(name="Valor", data_type="Double"),
                ColumnInfo(name="Data", data_type="DateTime"),
            ),
        )
    )
    fake.add_table(
        TableInfo(
            name="Regiao",
            columns=(
                ColumnInfo(name="RegiaoId", data_type="Int64"),
                ColumnInfo(name="Nome", data_type="String"),
            ),
        )
    )
    connection.set_active_runtime(fake)
    return fake


def test_build_sales_by_region_dashboard_end_to_end(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    # --- Etapa 1: plan_dashboard ------------------------------------
    plan = plan_dashboard(
        description="crie um dashboard de vendas por região com base nesta tabela",
        pbip_path=str(project_dir),
    )
    table_names = {t["name"] for t in plan["model_metadata"]["tables"]}
    assert table_names == {"Vendas", "Regiao"}
    assert "clusteredColumnChart" in plan["visual_catalog"]

    # --- Monta o blueprint usando exatamente o que plan_dashboard confirmou ---
    blueprint = {
        "new_measures": [
            {
                "table_name": "Vendas",
                "measure_name": "Total Vendas",
                "dax_expression": "SUM(Vendas[Valor])",
                "format_string": "#,##0.00",
            }
        ],
        "new_relationships": [
            {
                "from_table": "Vendas",
                "from_column": "RegiaoId",
                "to_table": "Regiao",
                "to_column": "RegiaoId",
            }
        ],
        "pages": [
            {
                "page_name": "VendasPorRegiao",
                "display_name": "Vendas por Região",
                "visuals": [
                    {
                        "visual_type": "card",
                        "x": 0, "y": 0, "width": 200, "height": 100,
                        "fields": {"Values": ["Vendas.Total Vendas"]},
                    },
                    {
                        "visual_type": "clusteredColumnChart",
                        "x": 0, "y": 0, "width": 400, "height": 300,
                        "fields": {"Category": ["Regiao.Nome"], "Y": ["Vendas.Total Vendas"]},
                    },
                    {
                        "visual_type": "lineChart",
                        "x": 0, "y": 0, "width": 400, "height": 300,
                        "fields": {"Category": ["Vendas.Data"], "Y": ["Vendas.Total Vendas"]},
                    },
                ],
                "layout": "kpi_row",
            }
        ],
    }

    # --- Etapa 2: apply_dashboard_blueprint --------------------------
    result = apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    # 1. Operações TOM na ordem certa: medida -> relacionamento -> um
    # único save_changes no final (ver orchestrator.applier: as
    # operações de modelagem de um blueprint são salvas juntas, não uma
    # a uma, para que uma falha no meio não deixe nada persistido).
    call_names = [c[0] for c in fake_runtime.written_calls()]
    assert call_names == ["create_measure", "create_relationship", "save_changes"]
    assert fake_runtime.written_calls()[0][1]["measure_name"] == "Total Vendas"
    assert fake_runtime.written_calls()[1][1] == {
        "from_table": "Vendas",
        "from_column": "RegiaoId",
        "to_table": "Regiao",
        "to_column": "RegiaoId",
        "cardinality": "many_to_one",
        "cross_filter_direction": "single",
    }

    assert result["measures_created"] == ["Total Vendas"]
    assert result["relationships_created"] == [{"from": "Vendas.RegiaoId", "to": "Regiao.RegiaoId"}]
    assert result["pages"][0]["page_name"] == "VendasPorRegiao"
    assert len(result["pages"][0]["visuals"]) == 3

    # 2. Árvore de arquivos bate exatamente com a estrutura PBIR
    definition_dir = project_dir / "Vendas.Report" / "definition"
    assert (definition_dir / "version.json").is_file()
    assert (definition_dir / "report.json").is_file()
    page_dir = definition_dir / "pages" / "VendasPorRegiao"
    assert (definition_dir / "pages" / "pages.json").is_file()
    assert (page_dir / "page.json").is_file()
    visuals_dir = page_dir / "visuals"
    visual_dirs = sorted(d for d in visuals_dir.iterdir() if d.is_dir())
    assert len(visual_dirs) == 3
    for visual_dir in visual_dirs:
        assert (visual_dir / "visual.json").is_file()
        assert set(p.name for p in visual_dir.iterdir()) == {"visual.json"}

    pages_json = json.loads((definition_dir / "pages" / "pages.json").read_text(encoding="utf-8"))
    validate_pages_metadata_json(pages_json)
    assert pages_json["pageOrder"] == ["VendasPorRegiao"]
    assert pages_json["activePageName"] == "VendasPorRegiao"

    page_json = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
    validate_page_json(page_json)
    assert page_json["displayName"] == "Vendas por Região"

    # 3. Cada visual.json valida contra o schema oficial do PBIR
    visual_jsons = []
    for visual_dir in visual_dirs:
        data = json.loads((visual_dir / "visual.json").read_text(encoding="utf-8"))
        validate_visual_json(data)
        visual_jsons.append(data)

    visual_types = {v["visual"]["visualType"] for v in visual_jsons}
    assert visual_types == {"card", "clusteredColumnChart", "lineChart"}

    # kpi_row: o card fica no topo, os gráficos abaixo
    by_type = {v["visual"]["visualType"]: v for v in visual_jsons}
    card_bottom = by_type["card"]["position"]["y"] + by_type["card"]["position"]["height"]
    assert by_type["clusteredColumnChart"]["position"]["y"] >= card_bottom
    assert by_type["lineChart"]["position"]["y"] >= card_bottom

    # 4. Cada queryRef/nativeQueryRef corresponde a um objeto real no metadata final
    final_metadata = get_model_metadata(pbip_path=str(project_dir))
    known_measure_names = set(final_metadata.measure_names())
    known_columns = {
        (t.name, c.name) for t in final_metadata.tables for c in t.columns
    }

    for visual in visual_jsons:
        query_state = visual["visual"]["query"]["queryState"]
        for role in query_state.values():
            for projection in role["projections"]:
                query_ref = projection["queryRef"]
                native_query_ref = projection["nativeQueryRef"]
                table_name, _, property_name = query_ref.partition(".")
                assert native_query_ref == property_name
                field = projection["field"]
                if "Measure" in field:
                    assert property_name in known_measure_names
                    assert field["Measure"]["Property"] == property_name
                else:
                    assert (table_name, property_name) in known_columns
                    assert field["Column"]["Property"] == property_name
                    assert field["Column"]["Expression"]["SourceRef"]["Entity"] == table_name
