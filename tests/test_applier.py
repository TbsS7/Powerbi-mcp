"""Testes de orchestrator.applier: apply_dashboard_blueprint.

Cobre: execução real (tabelas -> medidas -> relacionamentos -> páginas/
visuais), dry_run (nada é escrito), validação completa ANTES de
qualquer escrita (inclusive de páginas/visuais que nada têm a ver com o
campo inválido), a proibição de referenciar coluna de tabela nova no
mesmo blueprint, e a atomicidade da escrita de páginas/visuais (staging
+ swap: uma falha não deixa a pasta definition/ real pela metade).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import BlueprintValidationError, UnknownFieldError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from orchestrator.applier import apply_dashboard_blueprint
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_visual_json


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    return root


@pytest.fixture
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(
        TableInfo(
            name="Vendas",
            columns=(ColumnInfo(name="Valor", data_type="Double"), ColumnInfo(name="RegiaoId", data_type="Int64")),
        )
    )
    connection.set_active_runtime(fake)
    return fake


def _visuals_of(project_dir: Path, page_name: str) -> list[Path]:
    visuals_dir = project_dir / "Vendas.Report" / "definition" / "pages" / page_name / "visuals"
    return sorted(visuals_dir.iterdir()) if visuals_dir.is_dir() else []


def test_empty_blueprint_is_a_noop(project_dir: Path, fake_runtime: FakeTomRuntime):
    result = apply_dashboard_blueprint(blueprint={}, pbip_path=str(project_dir))

    assert result["tables_created"] == []
    assert result["measures_created"] == []
    assert result["relationships_created"] == []
    assert result["pages"] == []
    assert fake_runtime.written_calls() == []
    assert "note" not in result  # nada foi escrito, não há aviso de reabrir o Desktop


def test_note_about_reopening_desktop_appears_only_when_pages_were_written(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)

    model_only_result = apply_dashboard_blueprint(
        blueprint={
            "new_measures": [
                {"table_name": "Vendas", "measure_name": "Outra Medida", "dax_expression": "COUNTROWS(Vendas)"}
            ]
        },
        pbip_path=str(project_dir),
    )
    assert "note" not in model_only_result

    pages_result = apply_dashboard_blueprint(
        blueprint={
            "pages": [
                {
                    "page_name": "Pagina1",
                    "visuals": [
                        {"visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.Total Vendas"]}}
                    ],
                }
            ]
        },
        pbip_path=str(project_dir),
    )
    assert "note" in pages_result


def test_note_is_stronger_when_model_and_pages_change_in_the_same_call(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    """Achado testando ao vivo, em duas rodadas:
    1. Criar medida + visual que a usa na MESMA chamada, e fechar/
       reabrir o Desktop sem salvar primeiro, recarrega o modelo sem a
       medida nova -- os visuais (já escritos em disco) passam a
       referenciar algo inexistente e o Power BI Desktop mostra
       'Missing_References'.
    2. A "correção óbvia" (salvar ANTES de fechar/reabrir) é na
       verdade PERIGOSA: confirmado ao vivo que o Power BI Desktop não
       faz merge ao salvar -- Ctrl+S reescreve toda a pasta de páginas
       com o que está na memória do Desktop, apagando qualquer página
       que ele ainda não conheça (como a que acabamos de escrever
       nesta mesma chamada). Não existe uma única ação seque resolve
       as duas coisas -- a nota precisa explicar o caminho de
       recuperação real (fechar/reabrir sem salvar, recriar o modelo,
       só então salvar), não sugerir "salve agora"."""
    result = apply_dashboard_blueprint(
        blueprint={
            "new_measures": [
                {"table_name": "Vendas", "measure_name": "Total Vendas", "dax_expression": "SUM(Vendas[Valor])"}
            ],
            "pages": [
                {
                    "page_name": "Pagina1",
                    "visuals": [
                        {"visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.Total Vendas"]}}
                    ],
                }
            ],
        },
        pbip_path=str(project_dir),
    )

    assert "note" in result
    note = result["note"]
    # não deve mais sugerir "salvar agora" como solução -- isso apagaria
    # a página recém-escrita, que o Desktop ainda não conhece
    assert "faz merge" in note.lower()
    assert "list_model_metadata" in note
    assert "Ctrl+S" in note


def test_creates_measure_on_existing_table(project_dir: Path, fake_runtime: FakeTomRuntime):
    blueprint = {
        "new_measures": [
            {"table_name": "Vendas", "measure_name": "Total Vendas", "dax_expression": "SUM(Vendas[Valor])"}
        ]
    }

    result = apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    assert result["measures_created"] == ["Total Vendas"]
    assert any(call[0] == "create_measure" for call in fake_runtime.calls)
    assert any(call[0] == "save_changes" for call in fake_runtime.calls)


def test_creates_page_with_visual_using_existing_field(project_dir: Path, fake_runtime: FakeTomRuntime):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    blueprint = {
        "pages": [
            {
                "page_name": "Pagina1",
                "visuals": [
                    {
                        "visual_type": "card", "x": 0, "y": 0, "width": 200, "height": 100,
                        "fields": {"Values": ["Vendas.Total Vendas"]},
                    }
                ],
            }
        ]
    }

    result = apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    assert result["pages"][0]["page_name"] == "Pagina1"
    assert len(result["pages"][0]["visuals"]) == 1
    visuals = _visuals_of(project_dir, "Pagina1")
    assert len(visuals) == 1
    data = json.loads((visuals[0] / "visual.json").read_text(encoding="utf-8"))
    validate_visual_json(data)


def test_dry_run_writes_nothing_and_executes_nothing(project_dir: Path, fake_runtime: FakeTomRuntime):
    blueprint = {
        "new_measures": [
            {"table_name": "Vendas", "measure_name": "Total Vendas", "dax_expression": "SUM(Vendas[Valor])"}
        ],
        "pages": [
            {
                "page_name": "Pagina1",
                "visuals": [
                    {
                        "visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1,
                        "fields": {"Values": ["Vendas.Total Vendas"]},
                    }
                ],
            }
        ],
    }

    result = apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir), dry_run=True)

    assert result["dry_run"] is True
    assert fake_runtime.written_calls() == []  # nenhuma operação de modelagem executada
    assert not (project_dir / "Vendas.Report" / "definition").exists()  # nada escrito


def test_modeling_operations_share_a_single_save_changes(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    fake_runtime.add_table(TableInfo(name="Regiao", columns=(ColumnInfo(name="RegiaoId", data_type="Int64"),)))
    blueprint = {
        "new_measures": [
            {"table_name": "Vendas", "measure_name": "Total Vendas", "dax_expression": "SUM(Vendas[Valor])"}
        ],
        "new_relationships": [
            {"from_table": "Vendas", "from_column": "RegiaoId", "to_table": "Regiao", "to_column": "RegiaoId"}
        ],
    }

    apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    call_names = [c[0] for c in fake_runtime.written_calls()]
    assert call_names == ["create_measure", "create_relationship", "save_changes"]


def test_full_flow_creates_table_measure_relationship_and_page(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    fake_runtime.add_table(TableInfo(name="Regiao", columns=(ColumnInfo(name="RegiaoId", data_type="Int64"),)))
    blueprint = {
        "new_measures": [
            {"table_name": "Vendas", "measure_name": "Total Vendas", "dax_expression": "SUM(Vendas[Valor])"}
        ],
        "new_relationships": [
            {"from_table": "Vendas", "from_column": "RegiaoId", "to_table": "Regiao", "to_column": "RegiaoId"}
        ],
        "pages": [
            {
                "page_name": "Pagina1",
                "visuals": [
                    {
                        "visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1,
                        "fields": {"Values": ["Vendas.Total Vendas"]},
                    }
                ],
                "layout": "grid",
            }
        ],
    }

    result = apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    assert result["measures_created"] == ["Total Vendas"]
    assert result["relationships_created"] == [{"from": "Vendas.RegiaoId", "to": "Regiao.RegiaoId"}]
    call_order = [c[0] for c in fake_runtime.written_calls()]
    assert call_order.index("create_measure") < call_order.index("create_relationship")


def test_rejects_visual_field_referencing_column_of_new_table(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    blueprint = {
        "new_tables": [{"table_name": "Regiao", "dax_expression": "..."}],
        "pages": [
            {
                "page_name": "Pagina1",
                "visuals": [
                    {
                        "visual_type": "slicer", "x": 0, "y": 0, "width": 1, "height": 1,
                        "fields": {"Values": ["Regiao.Nome"]},
                    }
                ],
            }
        ],
    }

    with pytest.raises(BlueprintValidationError, match="Regiao"):
        apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    assert fake_runtime.written_calls() == []
    assert not (project_dir / "Vendas.Report" / "definition").exists()


def test_invalid_field_in_one_visual_blocks_the_whole_blueprint(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    blueprint = {
        "new_measures": [
            {"table_name": "Vendas", "measure_name": "Total Vendas", "dax_expression": "SUM(Vendas[Valor])"}
        ],
        "pages": [
            {
                "page_name": "Pagina1",
                "visuals": [
                    {
                        "visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1,
                        "fields": {"Values": ["Vendas.CampoQueNaoExiste"]},
                    }
                ],
            }
        ],
    }

    with pytest.raises(UnknownFieldError):
        apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    # nem a medida (não relacionada ao erro) foi criada
    assert fake_runtime.written_calls() == []


def test_reuses_existing_page_instead_of_failing(project_dir: Path, fake_runtime: FakeTomRuntime):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    blueprint_1 = {
        "pages": [
            {
                "page_name": "Pagina1",
                "visuals": [
                    {"visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.Total Vendas"]}}
                ],
            }
        ]
    }
    apply_dashboard_blueprint(blueprint=blueprint_1, pbip_path=str(project_dir))

    blueprint_2 = {
        "pages": [
            {
                "page_name": "Pagina1",
                "visuals": [
                    {"visual_type": "card", "x": 100, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.Total Vendas"]}}
                ],
            }
        ]
    }
    apply_dashboard_blueprint(blueprint=blueprint_2, pbip_path=str(project_dir))

    assert len(_visuals_of(project_dir, "Pagina1")) == 2


def test_pages_written_when_project_shares_a_folder_with_unrelated_files(
    tmp_path: Path, fake_runtime: FakeTomRuntime, monkeypatch
):
    """Achado testando ao vivo: um usuário salvou o .pbip direto na
    pasta do seu perfil do Windows (C:\\Users\\<nome>\\), ao lado de
    Documentos/Desktop/etc. A cópia atômica para staging travava por
    minutos tentando copiar a pasta inteira. Este teste simula essa
    pasta "cheia" (aqui, um arquivo grande fictício ao lado do projeto)
    e confirma que shutil.copytree nunca recebe essa pasta-pai como
    origem -- só .Report e .SemanticModel do próprio projeto."""
    shared_folder = tmp_path  # simula "C:\\Users\\<nome>\\"
    (shared_folder / "Proj.pbip").write_text("{}", encoding="utf-8")
    (shared_folder / "Proj.Report").mkdir()
    (shared_folder / "arquivo_nao_relacionado.txt").write_text("x" * 1000, encoding="utf-8")
    (shared_folder / "Documentos_Fake").mkdir()
    (shared_folder / "Documentos_Fake" / "algo.docx").write_text("nada a ver", encoding="utf-8")

    import shutil

    copytree_sources = []
    real_copytree = shutil.copytree

    def _tracking_copytree(src, dst, *args, **kwargs):
        copytree_sources.append(Path(src))
        return real_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", _tracking_copytree)

    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    result = apply_dashboard_blueprint(
        blueprint={
            "pages": [
                {
                    "page_name": "Pagina1",
                    "visuals": [
                        {"visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.Total Vendas"]}}
                    ],
                }
            ]
        },
        pbip_path=str(shared_folder / "Proj.pbip"),
    )

    assert len(result["pages"][0]["visuals"]) == 1
    # nenhuma chamada a copytree teve a pasta compartilhada (com os
    # arquivos não relacionados) como origem, nem nada fora de .Report/
    # .SemanticModel do projeto -- só subpastas deles (inclusive
    # sub-chamadas recursivas internas do próprio shutil.copytree)
    assert shared_folder not in copytree_sources
    allowed_roots = (shared_folder / "Proj.Report", shared_folder / "Proj.SemanticModel")
    for src in copytree_sources:
        assert any(
            src == root or root.name in src.parts for root in allowed_roots
        ), f"copytree teve origem inesperada: {src}"


def test_existing_definition_content_survives_a_failed_apply(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    apply_dashboard_blueprint(
        blueprint={
            "pages": [
                {
                    "page_name": "Pagina1",
                    "visuals": [
                        {"visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.Total Vendas"]}}
                    ],
                }
            ]
        },
        pbip_path=str(project_dir),
    )
    before = (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "page.json").read_text(
        encoding="utf-8"
    )

    with pytest.raises(UnknownFieldError):
        apply_dashboard_blueprint(
            blueprint={
                "pages": [
                    {
                        "page_name": "Pagina2",
                        "visuals": [
                            {"visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.NaoExiste"]}}
                        ],
                    }
                ]
            },
            pbip_path=str(project_dir),
        )

    after = (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "page.json").read_text(
        encoding="utf-8"
    )
    assert before == after
    assert not (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina2").exists()


# --- título e fundo da página (acabamento automático) ------------------------


def _read_visual_jsons(project_dir: Path, page_name: str) -> list[dict]:
    return [
        json.loads((d / "visual.json").read_text(encoding="utf-8")) for d in _visuals_of(project_dir, page_name)
    ]


def _card(y: float = 0) -> dict:
    return {
        "visual_type": "card", "x": 0, "y": y, "width": 200, "height": 100,
        "fields": {"Values": ["Vendas.Total Vendas"]},
    }


def test_page_title_creates_styled_textbox_banner_and_layout_starts_below_it(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)

    result = apply_dashboard_blueprint(
        blueprint={"pages": [{
            "page_name": "Pagina1",
            "title": {"text": "Dashboard de Vendas"},
            "visuals": [_card(), _card()],
            "layout": "kpi_row",
        }]},
        pbip_path=str(project_dir),
    )

    visuals = _read_visual_jsons(project_dir, "Pagina1")
    textboxes = [v for v in visuals if v["visual"]["visualType"] == "textbox"]
    cards = [v for v in visuals if v["visual"]["visualType"] == "card"]
    assert len(textboxes) == 1 and len(cards) == 2

    title = textboxes[0]
    assert result["pages"][0]["title_visual"] == title["name"]
    assert title["position"]["x"] == 0 and title["position"]["y"] == 0
    assert title["position"]["width"] == 1280 and title["position"]["height"] == 56

    paragraph = title["visual"]["objects"]["general"][0]["properties"]["paragraphs"][0]
    assert paragraph["horizontalTextAlignment"] == "center"
    run = paragraph["textRuns"][0]
    assert run["value"] == "Dashboard de Vendas"
    assert run["textStyle"]["fontSize"] == "20pt"
    assert run["textStyle"]["fontWeight"] == "bold"
    assert run["textStyle"]["color"] == "#FFFFFF"

    background = title["visual"]["visualContainerObjects"]["background"][0]["properties"]
    assert background["color"] == {"solid": {"color": {"expr": {"Literal": {"Value": "'#1F3864'"}}}}}
    assert background["show"] == {"expr": {"Literal": {"Value": "true"}}}

    for card in cards:
        assert card["position"]["y"] >= 56 + 8
    for visual in visuals:
        validate_visual_json(visual)


def test_page_title_without_layout_shifts_visuals_below_the_banner(
    project_dir: Path, fake_runtime: FakeTomRuntime
):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)

    apply_dashboard_blueprint(
        blueprint={"pages": [{
            "page_name": "Pagina1",
            "title": {"text": "Vendas", "height": 60},
            "visuals": [_card(y=10)],
        }]},
        pbip_path=str(project_dir),
    )

    cards = [v for v in _read_visual_jsons(project_dir, "Pagina1") if v["visual"]["visualType"] == "card"]
    assert cards[0]["position"]["y"] == 70


def test_page_background_color_is_written_to_page_json(project_dir: Path, fake_runtime: FakeTomRuntime):
    from tests.schema_validation import validate_page_json

    apply_dashboard_blueprint(
        blueprint={"pages": [{"page_name": "Pagina1", "background_color": "#F3F2F1"}]},
        pbip_path=str(project_dir),
    )

    page = json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "page.json").read_text(encoding="utf-8")
    )
    props = page["objects"]["background"][0]["properties"]
    assert props["color"] == {"solid": {"color": {"expr": {"Literal": {"Value": "'#F3F2F1'"}}}}}
    assert props["transparency"] == {"expr": {"Literal": {"Value": "0D"}}}
    validate_page_json(page)


def test_page_without_title_is_unchanged(project_dir: Path, fake_runtime: FakeTomRuntime):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)

    result = apply_dashboard_blueprint(
        blueprint={"pages": [{"page_name": "Pagina1", "visuals": [_card(y=10)]}]},
        pbip_path=str(project_dir),
    )

    visuals = _read_visual_jsons(project_dir, "Pagina1")
    assert [v["visual"]["visualType"] for v in visuals] == ["card"]
    assert visuals[0]["position"]["y"] == 10
    assert "title_visual" not in result["pages"][0]
    page = json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "page.json").read_text(encoding="utf-8")
    )
    assert "objects" not in page


def test_invalid_title_is_rejected_before_any_write(project_dir: Path, fake_runtime: FakeTomRuntime):
    with pytest.raises(BlueprintValidationError):
        apply_dashboard_blueprint(
            blueprint={"pages": [{"page_name": "Pagina1", "title": {"text": "T", "color": "branco"}}]},
            pbip_path=str(project_dir),
        )
    assert not (project_dir / "Vendas.Report" / "definition").exists()


def test_visual_alt_text_from_blueprint(project_dir: Path, fake_runtime: FakeTomRuntime):
    fake_runtime.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    card = {**_card(), "alt_text": "Total de vendas do período"}

    apply_dashboard_blueprint(
        blueprint={"pages": [{"page_name": "Pagina1", "visuals": [card, _card()]}]},
        pbip_path=str(project_dir),
    )

    visuals = _read_visual_jsons(project_dir, "Pagina1")
    alt_texts = [
        v["visual"].get("visualContainerObjects", {}).get("general", [{}])[0].get("properties", {}).get("altText")
        for v in visuals
    ]
    assert {"expr": {"Literal": {"Value": "'Total de vendas do período'"}}} in alt_texts
    assert None in alt_texts
    for visual in visuals:
        validate_visual_json(visual)
