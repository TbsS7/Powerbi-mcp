"""Gráfico combinado colunas + linha (lineClusteredColumnComboChart).

Fonte: a doc oficial cartesian-part-02.md lista lineClusteredColumnComboChart
na família de visuais com `lineStyles`, e o schema oficial de tema tem
`visual-lineClusteredColumnComboChart`. Os roles `Y` (colunas) e `Y2`
(linha) são os do visual nativo -- melhor esforço, a doc não mostra um
exemplo de combo (confirmado ao vivo no dashboard da Cristallo).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualRoleError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_visual_json
from visuals import visual_writer


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    report_dir = root / "Vendas.Report"
    pages_dir = report_dir / "definition" / "pages"
    page_dir = pages_dir / "Pagina1"
    page_dir.mkdir(parents=True)
    (page_dir / "page.json").write_text("{}", encoding="utf-8")
    (pages_dir / "pages.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "version.json").write_text("{}", encoding="utf-8")
    (report_dir / "definition" / "report.json").write_text("{}", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Vendas", columns=(
        ColumnInfo(name="Valor", data_type="Double"),
        ColumnInfo(name="Segmento", data_type="String"),
    )))
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", "#,##0.00")
    fake.create_measure("Vendas", "Vendas PY", "0", "#,##0.00")
    connection.set_active_runtime(fake)
    return fake


def _visual(project_dir: Path, name: str) -> dict:
    path = project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_visual_json(data)
    return data


def test_combo_chart_columns_and_line(project_dir: Path):
    name = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type="lineClusteredColumnComboChart",
        x=0, y=0, width=400, height=300,
        fields={"Category": ["Vendas.Segmento"], "Y": ["Vendas.Total Vendas"], "Y2": ["Vendas.Vendas PY"]},
    )["visual_name"]

    query = _visual(project_dir, name)["visual"]["query"]["queryState"]
    assert [p["queryRef"] for p in query["Y"]["projections"]] == ["Vendas.Total Vendas"]
    assert [p["queryRef"] for p in query["Y2"]["projections"]] == ["Vendas.Vendas PY"]


def test_combo_chart_requires_columns(project_dir: Path):
    with pytest.raises(InvalidVisualRoleError, match="Y"):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="lineClusteredColumnComboChart",
            x=0, y=0, width=400, height=300,
            fields={"Category": ["Vendas.Segmento"], "Y2": ["Vendas.Vendas PY"]},
        )
