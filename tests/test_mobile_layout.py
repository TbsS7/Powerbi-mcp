"""Testes de visuals.mobile_layout.set_mobile_layout: layout de celular.

Fontes: doc oficial Microsoft Learn "Power BI Desktop project report
folder" (visuals/<visual>/mobile.json = "visual mobile layout metadata,
such as mobile position and formatting"); schema oficial
visualContainerMobileState/2.3.0 (`$schema` + `position` obrigatórios,
`objects`/`visualContainerObjects` opcionais); e comparação com o que o
Desktop gravou pela UI (2026-09-29): tela do celular com 324px de
largura, visual solto ocupando x=0/largura 324, `z` crescente, sem
`tabOrder`, e o textbox com uma cópia de `objects.general` (o texto).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import MobileLayoutExistsError, VisualNotFoundError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_mobile_json
from visuals import mobile_layout, page_writer, visual_writer


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Regiao", data_type="String"),)))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _add(project_dir: Path, visual_type: str, x: float, y: float, **kwargs) -> str:
    fields = {
        "cardVisual": {"Data": ["Vendas.Total Vendas"]},
        "clusteredColumnChart": {"Category": ["Vendas.Regiao"], "Y": ["Vendas.Total Vendas"]},
        "slicer": {"Values": ["Vendas.Regiao"]},
    }.get(visual_type)
    return visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=visual_type,
        x=x, y=y, width=300, height=100, fields=fields, **kwargs,
    )["visual_name"]


def _mobile(project_dir: Path, name: str) -> dict | None:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "mobile.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_mobile_json(data)
    return data


def test_stacks_visuals_in_desktop_reading_order(project_dir: Path):
    chart = _add(project_dir, "clusteredColumnChart", x=0, y=300)
    title = _add(project_dir, "textbox", x=0, y=0, text="Painel")
    card_a = _add(project_dir, "cardVisual", x=0, y=100)
    card_b = _add(project_dir, "cardVisual", x=400, y=100)

    result = mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name="Pagina1")

    assert [p["visual_name"] for p in result["placed"]] == [title, card_a, card_b, chart]
    title_pos = _mobile(project_dir, title)["position"]
    a = _mobile(project_dir, card_a)["position"]
    b = _mobile(project_dir, card_b)["position"]
    c = _mobile(project_dir, chart)["position"]

    assert title_pos["x"] == 0 and title_pos["width"] == 324 and title_pos["y"] == 0
    # dois cartões lado a lado
    assert a["y"] == b["y"] > title_pos["y"] + title_pos["height"]
    assert a["x"] == 0 and b["x"] > a["x"] + a["width"]
    assert b["x"] + b["width"] <= 324
    # gráfico na largura toda, abaixo dos cartões
    assert c["x"] == 0 and c["width"] == 324
    assert c["y"] > a["y"] + a["height"]
    # z crescente, sem tabOrder (como o Desktop gravou)
    assert title_pos["z"] < a["z"] < b["z"] < c["z"]
    assert "tabOrder" not in c


def test_textbox_mobile_copies_text_like_desktop(project_dir: Path):
    title = _add(project_dir, "textbox", x=0, y=0, text="Painel")

    mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name="Pagina1")

    visual = json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / title / "visual.json")
        .read_text(encoding="utf-8")
    )
    assert _mobile(project_dir, title)["objects"]["general"] == visual["visual"]["objects"]["general"]


def test_only_listed_visuals_in_given_order(project_dir: Path):
    chart = _add(project_dir, "clusteredColumnChart", x=0, y=300)
    card = _add(project_dir, "cardVisual", x=0, y=100)
    slicer = _add(project_dir, "slicer", x=0, y=0)

    mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name="Pagina1", visuals=[chart, card])

    assert _mobile(project_dir, slicer) is None
    assert _mobile(project_dir, chart)["position"]["y"] < _mobile(project_dir, card)["position"]["y"]


def test_refuses_to_overwrite_existing_mobile_layout(project_dir: Path):
    chart = _add(project_dir, "clusteredColumnChart", x=0, y=0)
    mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name="Pagina1")
    before = _mobile(project_dir, chart)

    with pytest.raises(MobileLayoutExistsError):
        mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name="Pagina1")

    assert _mobile(project_dir, chart) == before


def test_replace_rewrites_and_removes_visuals_left_out(project_dir: Path):
    chart = _add(project_dir, "clusteredColumnChart", x=0, y=100)
    card = _add(project_dir, "cardVisual", x=0, y=0)
    mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name="Pagina1")

    result = mobile_layout.set_mobile_layout(
        pbip_path=str(project_dir), page_name="Pagina1", visuals=[chart], replace=True
    )

    assert _mobile(project_dir, card) is None
    assert _mobile(project_dir, chart)["position"]["y"] == 0
    assert result["removed"] == [card]


def test_unknown_visual_is_rejected_before_writing(project_dir: Path):
    chart = _add(project_dir, "clusteredColumnChart", x=0, y=0)

    with pytest.raises(VisualNotFoundError):
        mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name="Pagina1", visuals=[chart, "nao_existe"])

    assert _mobile(project_dir, chart) is None
