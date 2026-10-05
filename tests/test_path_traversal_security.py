"""Confirma, de ponta a ponta (não só a unidade visuals.names), que
page_name malicioso é recusado em todo caminho que o transforma em
componente de arquivo: create_report_page, add_visual,
set_page_layout, e o parse do blueprint em apply_dashboard_blueprint.

Sem esta validação, um page_name como "../../../outra_pasta/x" escapa
de definition/pages/ (path traversal) quando concatenado via
Path / page_name.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from errors import BlueprintValidationError, InvalidPageNameError
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from orchestrator.applier import apply_dashboard_blueprint
from orchestrator.blueprint import DashboardBlueprint
from tests.fakes.fake_tom import FakeTomRuntime
from visuals import filter_writer, layout, page_writer, visual_writer

MALICIOUS_PAGE_NAMES = [
    "../../../outra_pasta/x",
    "..\\..\\outra_pasta",
    "/etc/passwd",
    "pagina/../../fora",
]


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "Proj"
    root.mkdir()
    (root / "Proj.pbip").write_text("{}", encoding="utf-8")
    (root / "Proj.Report").mkdir()
    return root


@pytest.fixture
def fake_runtime() -> FakeTomRuntime:
    fake = FakeTomRuntime(database_name="Vendas")
    fake.add_table(TableInfo(name="Vendas", columns=(ColumnInfo(name="Valor", data_type="Double"),)))
    connection.set_active_runtime(fake)
    return fake


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_create_report_page_rejects_path_traversal(
    project_dir: Path, malicious_name: str, tmp_path: Path
):
    with pytest.raises(InvalidPageNameError):
        page_writer.create_report_page(pbip_path=str(project_dir), page_name=malicious_name)

    # nada foi escrito fora (nem dentro) da pasta do projeto
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_add_visual_rejects_path_traversal(
    project_dir: Path, fake_runtime: FakeTomRuntime, malicious_name: str, tmp_path: Path
):
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        visual_writer.add_visual(
            pbip_path=str(project_dir),
            page_name=malicious_name,
            visual_type="card",
            x=0, y=0, width=1, height=1,
            fields={"Values": ["Vendas.Valor"]},
        )
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_add_and_remove_page_filter_reject_path_traversal(
    project_dir: Path, fake_runtime: FakeTomRuntime, malicious_name: str, tmp_path: Path
):
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        filter_writer.add_page_filter(
            pbip_path=str(project_dir), page_name=malicious_name, query_ref="Vendas.Valor",
            filter_type="comparison", operator="gt", value=0,
        )
    with pytest.raises(InvalidPageNameError):
        filter_writer.remove_page_filter(
            pbip_path=str(project_dir), page_name=malicious_name, query_ref="Vendas.Valor"
        )
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_set_page_layout_rejects_path_traversal(
    project_dir: Path, malicious_name: str, tmp_path: Path
):
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        layout.set_page_layout(pbip_path=str(project_dir), page_name=malicious_name, layout="grid")
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_blueprint_page_spec_rejects_path_traversal_at_parse_time(malicious_name: str):
    with pytest.raises(PydanticValidationError):
        DashboardBlueprint.model_validate({"pages": [{"page_name": malicious_name}]})


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_apply_dashboard_blueprint_rejects_path_traversal_before_any_write(
    project_dir: Path, fake_runtime: FakeTomRuntime, malicious_name: str, tmp_path: Path
):
    blueprint = {
        "pages": [
            {
                "page_name": malicious_name,
                "visuals": [
                    {"visual_type": "card", "x": 0, "y": 0, "width": 1, "height": 1, "fields": {"Values": ["Vendas.Valor"]}}
                ],
            }
        ]
    }

    with pytest.raises(BlueprintValidationError):
        apply_dashboard_blueprint(blueprint=blueprint, pbip_path=str(project_dir))

    assert fake_runtime.calls == []
    assert not (project_dir / "Proj.Report" / "definition").exists()
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_set_page_background_rejects_path_traversal(
    project_dir: Path, malicious_name: str, tmp_path: Path
):
    from visuals import formatting

    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        formatting.set_page_background(pbip_path=str(project_dir), page_name=malicious_name, color="#FFFFFF")
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_set_mobile_layout_rejects_path_traversal(
    project_dir: Path, malicious_name: str, tmp_path: Path
):
    from visuals import mobile_layout

    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        mobile_layout.set_mobile_layout(pbip_path=str(project_dir), page_name=malicious_name)
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_set_page_perspective_rejects_path_traversal(
    project_dir: Path, malicious_name: str, tmp_path: Path
):
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        page_writer.set_page_perspective(pbip_path=str(project_dir), page_name=malicious_name, perspective=None)
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_set_page_background_image_rejects_path_traversal(
    project_dir: Path, malicious_name: str, tmp_path: Path
):
    from visuals import formatting

    image = tmp_path / "fundo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        formatting.set_page_background_image(
            pbip_path=str(project_dir), page_name=malicious_name, image_path=str(image)
        )
    assert not (tmp_path / "outra_pasta").exists()


@pytest.mark.parametrize("malicious_name", MALICIOUS_PAGE_NAMES)
def test_add_image_rejects_path_traversal(project_dir: Path, malicious_name: str, tmp_path: Path):
    from visuals import formatting

    image = tmp_path / "icone.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    page_writer.create_report_page(pbip_path=str(project_dir), page_name="PaginaLegitima")

    with pytest.raises(InvalidPageNameError):
        formatting.add_image(pbip_path=str(project_dir), page_name=malicious_name, image_path=str(image),
                             x=0, y=0, width=10, height=10)
    assert not (tmp_path / "outra_pasta").exists()
