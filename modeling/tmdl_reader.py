"""Leitor offline de ModelMetadata a partir dos arquivos .tmdl de uma
pasta .SemanticModel -- funciona com o Power BI Desktop fechado, sem
TOM, sem pythonnet.

TMDL (Tabular Model Definition Language) é um formato de texto completo
o bastante para expressar qualquer objeto do TOM; este leitor implementa
deliberadamente só o subconjunto que a validação de visuais precisa:

- `table <Nome>`, com blocos `column <Nome>` (propriedade `dataType`) e
  `measure <Nome> = <expressão DAX de uma linha>` (propriedade
  `formatString`).
- `relationship <id>`, com `fromColumn`/`toColumn` (referências
  `Tabela.Coluna`) e opcionalmente `crossFilteringBehavior`.

Não são interpretados: `partition` (fonte M/DAX de carga de dados,
irrelevante para metadata de campos), medidas DAX multi-linha
(`var ... return ...`), expressões entre crases (```), `ref`/ordenação de
coleção, `role`, `perspective`, `culture`, anotações e descrições
(`///`). Um modelo real que use essas construções ainda tem suas
tabelas/colunas/medidas/relacionamentos lidos corretamente -- só o que
essas construções adicionam é ignorado.
"""

from __future__ import annotations

import re
from pathlib import Path

from errors import SemanticModelNotFoundError
from modeling.metadata import ColumnInfo, MeasureInfo, ModelMetadata, RelationshipInfo, TableInfo

_TABLE_RE = re.compile(r"^table\s+(.+?)\s*$")
_COLUMN_RE = re.compile(r"^column\s+(.+?)\s*$")
_MEASURE_RE = re.compile(r"^measure\s+(.+?)\s*=\s*(.*)$")


def _split_name_and_expression(rest: str) -> tuple[str, str | None]:
    """`Nome = expr` / `'Nome com = dentro' = expr` / `Nome` -> (nome,
    expressão ou None). Achado ao vivo (2026-09-30): coluna calculada da
    tabela de datas automática vem como `column Ano = YEAR([Date])`, e o
    nome saía junto com a expressão. Nome entre aspas pode conter `=`."""
    rest = rest.strip()
    if rest.startswith("'"):
        end = _find_closing_quote(rest, 0)
        name, after = rest[: end + 1], rest[end + 1:].strip()
    else:
        name, sep, after = rest.partition("=")
        name, after = name.strip(), (after.strip() if sep else "")
        if not sep:
            return name, None
    if after.startswith("="):
        return name, after[1:].strip()
    return name, (after or None)
_PARTITION_RE = re.compile(r"^partition\b")
_PROPERTY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*:\s*(.*?)\s*$")
_RELATIONSHIP_RE = re.compile(r"^relationship\s+(.+?)\s*$")


def read_model_metadata(pbip_path: str) -> ModelMetadata:
    """Lê tabelas, colunas, medidas e relacionamentos a partir dos
    arquivos .tmdl encontrados a partir de `pbip_path`.

    `pbip_path` aceita, nessa ordem de tentativa: o caminho de um
    arquivo .pbip, a pasta raiz do projeto (que contém a pasta
    `*.SemanticModel`), a própria pasta `*.SemanticModel`, ou já a pasta
    `definition` dentro dela.

    Raises:
        SemanticModelNotFoundError: nenhuma definição TMDL foi
            encontrada a partir do caminho informado.
    """
    definition_dir = _resolve_definition_dir(pbip_path)

    table_infos: list[_ParsedTable] = []
    tables_dir = definition_dir / "tables"
    table_files = sorted(tables_dir.glob("*.tmdl")) if tables_dir.is_dir() else []
    for table_file in table_files:
        table_infos.append(_parse_table_file(table_file))

    measures = [m for t in table_infos for m in t.measures]

    relationships_file = definition_dir / "relationships.tmdl"
    relationships = (
        _parse_relationships_file(relationships_file) if relationships_file.is_file() else []
    )

    return ModelMetadata(
        tables=tuple(TableInfo(name=t.name, columns=tuple(t.columns)) for t in table_infos),
        measures=tuple(measures),
        relationships=tuple(relationships),
    )


# --- resolução de caminho -------------------------------------------------


def read_perspective_names(pbip_path: str) -> list[str]:
    """Nomes das perspectivas salvas (definition/perspectives/*.tmdl,
    uma por arquivo, linha `perspective <nome>` -- formato que o próprio
    Desktop gravou, conferido em 2026-09-30)."""
    perspectives_dir = _resolve_definition_dir(pbip_path) / "perspectives"
    if not perspectives_dir.is_dir():
        return []
    names = []
    for path in sorted(perspectives_dir.glob("*.tmdl")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("perspective "):
                names.append(_dequote(line[len("perspective "):]))
    return names


def _resolve_definition_dir(pbip_path: str) -> Path:
    path = Path(pbip_path)

    if path.is_dir() and path.name.endswith(".SemanticModel"):
        candidate = path / "definition"
        if candidate.is_dir():
            return candidate

    if path.is_dir() and path.name == "definition" and (path / "tables").is_dir():
        return path

    if path.is_file() and path.suffix.lower() == ".pbip":
        # Vários projetos podem dividir a mesma pasta: seguir o modelo que
        # ESTE projeto declara (relatório -> definition.pbir -> byPath), e
        # só depois o <nome>.SemanticModel do mesmo nome. Antes, o primeiro
        # *.SemanticModel em ordem alfabética era usado -- e lia o modelo de
        # outro projeto (achado em 2026-10-03, dashboard Cristallo).
        declared = _declared_semantic_model(path)
        for candidate_model in (declared, path.with_suffix(".SemanticModel")):
            if candidate_model is not None and (candidate_model / "definition").is_dir():
                return candidate_model / "definition"

    search_dir = path.parent if path.is_file() else path
    if search_dir.is_dir():
        candidates = [
            entry / "definition"
            for entry in sorted(search_dir.iterdir())
            if entry.is_dir() and entry.name.endswith(".SemanticModel") and (entry / "definition").is_dir()
        ]
        # .pbip que não aponta pra nenhum de vários modelos: não adivinhar
        # (revisão final de 2026-10-03 -- antes lia o modelo de outro projeto)
        if candidates and not (path.is_file() and len(candidates) > 1):
            return candidates[0]

    raise SemanticModelNotFoundError(pbip_path)


def _declared_semantic_model(pbip_file: Path) -> Path | None:
    """Pasta .SemanticModel que o relatório do .pbip referencia em
    `definition.pbir` (`datasetReference.byPath.path`), ou None."""
    import json

    try:
        pbip = json.loads(pbip_file.read_text(encoding="utf-8-sig"))
        for artifact in pbip.get("artifacts", []):
            report_path = artifact.get("report", {}).get("path")
            if not report_path:
                continue
            report_dir = pbip_file.parent / report_path
            pbir = json.loads((report_dir / "definition.pbir").read_text(encoding="utf-8-sig"))
            by_path = pbir.get("datasetReference", {}).get("byPath", {}).get("path")
            if by_path:
                return (report_dir / by_path).resolve()
    except (OSError, ValueError, AttributeError):
        return None
    return None


# --- parsing de tabela ------------------------------------------------


class _ParsedTable:
    __slots__ = ("name", "columns", "measures")

    def __init__(self, name: str) -> None:
        self.name = name
        self.columns: list[ColumnInfo] = []
        self.measures: list[MeasureInfo] = []


def _parse_table_file(path: Path) -> _ParsedTable:
    lines = path.read_text(encoding="utf-8").splitlines()
    table: _ParsedTable | None = None

    i = 0
    n = len(lines)
    while i < n:
        raw_line = lines[i]
        stripped = raw_line.strip()
        indent = _indent_of(raw_line)

        if not stripped or stripped.startswith("///"):
            i += 1
            continue

        if indent == 0:
            match = _TABLE_RE.match(stripped)
            if match and table is None:
                table = _ParsedTable(name=_dequote(match.group(1)))
            i += 1
            continue

        if table is None:
            i += 1
            continue

        if indent == 1:
            column_match = _COLUMN_RE.match(stripped)
            measure_match = _MEASURE_RE.match(stripped)
            partition_match = _PARTITION_RE.match(stripped)

            if column_match:
                column_name = _dequote(_split_name_and_expression(column_match.group(1))[0])
                data_type, i = _read_block_property(lines, i + 1, "dataType")
                table.columns.append(
                    ColumnInfo(name=column_name, data_type=_normalize_data_type(data_type or ""))
                )
                continue

            if measure_match:
                raw_name, raw_expression = _split_name_and_expression(stripped[len("measure"):])
                measure_name = _dequote(raw_name)
                expression = (raw_expression or "").strip()
                format_string, i = _read_block_property(lines, i + 1, "formatString")
                table.measures.append(
                    MeasureInfo(
                        table_name=table.name,
                        name=measure_name,
                        dax_expression=expression,
                        format_string=format_string,
                    )
                )
                continue

            if partition_match:
                i = _skip_block(lines, i + 1)
                continue

        i += 1

    if table is None:
        return _ParsedTable(name=path.stem)
    return table


def _read_block_property(lines: list[str], start: int, property_name: str) -> tuple[str | None, int]:
    """A partir da linha `start` (as propriedades de um column/measure,
    indentadas um nível a mais que a declaração), procura por
    `property_name: valor` até encontrar uma linha em indentação <= à do
    bloco (ou seja, o próximo irmão). Devolve o valor encontrado (ou
    None) e o índice da próxima linha a processar."""
    value: str | None = None
    i = start
    n = len(lines)
    while i < n:
        raw_line = lines[i]
        stripped = raw_line.strip()
        if not stripped:
            i += 1
            continue
        indent = _indent_of(raw_line)
        if indent < 2:
            break
        prop_match = _PROPERTY_RE.match(stripped)
        if prop_match and prop_match.group(1) == property_name:
            value = _unquote_value(prop_match.group(2))
        i += 1
    return value, i


def _skip_block(lines: list[str], start: int) -> int:
    i = start
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped and _indent_of(lines[i]) < 1:
            break
        i += 1
    return i


# --- parsing de relacionamentos -----------------------------------------


def _parse_relationships_file(path: Path) -> list[RelationshipInfo]:
    lines = path.read_text(encoding="utf-8").splitlines()
    relationships: list[RelationshipInfo] = []

    from_ref: tuple[str, str] | None = None
    to_ref: tuple[str, str] | None = None
    cross_filter = "single"
    in_relationship = False

    def _flush() -> None:
        nonlocal from_ref, to_ref, cross_filter, in_relationship
        if in_relationship and from_ref and to_ref:
            relationships.append(
                RelationshipInfo(
                    from_table=from_ref[0],
                    from_column=from_ref[1],
                    to_table=to_ref[0],
                    to_column=to_ref[1],
                    cardinality="many_to_one",
                    cross_filter_direction=cross_filter,
                )
            )
        from_ref, to_ref, cross_filter, in_relationship = None, None, "single", False

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("///"):
            continue
        indent = _indent_of(raw_line)

        if indent == 0:
            if _RELATIONSHIP_RE.match(stripped):
                _flush()
                in_relationship = True
            continue

        if not in_relationship:
            continue

        prop_match = _PROPERTY_RE.match(stripped)
        if not prop_match:
            continue
        key, value = prop_match.group(1), _unquote_value(prop_match.group(2))
        if key == "fromColumn":
            from_ref = _split_qualified_name(value)
        elif key == "toColumn":
            to_ref = _split_qualified_name(value)
        elif key == "crossFilteringBehavior":
            cross_filter = "both" if value.strip().lower() == "bothdirections" else "single"

    _flush()
    return relationships


def _split_qualified_name(value: str) -> tuple[str, str]:
    """Separa uma referência `Tabela.Coluna` (ou `'Tabela X'.'Coluna Y'`)
    em (tabela, coluna), respeitando nomes entre aspas simples que podem
    conter pontos."""
    value = value.strip()
    if value.startswith("'"):
        end = _find_closing_quote(value, 0)
        table = _dequote(value[: end + 1])
        rest = value[end + 1 :]
    else:
        dot = value.index(".")
        table = value[:dot]
        rest = value[dot:]

    rest = rest.lstrip(".")
    column = _dequote(rest)
    return table, column


def _find_closing_quote(value: str, start: int) -> int:
    i = start + 1
    while i < len(value):
        if value[i] == "'":
            if i + 1 < len(value) and value[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    return len(value) - 1


# --- utilitários de texto ----------------------------------------------


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip("\t "))


def _dequote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name.startswith("'") and name.endswith("'"):
        return name[1:-1].replace("''", "'")
    return name


def _unquote_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('""', '"')
    return value


def _normalize_data_type(tmdl_type: str) -> str:
    """TMDL usa camelCase (`int64`, `dateTime`); a implementação real de
    tom_runtime devolve os nomes do enum .NET DataType (PascalCase, ex.
    `Int64`, `DateTime`) via `str(col.DataType)`. Normalizamos aqui para
    a mesma convenção, para que o validador da camada de visuais (Fase
    3) não precise se importar com qual das duas fontes leu o campo."""
    if not tmdl_type:
        return tmdl_type
    return tmdl_type[0].upper() + tmdl_type[1:]
