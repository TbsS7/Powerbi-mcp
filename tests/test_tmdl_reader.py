"""Testes de modeling.tmdl_reader: leitura offline de ModelMetadata a
partir dos arquivos .tmdl de uma pasta .SemanticModel -- sem TOM, sem
pythonnet, sem Power BI Desktop aberto.

Usa o fixture real em tests/fixtures/sample_pbip/ (2 tabelas, 1 medida,
1 relacionamento), reaproveitado pelas Fases 3 e 4.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from errors import SemanticModelNotFoundError
from modeling.tmdl_reader import read_model_metadata

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_pbip"


@pytest.fixture
def metadata():
    return read_model_metadata(str(FIXTURE_ROOT / "Vendas.pbip"))


def test_reads_both_tables(metadata):
    assert metadata.table_names() == ["Regiao", "Vendas"]


def test_reads_columns_with_normalized_data_type(metadata):
    vendas = metadata.find_table("Vendas")
    assert vendas is not None
    columns = {c.name: c.data_type for c in vendas.columns}
    assert columns == {"RegiaoId": "Int64", "Valor": "Double"}

    regiao = metadata.find_table("Regiao")
    assert regiao is not None
    assert {c.name: c.data_type for c in regiao.columns} == {
        "RegiaoId": "Int64",
        "Nome": "String",
    }


def test_reads_measure_with_expression_and_format_string(metadata):
    measure = metadata.find_measure("Total Vendas")
    assert measure is not None
    assert measure.table_name == "Vendas"
    assert measure.dax_expression == "SUM(Vendas[Valor])"
    assert measure.format_string == "#,##0.00"


def test_reads_relationship_with_default_cardinality(metadata):
    assert len(metadata.relationships) == 1
    rel = metadata.relationships[0]
    assert rel.from_table == "Vendas"
    assert rel.from_column == "RegiaoId"
    assert rel.to_table == "Regiao"
    assert rel.to_column == "RegiaoId"
    assert rel.cardinality == "many_to_one"
    assert rel.cross_filter_direction == "single"


def test_accepts_path_to_semantic_model_folder_directly():
    metadata = read_model_metadata(str(FIXTURE_ROOT / "Vendas.SemanticModel"))
    assert metadata.table_names() == ["Regiao", "Vendas"]


def test_accepts_path_to_project_root_directory():
    metadata = read_model_metadata(str(FIXTURE_ROOT))
    assert metadata.table_names() == ["Regiao", "Vendas"]


def test_accepts_path_to_definition_folder_directly():
    metadata = read_model_metadata(str(FIXTURE_ROOT / "Vendas.SemanticModel" / "definition"))
    assert metadata.table_names() == ["Regiao", "Vendas"]


def test_raises_when_path_does_not_resolve_to_a_semantic_model(tmp_path: Path):
    empty_dir = tmp_path / "not-a-project"
    empty_dir.mkdir()

    with pytest.raises(SemanticModelNotFoundError):
        read_model_metadata(str(empty_dir))


def test_reads_cross_filter_direction_both_when_specified(tmp_path: Path):
    project = tmp_path / "Outro.SemanticModel" / "definition"
    tables_dir = project / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "A.tmdl").write_text("table A\n\n\tcolumn Id\n\t\tdataType: int64\n", encoding="utf-8")
    (tables_dir / "B.tmdl").write_text("table B\n\n\tcolumn Id\n\t\tdataType: int64\n", encoding="utf-8")
    (project / "relationships.tmdl").write_text(
        "relationship guid-1\n\tfromColumn: A.Id\n\ttoColumn: B.Id\n\tcrossFilteringBehavior: bothDirections\n",
        encoding="utf-8",
    )

    metadata = read_model_metadata(str(project.parent))

    assert metadata.relationships[0].cross_filter_direction == "both"


def test_reads_quoted_names_with_spaces(tmp_path: Path):
    project = tmp_path / "Quoted.SemanticModel" / "definition"
    tables_dir = project / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "Sales.tmdl").write_text(
        "table Sales\n"
        "\n"
        "\tcolumn 'Order Date'\n"
        "\t\tdataType: dateTime\n"
        "\n"
        "\tmeasure 'Total Sales' = SUM(Sales[Amount])\n"
        "\t\tformatString: $ #,##0\n",
        encoding="utf-8",
    )

    metadata = read_model_metadata(str(project.parent))

    sales = metadata.find_table("Sales")
    assert sales is not None
    assert sales.columns[0].name == "Order Date"
    assert sales.columns[0].data_type == "DateTime"
    measure = metadata.find_measure("Total Sales")
    assert measure is not None
    assert measure.dax_expression == "SUM(Sales[Amount])"


def test_model_without_relationships_file_has_empty_relationships(tmp_path: Path):
    project = tmp_path / "Solo.SemanticModel" / "definition"
    tables_dir = project / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "A.tmdl").write_text("table A\n\n\tcolumn Id\n\t\tdataType: int64\n", encoding="utf-8")

    metadata = read_model_metadata(str(project.parent))

    assert metadata.relationships == ()


def test_calculated_column_name_does_not_include_the_expression(tmp_path: Path):
    """Bug achado ao vivo (2026-09-30), réplica de dashboard sem conexão
    ativa: na tabela de datas automática o TMDL tem `column Ano =
    YEAR([Date])` (coluna calculada, expressão na mesma linha) e o leitor
    devolvia a coluna "Ano = YEAR([Date])" -- remove_page_filter em
    "...Ano" falhava com "campo não encontrado"."""
    project = tmp_path / "Calc.SemanticModel" / "definition"
    tables_dir = project / "tables"
    tables_dir.mkdir(parents=True)
    (tables_dir / "Datas.tmdl").write_text(
        "table Datas\n"
        "\n"
        "\tcolumn Date\n"
        "\t\tdataType: dateTime\n"
        "\n"
        "\tcolumn Ano = YEAR([Date])\n"
        "\t\tdataType: int64\n"
        "\n"
        "\tcolumn 'Mês = nome' = FORMAT([Date], \"MMMM\")\n"
        "\t\tdataType: string\n"
        "\n"
        "\tmeasure 'A = B' = 1\n",
        encoding="utf-8",
    )

    metadata = read_model_metadata(str(project.parent))

    datas = metadata.find_table("Datas")
    assert [(c.name, c.data_type) for c in datas.columns] == [
        ("Date", "DateTime"), ("Ano", "Int64"), ("Mês = nome", "String"),
    ]
    measure = metadata.find_measure("A = B")
    assert measure is not None and measure.dax_expression == "1"


# --- vários projetos na mesma pasta (achado 03/10: o leitor pegava o
# primeiro *.SemanticModel em ordem alfabética, não o do .pbip pedido) ----


def _two_projects(tmp_path: Path, with_pbir: bool, model_name: str = "Vendas") -> Path:
    import json
    import shutil

    # "AAA" vem antes de "Vendas" em ordem alfabética: é o modelo ERRADO.
    shutil.copytree(FIXTURE_ROOT / "Vendas.SemanticModel", tmp_path / "AAA.SemanticModel")
    for tmdl in (tmp_path / "AAA.SemanticModel" / "definition" / "tables").glob("*.tmdl"):
        tmdl.unlink()
    (tmp_path / "AAA.SemanticModel" / "definition" / "relationships.tmdl").unlink()
    (tmp_path / "AAA.SemanticModel" / "definition" / "tables" / "Outra.tmdl").write_text(
        "table Outra\n\n\tcolumn Id\n\t\tdataType: int64\n\t\tsourceColumn: Id\n", encoding="utf-8"
    )
    shutil.copytree(FIXTURE_ROOT / "Vendas.SemanticModel", tmp_path / f"{model_name}.SemanticModel")
    shutil.copy(FIXTURE_ROOT / "Vendas.pbip", tmp_path / "Vendas.pbip")
    if with_pbir:
        report = tmp_path / "Vendas.Report"
        report.mkdir()
        (report / "definition.pbir").write_text(
            json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": f"../{model_name}.SemanticModel"}}}),
            encoding="utf-8",
        )
    return tmp_path / "Vendas.pbip"


def test_pbip_follows_report_dataset_reference(tmp_path: Path):
    # nome do modelo diferente do .pbip: só passa seguindo o byPath
    # (revisão final: com o mesmo nome o teste passaria sem ele)
    pbip = _two_projects(tmp_path, with_pbir=True, model_name="Modelo")

    assert read_model_metadata(str(pbip)).table_names() == ["Regiao", "Vendas"]


def test_pbip_without_pbir_prefers_semantic_model_with_same_name(tmp_path: Path):
    pbip = _two_projects(tmp_path, with_pbir=False)

    assert read_model_metadata(str(pbip)).table_names() == ["Regiao", "Vendas"]


def test_pbip_refuses_to_guess_between_semantic_models(tmp_path: Path):
    # sem definition.pbir e sem <nome>.SemanticModel, com dois modelos na
    # pasta -> antes caía no primeiro em ordem alfabética (o ERRADO).
    pbip = _two_projects(tmp_path, with_pbir=False, model_name="Modelo")

    with pytest.raises(SemanticModelNotFoundError):
        read_model_metadata(str(pbip))
