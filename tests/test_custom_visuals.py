"""Testes de visuals.custom_visuals: importar um visual personalizado
(.pbiviz) no relatório e usá-lo em add_visual / blueprint.

Fonte: doc oficial custom-visuals.md (microsoft/skills-for-fabric) --
visual PRIVADO = pacote descompactado em `CustomVisuals/<GUID>/`
(package.json + resources/<GUID>.pbiviz.json) E registrado em
report.json `resourcePackages` (type "CustomVisual", item
`<GUID>.pbiviz.json` do tipo "CustomVisualMetadata"; só a pasta não
basta); `visualType` = GUID; roles vêm de `capabilities.dataRoles`
(Grouping -> coluna, Measure -> medida) e os limites de
`dataViewMappings.conditions`; GUID sempre do package.json, nunca
adivinhado. Schema oficial report/3.3.0 confirma `CustomVisual` e
`CustomVisualMetadata`.

ACHADO AO VIVO (2026-09-30), que muda a receita da doc: só pasta +
resourcePackages (a receita "privado" da doc) NÃO renderizou o Tornado
(visual do AppSource) -- "adicione-o a este relatório primeiro". O que o
Desktop grava (no .pbix de exemplo do AppSource e ao adicionar pela UI)
tem TAMBÉM o GUID em `publicCustomVisuals`; com isso renderizou. E ao
salvar, o Desktop APAGA a pasta CustomVisuals/ -- por isso os roles
ficam guardados numa anotação do report.json (annotations: "Power BI
Desktop ignores these annotations", doc do Microsoft Learn).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from errors import (
    CustomVisualAlreadyExistsError,
    CustomVisualInUseError,
    CustomVisualNotFoundError,
    InvalidCustomVisualError,
    InvalidVisualRoleError,
    UnknownVisualTypeError,
)
from modeling import connection
from modeling.metadata import ColumnInfo, TableInfo
from tests.fakes.fake_tom import FakeTomRuntime
from tests.schema_validation import validate_report_json, validate_visual_json
from visuals import custom_visuals, page_writer, visual_writer

GUID = "TornadoChart1452517688218"


def _capabilities() -> dict:
    return {
        "dataRoles": [
            {"name": "Category", "kind": "Grouping", "displayName": "Group"},
            {"name": "Values", "kind": "Measure", "displayName": "Values"},
            {"name": "Tooltips", "kind": "GroupingOrMeasure", "displayName": "Tooltips"},
        ],
        "dataViewMappings": [{"conditions": [{"Category": {"max": 1}, "Values": {"min": 1, "max": 2}}]}],
    }


def _make_pbiviz(tmp_path: Path, guid: str = GUID, extra: dict[str, str] | None = None,
                 capabilities: dict | None = None, include_resource: bool = True) -> Path:
    path = tmp_path / f"{guid}.pbiviz"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("package.json", json.dumps({
            "visual": {"name": "tornado", "displayName": "Tornado chart", "guid": guid, "version": "3.0.1"},
            "resources": [{"resourceId": "rId0", "sourceType": 5, "file": f"resources/{guid}.pbiviz.json"}],
        }))
        if include_resource:
            zf.writestr(f"resources/{guid}.pbiviz.json", json.dumps({
                "visual": {"guid": guid}, "capabilities": capabilities or _capabilities(), "content": {"js": "x"},
            }))
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return path


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
    fake.create_measure("Vendas", "Total Vendas", "SUM(Vendas[Valor])", None)
    fake.create_measure("Vendas", "Lucro", "1", None)
    connection.set_active_runtime(fake)
    return fake


def _report(project_dir: Path) -> dict:
    return json.loads((project_dir / "Vendas.Report" / "definition" / "report.json").read_text(encoding="utf-8"))


def test_import_registers_like_the_desktop(project_dir, tmp_path):
    result = custom_visuals.import_custom_visual(
        pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path))
    )

    visual_dir = project_dir / "Vendas.Report" / "CustomVisuals" / GUID
    assert (visual_dir / "package.json").is_file()
    assert (visual_dir / "resources" / f"{GUID}.pbiviz.json").is_file()
    report = _report(project_dir)
    assert {
        "name": GUID, "type": "CustomVisual",
        "items": [{"name": f"{GUID}.pbiviz.json", "path": f"{GUID}.pbiviz.json", "type": "CustomVisualMetadata"}],
    } in report["resourcePackages"]
    assert report["publicCustomVisuals"] == [GUID]
    [annotation] = [a for a in report["annotations"] if a["name"] == f"powerbi-mcp.customVisual.{GUID}"]
    assert json.loads(annotation["value"])["roles"][1]["name"] == "Values"
    validate_report_json(report)

    assert result["visual_type"] == GUID
    assert result["display_name"] == "Tornado chart"
    assert result["roles"] == [
        {"name": "Category", "display_name": "Group", "accepts": ["column"], "min_fields": 0, "max_fields": 1},
        {"name": "Values", "display_name": "Values", "accepts": ["measure"], "min_fields": 1, "max_fields": 2},
        {"name": "Tooltips", "display_name": "Tooltips", "accepts": ["column", "measure"], "min_fields": 0, "max_fields": None},
    ]


def test_imported_visual_works_in_add_visual_with_its_roles(project_dir, tmp_path):
    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path)))

    result = visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=GUID, x=0, y=0, width=400, height=300,
        fields={"Category": ["Vendas.Regiao"], "Values": ["Vendas.Total Vendas", "Vendas.Lucro"]},
    )

    visual = json.loads(
        (project_dir / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / result["visual_name"] / "visual.json")
        .read_text(encoding="utf-8")
    )
    assert visual["visual"]["visualType"] == GUID
    assert set(visual["visual"]["query"]["queryState"]) == {"Category", "Values"}
    validate_visual_json(visual)


@pytest.mark.parametrize("fields", [
    {"Values": ["Vendas.Regiao"]},                                   # coluna num role de medida
    {"Category": ["Vendas.Total Vendas"], "Values": ["Vendas.Lucro"]},  # medida num role de coluna
    {"Values": ["Vendas.Total Vendas", "Vendas.Lucro", "Vendas.Total Vendas"]},  # acima do max
    {"Category": ["Vendas.Regiao"]},                                  # Values obrigatório (min 1)
    {"Nope": ["Vendas.Regiao"]},
])
def test_custom_visual_roles_are_validated(project_dir, tmp_path, fields):
    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path)))

    with pytest.raises(InvalidVisualRoleError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type=GUID, x=0, y=0, width=1, height=1, fields=fields,
        )


def test_unregistered_guid_is_still_unknown(project_dir):
    with pytest.raises(UnknownVisualTypeError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="NaoImportado123", x=0, y=0, width=1, height=1,
            fields={"Values": ["Vendas.Total Vendas"]},
        )


def test_list_and_remove(project_dir, tmp_path):
    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path)))

    [listed] = custom_visuals.list_custom_visuals(pbip_path=str(project_dir))
    assert (listed["visual_type"], listed["display_name"]) == (GUID, "Tornado chart")

    assert custom_visuals.remove_custom_visual(pbip_path=str(project_dir), visual_type=GUID) == {
        "visual_type": GUID, "removed": True,
    }
    assert not (project_dir / "Vendas.Report" / "CustomVisuals" / GUID).exists()
    report = _report(project_dir)
    assert all(p["name"] != GUID for p in report.get("resourcePackages", []))
    assert GUID not in report.get("publicCustomVisuals", [])
    assert not [a for a in report.get("annotations", []) if GUID in a["name"]]
    assert custom_visuals.list_custom_visuals(pbip_path=str(project_dir)) == []


def test_roles_survive_desktop_deleting_the_package_folder(project_dir, tmp_path):
    """Ao salvar, o Desktop apaga CustomVisuals/ (visto ao vivo) -- os roles
    continuam valendo pela anotação."""
    import shutil

    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path)))
    shutil.rmtree(project_dir / "Vendas.Report" / "CustomVisuals")

    visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=GUID, x=0, y=0, width=1, height=1,
        fields={"Category": ["Vendas.Regiao"], "Values": ["Vendas.Total Vendas"]},
    )
    [listed] = custom_visuals.list_custom_visuals(pbip_path=str(project_dir))
    assert listed["display_name"] == "Tornado chart" and listed["roles"]


def test_visual_added_only_through_the_desktop_is_listed_without_roles(project_dir):
    """Visual adicionado pela UI do Desktop (só publicCustomVisuals): aparece
    na lista, mas sem roles -- pra usar pelo MCP, importar o .pbiviz."""
    report_path = project_dir / "Vendas.Report" / "definition" / "report.json"
    report = _report(project_dir)
    report["publicCustomVisuals"] = ["OutroVisual123"]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    [listed] = custom_visuals.list_custom_visuals(pbip_path=str(project_dir))
    assert listed["visual_type"] == "OutroVisual123"
    assert listed["roles"] is None
    assert "import_custom_visual" in listed["note"]
    with pytest.raises(UnknownVisualTypeError):
        visual_writer.add_visual(
            pbip_path=str(project_dir), page_name="Pagina1", visual_type="OutroVisual123", x=0, y=0, width=1, height=1,
            fields={"Values": ["Vendas.Total Vendas"]},
        )


def test_remove_refuses_while_a_visual_uses_it(project_dir, tmp_path):
    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path)))
    visual_writer.add_visual(
        pbip_path=str(project_dir), page_name="Pagina1", visual_type=GUID, x=0, y=0, width=1, height=1,
        fields={"Values": ["Vendas.Total Vendas"]},
    )

    with pytest.raises(CustomVisualInUseError, match="Pagina1"):
        custom_visuals.remove_custom_visual(pbip_path=str(project_dir), visual_type=GUID)
    assert (project_dir / "Vendas.Report" / "CustomVisuals" / GUID).is_dir()


def test_remove_unknown(project_dir):
    with pytest.raises(CustomVisualNotFoundError):
        custom_visuals.remove_custom_visual(pbip_path=str(project_dir), visual_type="Nada")


def test_duplicate_import_needs_replace(project_dir, tmp_path):
    pbiviz = _make_pbiviz(tmp_path)
    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(pbiviz))

    with pytest.raises(CustomVisualAlreadyExistsError):
        custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(pbiviz))

    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(pbiviz), replace=True)
    report = _report(project_dir)
    assert len([p for p in report["resourcePackages"] if p["name"] == GUID]) == 1
    assert report["publicCustomVisuals"] == [GUID]
    assert len([a for a in report["annotations"] if GUID in a["name"]]) == 1


def test_existing_resource_packages_are_preserved(project_dir, tmp_path):
    report_path = project_dir / "Vendas.Report" / "definition" / "report.json"
    report = _report(project_dir)
    report["resourcePackages"] = [{"name": "SharedResources", "type": "SharedResources", "items": [
        {"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]}]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path)))

    names = [p["name"] for p in _report(project_dir)["resourcePackages"]]
    assert names == ["SharedResources", GUID]


@pytest.mark.parametrize("make", [
    lambda tmp: tmp / "nao_existe.pbiviz",
    lambda tmp: (tmp / "texto.pbiviz").write_text("nao é zip") and tmp / "texto.pbiviz",
    lambda tmp: _make_pbiviz(tmp, include_resource=False),
    lambda tmp: _make_pbiviz(tmp, guid="../../fora"),
    lambda tmp: _make_pbiviz(tmp, extra={"../../escape.txt": "x"}),
])
def test_bad_packages_are_rejected_without_writing(project_dir, tmp_path, make):
    pbiviz = make(tmp_path)

    with pytest.raises(InvalidCustomVisualError):
        custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(pbiviz))

    assert not (project_dir / "Vendas.Report" / "CustomVisuals").exists()
    assert not (tmp_path / "escape.txt").exists()
    report = _report(project_dir)
    assert "resourcePackages" not in report and "publicCustomVisuals" not in report


def test_conditions_with_alternatives_use_the_loosest_limits(project_dir, tmp_path):
    caps = _capabilities()
    caps["dataViewMappings"] = [{"conditions": [
        {"Category": {"max": 1}, "Values": {"min": 1, "max": 1}},
        {"Category": {"max": 0}, "Values": {"min": 2, "max": 3}},
    ]}]
    result = custom_visuals.import_custom_visual(
        pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path, capabilities=caps))
    )
    values = next(r for r in result["roles"] if r["name"] == "Values")
    assert (values["min_fields"], values["max_fields"]) == (1, 3)


def test_custom_visual_in_blueprint_and_plan_dashboard(project_dir, tmp_path):
    from orchestrator.applier import apply_dashboard_blueprint
    from orchestrator.planner import plan_dashboard

    custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbiviz(tmp_path)))

    plan = plan_dashboard(description="x", pbip_path=str(project_dir))
    assert [v["visual_type"] for v in plan["custom_visuals"]] == [GUID]

    result = apply_dashboard_blueprint(
        blueprint={"pages": [{"page_name": "Nova", "visuals": [{
            "visual_type": GUID, "x": 0, "y": 0, "width": 400, "height": 300,
            "fields": {"Category": ["Vendas.Regiao"], "Values": ["Vendas.Total Vendas"]},
        }]}]},
        pbip_path=str(project_dir),
    )
    assert result["pages"][0]["visuals"][0]["visual_type"] == GUID
    # o pacote continua no lugar depois do staging/swap do applier
    assert (project_dir / "Vendas.Report" / "CustomVisuals" / GUID / "package.json").is_file()


def test_plan_dashboard_without_report_has_no_custom_visuals(tmp_path):
    from orchestrator.planner import _custom_visuals

    assert _custom_visuals(str(tmp_path)) == []


# --- visual dentro de um .pbix (relatório que já usa o visual) ------------------
#
# Comparação com um .pbix salvo pelo Desktop (exemplo oficial do Tornado,
# 2026-09-30): o pacote fica em Report/CustomVisuals/<GUID>/ com o MESMO
# layout do .pbiviz (package.json + resources/<GUID>.pbiviz.json).


def _make_pbix(tmp_path: Path, guids: list[str]) -> Path:
    path = tmp_path / "exemplo.pbix"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Version", "1.28")
        zf.writestr("DataModel", "binario")
        zf.writestr("Report/definition/report.json", "{}")
        for guid in guids:
            base = f"Report/CustomVisuals/{guid}/"
            zf.writestr(base + "package.json", json.dumps({"visual": {"guid": guid, "displayName": guid}}))
            zf.writestr(base + f"resources/{guid}.pbiviz.json", json.dumps({"capabilities": _capabilities()}))
    return path


def test_import_from_pbix_takes_only_the_visual_package(project_dir, tmp_path):
    result = custom_visuals.import_custom_visual(
        pbip_path=str(project_dir), pbiviz_path=str(_make_pbix(tmp_path, [GUID]))
    )

    assert result["visual_type"] == GUID
    visual_dir = project_dir / "Vendas.Report" / "CustomVisuals" / GUID
    assert sorted(p.relative_to(visual_dir).as_posix() for p in visual_dir.rglob("*") if p.is_file()) == [
        "package.json", f"resources/{GUID}.pbiviz.json",
    ]


def test_pbix_with_several_visuals_needs_visual_guid(project_dir, tmp_path):
    pbix = _make_pbix(tmp_path, [GUID, "OutroVisual123"])

    with pytest.raises(InvalidCustomVisualError, match="OutroVisual123"):
        custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(pbix))

    result = custom_visuals.import_custom_visual(
        pbip_path=str(project_dir), pbiviz_path=str(pbix), visual_guid="OutroVisual123"
    )
    assert result["visual_type"] == "OutroVisual123"


def test_pbix_without_custom_visual_is_rejected(project_dir, tmp_path):
    with pytest.raises(InvalidCustomVisualError):
        custom_visuals.import_custom_visual(pbip_path=str(project_dir), pbiviz_path=str(_make_pbix(tmp_path, [])))
