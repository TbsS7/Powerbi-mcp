"""Contrato ModelMetadata e orquestração de list_model_metadata.

As dataclasses aqui definidas (`ColumnInfo`, `TableInfo`, `MeasureInfo`,
`RelationshipInfo`, `ModelMetadata`) são o contrato entre a camada de
modelagem e a camada de visuais: nenhum tipo .NET vaza por elas. Dois
produtores as constroem — leitura via XMLA (conexão TOM ativa) e leitura
offline dos arquivos .tmdl — e o validador da camada de visuais é o
consumidor.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from errors import PowerBiMcpError


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """Uma coluna de uma tabela do modelo."""

    name: str
    data_type: str


@dataclass(frozen=True, slots=True)
class TableInfo:
    """Uma tabela do modelo, com suas colunas."""

    name: str
    columns: tuple[ColumnInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class MeasureInfo:
    """Uma medida DAX do modelo.

    Nomes de medida são únicos em todo o modelo tabular (não só dentro
    da tabela), por isso ModelMetadata.find_measure busca só pelo nome.
    """

    table_name: str
    name: str
    dax_expression: str
    format_string: str | None = None


@dataclass(frozen=True, slots=True)
class RelationshipInfo:
    """Um relacionamento entre duas tabelas do modelo."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str
    cross_filter_direction: str


@dataclass(frozen=True, slots=True)
class HierarchyInfo:
    """Uma hierarquia de drill-down (ex: Ano > Trimestre > Mês) numa
    tabela do modelo. Não faz parte do contrato ModelMetadata/
    visuals.validator -- listada separadamente via list_hierarchies,
    porque a camada de visuais ainda não referencia hierarquias em
    `fields` de add_visual."""

    table_name: str
    name: str
    levels: tuple[str, ...]  # nomes de coluna, em ordem (nível mais alto primeiro)


@dataclass(frozen=True, slots=True)
class TablePermissionInfo:
    """Um filtro DAX de RLS (segurança em nível de LINHA) para uma
    tabela, dentro de um role, mais as colunas escondidas por OLS
    (segurança em nível de OBJETO) nessa mesma tabela/role -- são dois
    mecanismos diferentes que compartilham o mesmo TablePermission no
    TOM: RLS filtra quais linhas aparecem, OLS esconde a coluna por
    completo (dado e metadado -- membro do role nem sabe que ela
    existe)."""

    table_name: str
    filter_expression: str
    hidden_columns: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RoleInfo:
    """Um role de segurança em nível de linha (RLS): um nome e os
    filtros DAX por tabela que restringem o que membros desse role
    veem. Assim como HierarchyInfo, não faz parte do contrato
    ModelMetadata/visuals.validator -- listado separadamente via
    list_roles."""

    name: str
    table_permissions: tuple[TablePermissionInfo, ...] = field(default_factory=tuple)


# --- detalhes pra auditoria (modeling.audit) ---------------------------
#
# Mais ricos que ColumnInfo/TableInfo/MeasureInfo (descrição, visibilidade,
# pasta, sort-by, propriedades estendidas), e de propósito FORA do contrato
# ModelMetadata: esse contrato tem dois produtores (XMLA e o leitor TMDL
# offline) e é consumido pela camada de visuais -- estendê-lo exigiria
# mexer nos dois lados. Estes só vêm da conexão XMLA ativa, via
# TomRuntime.list_model_details. Propriedades lidas confirmadas por
# reflexão .NET (Table/Column/Measure.Description/IsHidden/DisplayFolder,
# Column.SortByColumn/ExtendedProperties).


@dataclass(frozen=True, slots=True)
class ColumnDetail:
    name: str
    data_type: str
    description: str | None = None
    is_hidden: bool = False
    display_folder: str | None = None
    sort_by_column: str | None = None
    extended_properties: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TableDetail:
    name: str
    description: str | None = None
    is_hidden: bool = False
    columns: tuple[ColumnDetail, ...] = ()


@dataclass(frozen=True, slots=True)
class MeasureDetail:
    table_name: str
    name: str
    dax_expression: str
    format_string: str | None = None
    description: str | None = None
    display_folder: str | None = None


@dataclass(frozen=True, slots=True)
class ModelDetails:
    tables: tuple[TableDetail, ...] = ()
    measures: tuple[MeasureDetail, ...] = ()


# --- calculation groups (modeling.calculation_groups) ------------------
#
# Fora do contrato ModelMetadata, como HierarchyInfo/RoleInfo -- listados
# por tool própria. Estrutura conforme a doc oficial ("Calculation groups
# in Analysis Services tabular models", TMSL/TMDL de exemplo) e reflexão
# .NET (Table.CalculationGroup, CalculationItem.Ordinal/
# FormatStringDefinition).


@dataclass(frozen=True, slots=True)
class CalculationItemInfo:
    name: str
    expression: str
    ordinal: int = -1
    # Expressão DAX que devolve a format string (ex: '"0.0%"', com aspas
    # -- é DAX, não a máscara crua). None = usa o formato da medida.
    format_string_expression: str | None = None


@dataclass(frozen=True, slots=True)
class CalculationGroupInfo:
    table_name: str
    column_name: str
    precedence: int
    items: tuple[CalculationItemInfo, ...] = ()


@dataclass(frozen=True, slots=True)
class PerspectiveTableInfo:
    """Uma tabela dentro de uma perspectiva: inteira (`include_all`) ou
    só as colunas/medidas/hierarquias listadas."""

    table_name: str
    include_all: bool = False
    columns: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    hierarchies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PerspectiveInfo:
    """Perspectiva: recorte do modelo mostrado a quem usa "Personalizar
    visuais" (não é segurança -- doc oficial)."""

    name: str
    description: str | None
    tables: tuple[PerspectiveTableInfo, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Snapshot completo do modelo: tabelas, medidas e relacionamentos.

    É o contrato consumido pelo validador da camada de visuais
    (visuals.validator) para resolver referências de campo antes de
    escrever qualquer visual.json.
    """

    tables: tuple[TableInfo, ...] = field(default_factory=tuple)
    measures: tuple[MeasureInfo, ...] = field(default_factory=tuple)
    relationships: tuple[RelationshipInfo, ...] = field(default_factory=tuple)

    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    def measure_names(self) -> list[str]:
        return [m.name for m in self.measures]

    def find_table(self, name: str) -> TableInfo | None:
        return next((t for t in self.tables if t.name == name), None)

    def find_measure(self, name: str) -> MeasureInfo | None:
        return next((m for m in self.measures if m.name == name), None)

    def find_column(self, table_name: str, column_name: str) -> ColumnInfo | None:
        table = self.find_table(table_name)
        if table is None:
            return None
        return next((c for c in table.columns if c.name == column_name), None)

    def to_dict(self) -> dict[str, Any]:
        """Representação em dict simples (str/número/list), pronta para
        ser devolvida como resultado de uma tool MCP."""
        return dataclasses.asdict(self)


class MetadataSourceUnavailableError(PowerBiMcpError):
    """Nenhuma fonte de metadata disponível: não há conexão XMLA ativa e
    nenhum pbip_path foi informado para leitura offline via TMDL."""

    def __init__(self) -> None:
        super().__init__(
            "Não há conexão ativa com o Power BI Desktop (chame "
            "connect_to_desktop primeiro) e nenhum 'pbip_path' foi "
            "informado para leitura offline. Informe um dos dois."
        )


def list_model_metadata(pbip_path: str | None = None) -> dict[str, Any]:
    """Lê o metadata do modelo: via XMLA se houver conexão ativa, senão
    via arquivos .tmdl se `pbip_path` foi informado.

    Args:
        pbip_path: Caminho da pasta ou arquivo .pbip do projeto, para
            leitura offline. Opcional se já houver conexão XMLA ativa.

    Returns:
        Dict serializável (ver ModelMetadata.to_dict) com `tables`,
        `measures` e `relationships`.
    """
    return get_model_metadata(pbip_path=pbip_path).to_dict()


def get_model_metadata(pbip_path: str | None = None) -> ModelMetadata:
    """Igual a list_model_metadata, mas devolve o objeto ModelMetadata
    em vez do dict serializado -- usado pela camada de visuais
    (visuals.validator), que precisa dos métodos find_table/find_measure,
    não de um dict.

    Raises:
        MetadataSourceUnavailableError: nenhuma conexão XMLA ativa e
            nenhum pbip_path informado.
    """
    from modeling import connection

    runtime = connection.get_active_runtime(required=False)
    if runtime is not None:
        return _read_from_runtime(runtime)

    if pbip_path:
        from modeling import tmdl_reader

        return tmdl_reader.read_model_metadata(pbip_path)

    raise MetadataSourceUnavailableError()


def _read_from_runtime(runtime: Any) -> ModelMetadata:
    return ModelMetadata(
        tables=tuple(runtime.list_tables()),
        measures=tuple(runtime.list_measures()),
        relationships=tuple(runtime.list_relationships()),
    )
