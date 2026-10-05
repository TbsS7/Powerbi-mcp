"""Testes de set_page_background_image (visuals.formatting): imagem de
fundo da página (tela) ou do papel de parede.

Fontes: doc oficial page-formatting.md (skills-for-fabric), seção
"Background Images" -- `background`/`outspace` com
`image.image.{name, url, scaling}` ANINHADO ("A flat image.name/url/
scaling will silently fail to render"), `url` = `ResourcePackageItem`
(PackageName "RegisteredResources", PackageType 1, ItemName), scaling
'Fit'/'Stretch'/'Fill'; e image.md -- arquivo copiado pra
StaticResources/RegisteredResources/ com sufixo numérico único antes da
extensão (como o Desktop faz), registrado em report.json
resourcePackages como item `type: "Image"` (name = path = arquivo), o
nome original vira `image.image.name`, e "if the image already exists,
do not add a duplicate copy".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from errors import InvalidVisualFormattingError, PageNotFoundError
from tests.schema_validation import validate_page_json, validate_report_json
from visuals import formatting, page_writer

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1")
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina2")
    return root


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "Fundo Vendas.png"
    path.write_bytes(_PNG)
    return path


def _page(project_dir: Path, page: str = "Pagina1") -> dict:
    return json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / page / "page.json").read_text(encoding="utf-8")
    )


def _report(project_dir: Path) -> dict:
    return json.loads((project_dir / "Vendas.Report" / "definition" / "report.json").read_text(encoding="utf-8"))


def _resources(project_dir: Path) -> Path:
    return project_dir / "Vendas.Report" / "StaticResources" / "RegisteredResources"


def _lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def test_copies_registers_and_sets_nested_image_like_the_doc(project_dir, image):
    result = formatting.set_page_background_image(
        pbip_path=str(project_dir), page_name="Pagina1", image_path=str(image)
    )

    item_name = result["resource_name"]
    assert re.fullmatch(r"Fundo_Vendas\d{10,}\.png", item_name)
    assert (_resources(project_dir) / item_name).read_bytes() == _PNG

    report = _report(project_dir)
    [package] = [p for p in report["resourcePackages"] if p["type"] == "RegisteredResources"]
    assert {"name": item_name, "path": item_name, "type": "Image"} in package["items"]
    validate_report_json(report)

    props = _page(project_dir)["objects"]["background"][0]["properties"]
    assert props["image"] == {"image": {
        "name": _lit("'Fundo Vendas.png'"),
        "url": {"expr": {"ResourcePackageItem": {
            "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": item_name,
        }}},
        "scaling": _lit("'Fit'"),
    }}
    assert props["transparency"] == _lit("0D")
    validate_page_json(_page(project_dir))


def test_same_image_on_another_page_reuses_the_file(project_dir, image):
    first = formatting.set_page_background_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(image))
    second = formatting.set_page_background_image(pbip_path=str(project_dir), page_name="Pagina2", image_path=str(image))

    assert second["resource_name"] == first["resource_name"]
    assert second["reused"] is True
    assert len(list(_resources(project_dir).iterdir())) == 1
    [package] = [p for p in _report(project_dir)["resourcePackages"] if p["type"] == "RegisteredResources"]
    assert len([i for i in package["items"] if i["type"] == "Image"]) == 1


def test_wallpaper_scaling_and_existing_color_are_kept(project_dir, image):
    formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", wallpaper_color="#0D1117")

    formatting.set_page_background_image(
        pbip_path=str(project_dir), page_name="Pagina1", image_path=str(image), wallpaper=True, scaling="Fill",
    )

    page = _page(project_dir)
    props = page["objects"]["outspace"][0]["properties"]
    assert props["image"]["image"]["scaling"] == _lit("'Fill'")
    assert props["color"] == {"solid": {"color": _lit("'#0D1117'")}}
    assert "background" not in page["objects"]
    validate_page_json(page)


def test_none_removes_the_image_but_keeps_the_color(project_dir, image):
    formatting.set_page_background(pbip_path=str(project_dir), page_name="Pagina1", color="#FFFFFF")
    formatting.set_page_background_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(image))

    formatting.set_page_background_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=None)

    props = _page(project_dir)["objects"]["background"][0]["properties"]
    assert "image" not in props
    assert props["color"] == {"solid": {"color": _lit("'#FFFFFF'")}}


@pytest.mark.parametrize("kwargs", [
    {"scaling": "Tile"},
    {"transparency": 120},
])
def test_invalid_options_are_rejected_without_writing(project_dir, image, kwargs):
    before = _page(project_dir)
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_page_background_image(
            pbip_path=str(project_dir), page_name="Pagina1", image_path=str(image), **kwargs
        )
    assert _page(project_dir) == before
    assert not _resources(project_dir).exists()


@pytest.mark.parametrize("name", ["planilha.xlsx", "sem_extensao", "nao_existe.png"])
def test_bad_image_files_are_rejected(project_dir, tmp_path, name):
    path = tmp_path / name
    if name != "nao_existe.png":
        path.write_bytes(b"x")
    with pytest.raises(InvalidVisualFormattingError):
        formatting.set_page_background_image(pbip_path=str(project_dir), page_name="Pagina1", image_path=str(path))
    assert not _resources(project_dir).exists()


def test_unknown_page_is_rejected_before_copying(project_dir, image):
    with pytest.raises(PageNotFoundError):
        formatting.set_page_background_image(pbip_path=str(project_dir), page_name="NaoExiste", image_path=str(image))
    assert not _resources(project_dir).exists()
