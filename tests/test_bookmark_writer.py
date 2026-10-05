"""Testes de visuals.bookmark_writer: create_bookmark, delete_bookmark,
list_bookmarks e a escrita de <nome>.bookmark.json / bookmarks.json.

MELHOR ESFORÇO: create_bookmark cria só um bookmark de "navegação de
página" (activeSection = page_name, sections vazio -- sem captura de
filtro/estado de visual). O valor de `explorationState.version` ("1.0")
não foi confirmado contra um bookmark real capturado pelo Power BI
Desktop -- pendente de validação ao vivo, ver README.

Cada arquivo escrito é validado contra o schema oficial correspondente
(bookmark/1.0.0, bookmarksMetadata/1.0.0), vendorizado em
tests/schemas/ a partir de developer.microsoft.com/json-schemas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errors import (
    BookmarkAlreadyExistsError,
    BookmarkNotFoundError,
    InvalidResourceNameError,
    PageNotFoundError,
)
from tests.schema_validation import validate_bookmark_json, validate_bookmarks_metadata_json
from visuals import bookmark_writer, page_writer


@pytest.fixture
def project_with_page(tmp_path: Path) -> Path:
    root = tmp_path / "VendasProject"
    root.mkdir()
    (root / "Vendas.pbip").write_text("{}", encoding="utf-8")
    (root / "Vendas.Report").mkdir()
    page_writer.create_report_page(pbip_path=str(root), page_name="Pagina1", display_name="Visão geral")
    return root


def _bookmarks_dir(project_root: Path) -> Path:
    return project_root / "Vendas.Report" / "definition" / "bookmarks"


def test_create_bookmark_writes_schema_valid_files(project_with_page: Path):
    result = bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bkVisaoGeral",
        page_name="Pagina1", display_name="Visão geral",
    )

    assert result == {
        "bookmark_name": "bkVisaoGeral", "display_name": "Visão geral", "page_name": "Pagina1",
    }

    bookmark_path = _bookmarks_dir(project_with_page) / "bkVisaoGeral.bookmark.json"
    assert bookmark_path.is_file()
    data = json.loads(bookmark_path.read_text(encoding="utf-8"))
    validate_bookmark_json(data)
    assert data["name"] == "bkVisaoGeral"
    assert data["displayName"] == "Visão geral"
    assert data["explorationState"]["activeSection"] == "Pagina1"

    bookmarks_json_path = _bookmarks_dir(project_with_page) / "bookmarks.json"
    bookmarks_data = json.loads(bookmarks_json_path.read_text(encoding="utf-8"))
    validate_bookmarks_metadata_json(bookmarks_data)
    assert bookmarks_data["items"] == [{"name": "bkVisaoGeral"}]


def test_create_bookmark_display_name_defaults_to_name(project_with_page: Path):
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bkX", page_name="Pagina1",
    )

    data = json.loads(
        (_bookmarks_dir(project_with_page) / "bkX.bookmark.json").read_text(encoding="utf-8")
    )
    assert data["displayName"] == "bkX"


def test_create_bookmark_appends_to_existing_items(project_with_page: Path):
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bk1", page_name="Pagina1",
    )
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bk2", page_name="Pagina1",
    )

    bookmarks_data = json.loads(
        (_bookmarks_dir(project_with_page) / "bookmarks.json").read_text(encoding="utf-8")
    )
    assert bookmarks_data["items"] == [{"name": "bk1"}, {"name": "bk2"}]


def test_create_bookmark_raises_when_page_does_not_exist(project_with_page: Path):
    with pytest.raises(PageNotFoundError):
        bookmark_writer.create_bookmark(
            pbip_path=str(project_with_page), bookmark_name="bk1", page_name="PaginaFantasma",
        )
    assert not _bookmarks_dir(project_with_page).exists()


def test_create_bookmark_raises_when_name_already_exists(project_with_page: Path):
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bk1", page_name="Pagina1",
    )

    with pytest.raises(BookmarkAlreadyExistsError):
        bookmark_writer.create_bookmark(
            pbip_path=str(project_with_page), bookmark_name="bk1", page_name="Pagina1",
        )


def test_delete_bookmark_removes_file_and_items_entry(project_with_page: Path):
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bk1", page_name="Pagina1",
    )
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bk2", page_name="Pagina1",
    )

    result = bookmark_writer.delete_bookmark(pbip_path=str(project_with_page), bookmark_name="bk1")

    assert result == {"bookmark_name": "bk1", "deleted": True}
    assert not (_bookmarks_dir(project_with_page) / "bk1.bookmark.json").exists()
    bookmarks_data = json.loads(
        (_bookmarks_dir(project_with_page) / "bookmarks.json").read_text(encoding="utf-8")
    )
    assert bookmarks_data["items"] == [{"name": "bk2"}]


def test_delete_bookmark_raises_when_not_found(project_with_page: Path):
    with pytest.raises(BookmarkNotFoundError):
        bookmark_writer.delete_bookmark(pbip_path=str(project_with_page), bookmark_name="fantasma")


def test_list_bookmarks_returns_all(project_with_page: Path):
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bk1", page_name="Pagina1",
        display_name="Primeiro",
    )
    bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="bk2", page_name="Pagina1",
    )

    result = bookmark_writer.list_bookmarks(pbip_path=str(project_with_page))

    assert result == [
        {"bookmark_name": "bk1", "display_name": "Primeiro", "page_name": "Pagina1"},
        {"bookmark_name": "bk2", "display_name": "bk2", "page_name": "Pagina1"},
    ]


def test_list_bookmarks_returns_empty_when_none_created(project_with_page: Path):
    assert bookmark_writer.list_bookmarks(pbip_path=str(project_with_page)) == []


def test_create_bookmark_raises_for_path_traversal_name(
    project_with_page: Path, tmp_path: Path
):
    """Achado de segurança: sem validar, um bookmark_name tipo
    '../../../../alvo' escaparia de definition/bookmarks/ (path
    traversal) antes de escrever o arquivo do bookmark."""
    with pytest.raises(InvalidResourceNameError):
        bookmark_writer.create_bookmark(
            pbip_path=str(project_with_page),
            bookmark_name="../" * 10 + "alvo",
            page_name="Pagina1",
        )
    assert not (tmp_path / "alvo.bookmark.json").exists()


def test_delete_bookmark_raises_for_path_traversal_name(project_with_page: Path):
    with pytest.raises(InvalidResourceNameError):
        bookmark_writer.delete_bookmark(
            pbip_path=str(project_with_page), bookmark_name="../" * 10 + "alvo",
        )


# --- bookmark de mostrar/esconder visuais (ex: painel de informações) ---------------
#
# Doc oficial bookmark.md ("Visibility toggles"): estado em
# explorationState.sections.<página>.visualContainers.<visual>; visível =
# {"singleVisual": {}}, escondido = {"singleVisual": {"display": {"mode":
# "hidden"}}}; `options` com targetVisualNames (os dois lados do toggle),
# suppressData true (não mexe em filtro/slicer), suppressDisplay false,
# suppressActiveSection true (não troca de página); version "1.3" (exemplo
# da doc). Visual escondido por padrão: `isHidden` na raiz do visual.json
# (schema oficial visualContainer/2.7.0).


def _two_visuals(root: Path) -> tuple[str, str]:
    from visuals import visual_writer

    names = []
    for text in ("Painel de informações", "Fechar"):
        names.append(visual_writer.add_visual(
            pbip_path=str(root), page_name="Pagina1", visual_type="textbox",
            x=0, y=0, width=100, height=40, text=text,
        )["visual_name"])
    return names[0], names[1]


def test_visibility_bookmark_matches_the_doc(project_with_page: Path):
    panel, close = _two_visuals(project_with_page)

    result = bookmark_writer.create_bookmark(
        pbip_path=str(project_with_page), bookmark_name="MostrarInfo", page_name="Pagina1",
        display_name="Mostrar informações", visible_visuals=[panel], hidden_visuals=[close],
    )

    data = json.loads((_bookmarks_dir(project_with_page) / "MostrarInfo.bookmark.json").read_text(encoding="utf-8"))
    validate_bookmark_json(data)
    assert data["options"] == {
        "targetVisualNames": [panel, close],
        "suppressData": True,
        "suppressDisplay": False,
        "suppressActiveSection": True,
        "applyOnlyToTargetVisuals": False,
    }
    assert data["explorationState"]["version"] == "1.3"
    assert data["explorationState"]["sections"] == {"Pagina1": {"visualContainers": {
        panel: {"singleVisual": {}},
        close: {"singleVisual": {"display": {"mode": "hidden"}}},
    }}}
    assert result["visible_visuals"] == [panel] and result["hidden_visuals"] == [close]


def test_visibility_bookmark_rejects_unknown_visual(project_with_page: Path):
    from errors import VisualNotFoundError

    with pytest.raises(VisualNotFoundError):
        bookmark_writer.create_bookmark(
            pbip_path=str(project_with_page), bookmark_name="X", page_name="Pagina1", hidden_visuals=["nao_existe"],
        )
    assert not (_bookmarks_dir(project_with_page) / "X.bookmark.json").exists()


def test_same_visual_cannot_be_visible_and_hidden(project_with_page: Path):
    from errors import InvalidBookmarkError

    panel, _ = _two_visuals(project_with_page)
    with pytest.raises(InvalidBookmarkError):
        bookmark_writer.create_bookmark(
            pbip_path=str(project_with_page), bookmark_name="X", page_name="Pagina1",
            visible_visuals=[panel], hidden_visuals=[panel],
        )


def test_set_visual_hidden_toggles_is_hidden(project_with_page: Path):
    from tests.schema_validation import validate_visual_json
    from visuals import visual_writer

    panel, _ = _two_visuals(project_with_page)
    path = project_with_page / "Vendas.Report" / "definition" / "pages" / "Pagina1" / "visuals" / panel / "visual.json"

    visual_writer.set_visual_hidden(pbip_path=str(project_with_page), page_name="Pagina1", visual_name=panel, hidden=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_visual_json(data)
    assert data["isHidden"] is True

    visual_writer.set_visual_hidden(pbip_path=str(project_with_page), page_name="Pagina1", visual_name=panel, hidden=False)
    assert "isHidden" not in json.loads(path.read_text(encoding="utf-8"))
