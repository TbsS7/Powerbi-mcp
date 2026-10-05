"""Testes de add_image (visuals.formatting): visual "Imagem" a partir de um
arquivo (ícone, logo).

Fontes: doc oficial image.md (skills-for-fabric), "1. Local file path to
the image": visualType "image", `objects.general[].properties.imageUrl` =
ResourcePackageItem (PackageName "RegisteredResources", PackageType 1,
ItemName), arquivo em StaticResources/RegisteredResources/ registrado como
item "Image" (mesmo registro de set_page_background_image, que reaproveita
imagem igual). Schema oficial de tema (visual-image): `imageScaling.
imageScalingType` com os NOMES INTERNOS trocados em relação à tela --
"Normal" aparece como "Fit"(Ajustar), "Fit" como "Stretch"(Esticar),
"Fill" como "Fill"(Preencher).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError, PageNotFoundError
from tests.schema_validation import validate_report_json, validate_visual_json
from visuals import formatting, page_writer

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 32


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    return root


@pytest.fixture
def icon(tmp_path: Path) -> Path:
    path = tmp_path / "icone dinheiro.svg"
    path.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"/>')
    return path


def _visual(project_dir: Path, name: str) -> dict:
    data = json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / name / "visual.json")
        .read_text(encoding="utf-8")
    )
    validate_visual_json(data)
    return data


def test_add_image_like_the_doc(project_dir, icon):
    result = formatting.add_image(
        pbip_path=str(project_dir), page_name="Pagina1", image_path=str(icon), x=10, y=20, width=40, height=40,
    )

    visual = _visual(project_dir, result["visual_name"])
    assert visual["visual"]["visualType"] == "image"
    assert visual["position"]["x"] == 10 and visual["position"]["width"] == 40
    assert visual["visual"]["objects"]["general"] == [{"properties": {"imageUrl": {"expr": {"ResourcePackageItem": {
        "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": result["resource_name"],
    }}}}}]
    assert (project_dir / "Vendas.Report" / "StaticResources" / "RegisteredResources" / result["resource_name"]).is_file()
    report = json.loads((project_dir / "Vendas.Report" / "definition" / "report.json").read_text(encoding="utf-8"))
    validate_report_json(report)
    assert result["reused"] is False


@pytest.mark.parametrize(("fit", "internal"), [("fit", "Normal"), ("stretch", "Fit"), ("fill", "Fill")])
def test_fit_uses_the_internal_names(project_dir, icon, fit, internal):
    result = formatting.add_image(
        pbip_path=str(project_dir), page_name="Pagina1", image_path=str(icon), x=0, y=0, width=40, height=40, fit=fit,
    )
    scaling = _visual(project_dir, result["visual_name"])["visual"]["objects"]["imageScaling"]
    assert scaling == [{"properties": {"imageScalingType": {"expr": {"Literal": {"Value": f"'{internal}'"}}}}}]


def test_same_icon_twice_reuses_the_file(project_dir, icon):
    first = formatting.add_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(icon),
                                 x=0, y=0, width=40, height=40)
    second = formatting.add_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(icon),
                                  x=50, y=0, width=40, height=40)
    assert second["resource_name"] == first["resource_name"] and second["reused"] is True
    assert second["visual_name"] != first["visual_name"]
    assert len(list((project_dir / "Vendas.Report" / "StaticResources" / "RegisteredResources").iterdir())) == 1


def test_new_image_goes_on_top(project_dir, icon):
    first = formatting.add_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(icon),
                                 x=0, y=0, width=40, height=40)
    second = formatting.add_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(icon),
                                  x=0, y=0, width=40, height=40)
    assert _visual(project_dir, second["visual_name"])["position"]["z"] > _visual(project_dir, first["visual_name"])["position"]["z"]


@pytest.mark.parametrize("kwargs", [{"fit": "zoom"}])
def test_invalid_fit_is_rejected_before_copying(project_dir, icon, kwargs):
    with pytest.raises(InvalidVisualFormattingError):
        formatting.add_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(icon),
                             x=0, y=0, width=40, height=40, **kwargs)
    assert not (project_dir / "Vendas.Report" / "StaticResources").exists()


def test_bad_file_or_page(project_dir, icon, tmp_path):
    bad = tmp_path / "planilha.xlsx"
    bad.write_bytes(b"x")
    with pytest.raises(InvalidVisualFormattingError):
        formatting.add_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(bad),
                             x=0, y=0, width=40, height=40)
    with pytest.raises(PageNotFoundError):
        formatting.add_image(pbip_path=str(project_dir), page_name="NaoExiste", image_path=str(icon),
                             x=0, y=0, width=40, height=40)
    assert not (project_dir / "Vendas.Report" / "StaticResources").exists()
