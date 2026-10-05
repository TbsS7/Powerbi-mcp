"""Única fronteira com .NET/pythonnet deste projeto.

Nenhum outro módulo deve importar `clr` ou referenciar tipos do
namespace `Microsoft.AnalysisServices.*` diretamente -- tudo passa pela
interface Python pura `TomRuntime` definida aqui, que `connection.py` e
`operations.py` consomem sem saber (nem precisar saber) que por baixo
existe um objeto .NET.

É essa fronteira que torna a suíte de testes deste projeto independente
de Power BI Desktop instalado: os testes injetam um `FakeTomRuntime`
(tests/fakes/fake_tom.py) que implementa o mesmo Protocol em memória
pura, e todo o resto da camada de modelagem funciona sem alterações.

A implementação real (`connect`, `_PythonnetTomRuntime`) importa `clr` e
constrói os objetos TOM (`Server`, `Database`, `Model`, `Table`,
`Measure`, `Relationship`) somente dentro de suas funções -- nunca no
nível do módulo -- para que este arquivo possa ser importado (e a
resolução de DLLs testada) mesmo sem pythonnet instalado.

`connect()` e `list_tables()`/`list_measures()`/`list_relationships()`
foram validados com uma conexão real (Power BI Desktop via Microsoft
Store + DLLs de scripts/setup_tom.py). Não têm cobertura de teste
*automatizado* nesta máquina -- não há como simular XMLA/TOM real em
CI sem o Power BI Desktop instalado -- mas a suíte automatizada cobre
toda a lógica ao redor (resolução de DLL, seleção de runtime .NET,
mapeamento de cardinalidade) via funções puras e o FakeTomRuntime.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from errors import DatabaseNotFoundOnPortError, ModelObjectNotFoundError, TomDllNotFoundError
from modeling.metadata import (
    CalculationGroupInfo,
    CalculationItemInfo,
    ColumnDetail,
    ColumnInfo,
    HierarchyInfo,
    MeasureDetail,
    MeasureInfo,
    PerspectiveInfo,
    PerspectiveTableInfo,
    ModelDetails,
    RelationshipInfo,
    RoleInfo,
    TableDetail,
    TableInfo,
    TablePermissionInfo,
)
from modeling.tom_errors import wrap_dotnet_errors

REQUIRED_DLLS: tuple[str, ...] = (
    "Microsoft.AnalysisServices.Core.dll",
    "Microsoft.AnalysisServices.Tabular.dll",
    "Microsoft.AnalysisServices.Tabular.Json.dll",
)


class TomRuntime(Protocol):
    """Interface Python pura para uma conexão TOM com um modelo tabular
    aberto (via Power BI Desktop) ou, em testes, com o grafo em memória
    de um FakeTomRuntime.

    Os métodos espelham deliberadamente a forma do objeto TOM real
    (Server > Database > Model > Tables/Measures/Relationships +
    SaveChanges) para que a implementação real seja um wrapper fino, e
    o fake seja um espelho fiel e fácil de auditar.
    """

    @property
    def port(self) -> int: ...

    @property
    def database_name(self) -> str: ...

    @property
    def compatibility_level(self) -> int: ...

    def refresh_metadata(self) -> None: ...

    def list_tables(self) -> tuple[TableInfo, ...]: ...

    def list_measures(self) -> tuple[MeasureInfo, ...]: ...

    def list_relationships(self) -> tuple[RelationshipInfo, ...]: ...

    def list_model_details(self) -> ModelDetails: ...

    def create_calculated_table(self, table_name: str, dax_expression: str) -> TableInfo: ...

    def create_measure(
        self,
        table_name: str,
        measure_name: str,
        dax_expression: str,
        format_string: str | None,
    ) -> MeasureInfo: ...

    def create_relationship(
        self,
        from_table: str,
        from_column: str,
        to_table: str,
        to_column: str,
        cardinality: str,
        cross_filter_direction: str,
    ) -> RelationshipInfo: ...

    def delete_table(self, table_name: str) -> None: ...

    def delete_measure(self, table_name: str, measure_name: str) -> None: ...

    def update_measure(
        self,
        table_name: str,
        measure_name: str,
        dax_expression: str | None,
        format_string: str | None,
    ) -> MeasureInfo: ...

    def delete_relationship(
        self, from_table: str, from_column: str, to_table: str, to_column: str
    ) -> None: ...

    def create_calculated_column(
        self,
        table_name: str,
        column_name: str,
        dax_expression: str,
        format_string: str | None,
    ) -> ColumnInfo: ...

    def delete_column(self, table_name: str, column_name: str) -> None: ...

    def create_hierarchy(
        self, table_name: str, hierarchy_name: str, levels: list[str]
    ) -> HierarchyInfo: ...

    def delete_hierarchy(self, table_name: str, hierarchy_name: str) -> None: ...

    def list_hierarchies(self) -> tuple[HierarchyInfo, ...]: ...

    def create_role(self, role_name: str) -> RoleInfo: ...

    def add_table_permission(
        self, role_name: str, table_name: str, filter_expression: str
    ) -> RoleInfo: ...

    def delete_role(self, role_name: str) -> None: ...

    def list_roles(self) -> tuple[RoleInfo, ...]: ...

    def hide_column(self, role_name: str, table_name: str, column_name: str) -> RoleInfo: ...

    def unhide_column(self, role_name: str, table_name: str, column_name: str) -> RoleInfo: ...

    def refresh_table(self, table_name: str) -> None: ...

    def refresh_model(self) -> None: ...

    def set_table_description(self, table_name: str, description: str) -> None: ...

    def set_column_metadata(
        self,
        table_name: str,
        column_name: str,
        description: str | None,
        display_folder: str | None,
    ) -> None: ...

    def set_column_sort_by(
        self, table_name: str, column_name: str, sort_by_column: str | None
    ) -> None: ...

    def set_column_format(
        self,
        table_name: str,
        column_name: str,
        format_string: str | None,
        data_category: str | None,
    ) -> None: ...

    def set_column_visibility(self, table_name: str, column_name: str, is_hidden: bool) -> None: ...

    def set_column_related_column(
        self, table_name: str, column_name: str, grouping_column_name: str
    ) -> None: ...

    def set_column_extended_property(
        self, table_name: str, column_name: str, property_name: str, json_value: str
    ) -> None: ...

    def set_measure_metadata(
        self,
        table_name: str,
        measure_name: str,
        description: str | None,
        display_folder: str | None,
    ) -> None: ...

    def get_discourage_implicit_measures(self) -> bool: ...

    def set_discourage_implicit_measures(self, value: bool) -> None: ...

    def create_calculation_group(
        self,
        table_name: str,
        column_name: str,
        precedence: int,
        items: tuple[CalculationItemInfo, ...],
    ) -> CalculationGroupInfo: ...

    def add_calculation_item(self, table_name: str, item: CalculationItemInfo) -> None: ...

    def delete_calculation_item(self, table_name: str, item_name: str) -> None: ...

    def list_calculation_groups(self) -> tuple[CalculationGroupInfo, ...]: ...

    def create_perspective(self, perspective: PerspectiveInfo) -> None: ...

    def delete_perspective(self, name: str) -> None: ...

    def list_perspectives(self) -> tuple[PerspectiveInfo, ...]: ...

    def save_changes(self) -> None: ...

    def disconnect(self) -> None: ...


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_dll_dirs() -> list[Path]:
    """Locais conhecidos onde as DLLs do TOM podem estar instaladas,
    em ordem de prioridade (depois de TOM_DLL_PATH, tratado separado em
    resolve_tom_dll_dir). Ver README, seção "Licenciamento e obtenção do
    TOM"."""
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))

    candidates = [
        # pasta gerada por scripts/setup_tom.py -- checada primeiro
        # porque, se existe, foi colocada lá deliberadamente para este
        # projeto (e o script já confere o SHA-512 contra a Microsoft).
        _project_root() / ".tom-dlls" / "dlls",
        program_files / "Microsoft Power BI Desktop" / "bin",
        program_files_x86 / "Tabular Editor",
        program_files / "Tabular Editor",
        program_files_x86 / "Tabular Editor 3",
        program_files / "Tabular Editor 3",
    ]

    sql_server_root = program_files / "Microsoft SQL Server"
    if sql_server_root.is_dir():
        assemblies_dirs = sorted(
            sql_server_root.glob("*/SDK/Assemblies"),
            key=lambda p: p.parts[-3],
            reverse=True,
        )
        candidates.extend(assemblies_dirs)

    return candidates


def _cardinality_from_tom(from_cardinality: object, to_cardinality: object) -> str:
    """Traduz o par (FromCardinality, ToCardinality) do TOM real para a
    convenção deste projeto ("many_to_one" etc.), usada por
    FakeTomRuntime, tmdl_reader e pelo Literal aceito na tool
    create_relationship. Compara via str() para não precisar importar o
    enum .NET RelationshipEndCardinality aqui."""
    from_str, to_str = str(from_cardinality), str(to_cardinality)
    if from_str == "One" and to_str == "One":
        return "one_to_one"
    if from_str == "One" and to_str == "Many":
        return "one_to_many"
    return "many_to_one"


def _cross_filter_from_tom(cross_filtering_behavior: object) -> str:
    return "both" if str(cross_filtering_behavior) == "BothDirections" else "single"


def _has_required_dlls(directory: Path) -> bool:
    return directory.is_dir() and all((directory / dll).is_file() for dll in REQUIRED_DLLS)


def resolve_tom_dll_dir(extra_candidates: list[Path] | None = None) -> Path:
    """Encontra um diretório contendo as três DLLs do TOM.

    Ordem de prioridade: `TOM_DLL_PATH` (variável de ambiente) primeiro,
    depois `extra_candidates` (usado pelos testes para injetar diretórios
    fake sem depender do sistema de arquivos real), depois os locais de
    instalação conhecidos (`_candidate_dll_dirs`).

    Raises:
        TomDllNotFoundError: nenhum candidato continha as três DLLs.
    """
    searched: list[Path] = []

    env_path = os.environ.get("TOM_DLL_PATH")
    if env_path:
        env_dir = Path(env_path)
        searched.append(env_dir)
        if _has_required_dlls(env_dir):
            return env_dir

    for candidate in (extra_candidates or []) + _candidate_dll_dirs():
        searched.append(candidate)
        if _has_required_dlls(candidate):
            return candidate

    raise TomDllNotFoundError(searched_paths=[str(p) for p in searched])


def _dotnet_runtime_name() -> str:
    """Qual runtime .NET o pythonnet deve carregar, via
    `pythonnet.load(...)`, antes do primeiro `import clr`.

    Descoberto testando contra um Power BI Desktop real: no Windows, o
    pythonnet carrega .NET Framework por padrão -- mas as DLLs do TOM
    que scripts/setup_tom.py baixa são a variante NetCore
    (netcoreapp3.0). Um assembly .NET Core carregado dentro do .NET
    Framework produz TypeLoadException em assemblies de fachada como
    System.ComponentModel.Primitives. "coreclr" casa com essas DLLs;
    PYTHONNET_RUNTIME deixa quem usa DLLs .NET Framework (ex.: as que
    vêm com o Tabular Editor) sobrescrever sem mexer em código.
    """
    return os.environ.get("PYTHONNET_RUNTIME", "coreclr")


def connect(port: int, database_name: str | None = None) -> TomRuntime:
    """Conecta ao endpoint XMLA local de uma instância do Power BI
    Desktop e devolve um TomRuntime que opera sobre o banco encontrado.

    Validado com uma conexão real (Power BI Desktop via Microsoft
    Store + DLLs de scripts/setup_tom.py) -- ver README.

    Raises:
        TomDllNotFoundError: se as DLLs do TOM não puderem ser
            localizadas (propagado por resolve_tom_dll_dir).
    """
    dll_dir = resolve_tom_dll_dir()

    import sys

    if str(dll_dir) not in sys.path:
        sys.path.append(str(dll_dir))

    import pythonnet  # noqa: PLC0415 - import tardio deliberado, ver docstring do módulo

    pythonnet.load(_dotnet_runtime_name())  # precisa vir antes do 1º "import clr"

    import clr  # noqa: PLC0415 - import tardio deliberado, ver docstring do módulo

    for dll_name in REQUIRED_DLLS:
        clr.AddReference(str(dll_dir / dll_name))

    from Microsoft.AnalysisServices.Tabular import Server  # type: ignore[import-not-found]

    server = Server()
    with wrap_dotnet_errors("connect"):
        server.Connect(f"Data Source=localhost:{port}")

        if database_name:
            database = next((db for db in server.Databases if db.Name == database_name), None)
            if database is None:
                available = [db.Name for db in server.Databases]
                raise DatabaseNotFoundOnPortError(
                    database_name=database_name, port=port, available=available
                )
        else:
            database = server.Databases[0]

    return _PythonnetTomRuntime(server=server, database=database, port=port)


class _PythonnetTomRuntime:
    """Implementação real do TomRuntime Protocol sobre objetos TOM
    (.NET) vivos. Ver docstring do módulo: sem cobertura de teste
    automatizado nesta máquina."""

    def __init__(self, server: object, database: object, port: int) -> None:
        self._server = server
        self._database = database
        self._port = port

    @property
    def port(self) -> int:
        return self._port

    @property
    def database_name(self) -> str:
        return self._database.Name  # type: ignore[attr-defined]

    @property
    def compatibility_level(self) -> int:
        return self._database.CompatibilityLevel  # type: ignore[attr-defined]

    def _model(self):
        return self._database.Model  # type: ignore[attr-defined]

    # --- helpers de busca --------------------------------------------
    #
    # Substituem os `next(x for x in colecao if x.Name == nome)` soltos
    # que existiam antes em todo o arquivo: sem eles, um objeto não
    # encontrado levantava `StopIteration` crua -- uma exceção sem
    # mensagem nenhuma (achado ao vivo: virava "Error executing tool X"
    # com zero contexto). `operations.py` já valida a existência da
    # maioria desses objetos antes de chamar o runtime; estes helpers
    # são a rede de segurança para quem chama o TomRuntime direto
    # (field_parameters.py, applier.py) e para divergências de
    # última hora entre a validação e o uso.

    def _find_table(self, table_name: str):
        model = self._model()
        for table in model.Tables:
            if table.Name == table_name:
                return table
        raise ModelObjectNotFoundError(
            "tabela", table_name, known=[t.Name for t in model.Tables]
        )

    def _find_column(self, table, column_name: str):
        for column in table.Columns:
            if column.Name == column_name:
                return column
        raise ModelObjectNotFoundError(
            "coluna", column_name,
            known=[c.Name for c in table.Columns], parent=table.Name,
        )

    def _find_measure(self, table, measure_name: str):
        for measure in table.Measures:
            if measure.Name == measure_name:
                return measure
        raise ModelObjectNotFoundError(
            "medida", measure_name,
            known=[m.Name for m in table.Measures], parent=table.Name,
        )

    def _find_hierarchy(self, table, hierarchy_name: str):
        for hierarchy in table.Hierarchies:
            if hierarchy.Name == hierarchy_name:
                return hierarchy
        raise ModelObjectNotFoundError(
            "hierarquia", hierarchy_name,
            known=[h.Name for h in table.Hierarchies], parent=table.Name,
        )

    def _find_role(self, role_name: str):
        model = self._model()
        for role in model.Roles:
            if role.Name == role_name:
                return role
        raise ModelObjectNotFoundError(
            "role", role_name, known=[r.Name for r in model.Roles]
        )

    def _find_table_permission(self, role, table_name: str):
        for permission in role.TablePermissions:
            if permission.Table.Name == table_name:
                return permission
        raise ModelObjectNotFoundError(
            "permissão de tabela", table_name,
            known=[p.Table.Name for p in role.TablePermissions], parent=role.Name,
        )

    def _find_column_permission(self, table_permission, column_name: str):
        for column_permission in table_permission.ColumnPermissions:
            if column_permission.Column.Name == column_name:
                return column_permission
        raise ModelObjectNotFoundError(
            "permissão de coluna", column_name,
            known=[cp.Column.Name for cp in table_permission.ColumnPermissions],
            parent=table_permission.Table.Name,
        )

    def _find_relationship(self, model, from_table, from_column, to_table, to_column):
        for relationship in model.Relationships:
            if (
                relationship.FromTable.Name == from_table
                and relationship.FromColumn.Name == from_column
                and relationship.ToTable.Name == to_table
                and relationship.ToColumn.Name == to_column
            ):
                return relationship
        raise ModelObjectNotFoundError(
            "relacionamento", f"{from_table}.{from_column} -> {to_table}.{to_column}",
            known=[
                f"{r.FromTable.Name}.{r.FromColumn.Name} -> {r.ToTable.Name}.{r.ToColumn.Name}"
                for r in model.Relationships
            ],
        )

    def refresh_metadata(self) -> None:
        """Ressincroniza o objeto `Model` local com o que está no
        servidor -- `Model` é um snapshot do momento do `connect()`
        (nunca se atualiza sozinho), então uma tabela criada por outra
        conexão (ex: pela UI do Desktop) depois do nosso connect não
        aparecia em nenhuma leitura até isso ser chamado.

        CONFIRMADO AO VIVO: criamos uma tabela numa conexão .NET
        separada da conexão "presa" e comparamos `list(model.Tables)`
        antes/depois de `Model.Sync()` -- só apareceu depois. Chamado
        no início de cada método de leitura (não nas escritas, que já
        resolvem no próprio `SaveChanges`).

        GUARDA (não confirmada ao vivo, só por reflexão): se o modelo
        tem mudança local pendente (`Model.HasLocalChanges`, ex.: uma
        sequência de create_measure(save=False) ainda não salva), NÃO
        chama `Sync()` -- existe `SyncOptions.DiscardLocalChanges` como
        propriedade separada e opt-in, o que sugere que `Sync()` sem
        opções pode tentar mesclar/descartar mudança local de um jeito
        não documentado. Como este projeto depende inteiro de acumular
        edição sem salvar (save=False em várias tools) até um save
        final, o risco de perder trabalho não salvo é maior que o custo
        de servir uma leitura levemente desatualizada enquanto há
        edição pendente.

        Envolvida com wrap_dotnet_errors: é aqui, sendo chamada no
        início de toda leitura, que uma conexão morta (processo interno
        do Desktop reiniciado -- observado ao vivo nesta sessão) é mais
        provável de aparecer primeiro. Decisão de arquitetura (bug 1.3
        do plano original): checar a porta ativa contra
        discovery.find_desktop_instances() *proativamente* em
        connection.get_active_runtime() foi cogitado, mas quebraria a
        independência de .NET dos testes baseados em FakeTomRuntime
        (get_active_runtime roda em todo teste, e não há instância real
        do Desktop no ambiente de teste). Traduzir a exceção .NET real
        quando ela de fato acontece -- aqui e nos pontos de escrita
        (save_changes/refresh_table/refresh_model) -- cobre o mesmo caso
        de uso sem esse custo."""
        model = self._model()
        if model.HasLocalChanges:
            return
        with wrap_dotnet_errors("refresh_metadata", self._live_ports):
            model.Sync()

    def list_tables(self) -> tuple[TableInfo, ...]:
        from modeling.metadata import ColumnInfo

        self.refresh_metadata()
        tables = []
        for table in self._model().Tables:
            columns = tuple(
                ColumnInfo(name=col.Name, data_type=str(col.DataType)) for col in table.Columns
            )
            tables.append(TableInfo(name=table.Name, columns=columns))
        return tuple(tables)

    def list_measures(self) -> tuple[MeasureInfo, ...]:
        self.refresh_metadata()
        measures = []
        for table in self._model().Tables:
            for measure in table.Measures:
                measures.append(
                    MeasureInfo(
                        table_name=table.Name,
                        name=measure.Name,
                        dax_expression=measure.Expression,
                        format_string=measure.FormatString or None,
                    )
                )
        return tuple(measures)

    def list_relationships(self) -> tuple[RelationshipInfo, ...]:
        self.refresh_metadata()
        relationships = []
        for rel in self._model().Relationships:
            relationships.append(
                RelationshipInfo(
                    from_table=rel.FromTable.Name,
                    from_column=rel.FromColumn.Name,
                    to_table=rel.ToTable.Name,
                    to_column=rel.ToColumn.Name,
                    cardinality=_cardinality_from_tom(rel.FromCardinality, rel.ToCardinality),
                    cross_filter_direction=_cross_filter_from_tom(rel.CrossFilteringBehavior),
                )
            )
        return tuple(relationships)

    def list_model_details(self) -> ModelDetails:
        """Leitura rica pra auditoria (modeling.audit) -- ver comentário
        sobre ColumnDetail/TableDetail em modeling/metadata.py.
        Propriedades confirmadas por reflexão .NET. Pula colunas de
        sistema (`ColumnType.RowNumber` -- a coluna `RowNumber-<guid>`
        que toda tabela tem, confirmado ao vivo em list_model_metadata)."""
        self.refresh_metadata()
        tables = []
        measures = []
        for table in self._model().Tables:
            columns = tuple(
                ColumnDetail(
                    name=col.Name,
                    data_type=str(col.DataType),
                    description=col.Description or None,
                    is_hidden=bool(col.IsHidden),
                    display_folder=col.DisplayFolder or None,
                    sort_by_column=col.SortByColumn.Name if col.SortByColumn is not None else None,
                    extended_properties=tuple(p.Name for p in col.ExtendedProperties),
                )
                for col in table.Columns
                if str(col.Type) != "RowNumber"
            )
            tables.append(
                TableDetail(
                    name=table.Name,
                    description=table.Description or None,
                    is_hidden=bool(table.IsHidden),
                    columns=columns,
                )
            )
            for measure in table.Measures:
                measures.append(
                    MeasureDetail(
                        table_name=table.Name,
                        name=measure.Name,
                        dax_expression=measure.Expression,
                        format_string=measure.FormatString or None,
                        description=measure.Description or None,
                        display_folder=measure.DisplayFolder or None,
                    )
                )
        return ModelDetails(tables=tuple(tables), measures=tuple(measures))

    def create_calculated_table(self, table_name: str, dax_expression: str) -> TableInfo:
        from Microsoft.AnalysisServices.Tabular import (  # type: ignore[import-not-found]
            CalculatedPartitionSource,
            Partition,
            Table,
        )

        table = Table()
        table.Name = table_name
        partition = Partition()
        partition.Name = table_name
        partition.Source = CalculatedPartitionSource()
        partition.Source.Expression = dax_expression
        table.Partitions.Add(partition)
        self._model().Tables.Add(table)
        return TableInfo(name=table_name, columns=())

    def create_measure(
        self,
        table_name: str,
        measure_name: str,
        dax_expression: str,
        format_string: str | None,
    ) -> MeasureInfo:
        from Microsoft.AnalysisServices.Tabular import Measure  # type: ignore[import-not-found]

        table = self._find_table(table_name)
        measure = Measure()
        measure.Name = measure_name
        measure.Expression = dax_expression
        if format_string:
            measure.FormatString = format_string
        table.Measures.Add(measure)
        return MeasureInfo(
            table_name=table_name,
            name=measure_name,
            dax_expression=dax_expression,
            format_string=format_string,
        )

    def create_relationship(
        self,
        from_table: str,
        from_column: str,
        to_table: str,
        to_column: str,
        cardinality: str,
        cross_filter_direction: str,
    ) -> RelationshipInfo:
        from Microsoft.AnalysisServices.Tabular import (  # type: ignore[import-not-found]
            CrossFilteringBehavior,
            RelationshipEndCardinality,
            SingleColumnRelationship,
        )

        model = self._model()
        from_tbl = self._find_table(from_table)
        to_tbl = self._find_table(to_table)
        from_col = self._find_column(from_tbl, from_column)
        to_col = self._find_column(to_tbl, to_column)

        cardinality_to_tom = {
            "many_to_one": (RelationshipEndCardinality.Many, RelationshipEndCardinality.One),
            "one_to_one": (RelationshipEndCardinality.One, RelationshipEndCardinality.One),
            "one_to_many": (RelationshipEndCardinality.One, RelationshipEndCardinality.Many),
        }
        from_card, to_card = cardinality_to_tom.get(
            cardinality, (RelationshipEndCardinality.Many, RelationshipEndCardinality.One)
        )

        relationship = SingleColumnRelationship()
        relationship.FromColumn = from_col
        relationship.ToColumn = to_col
        relationship.FromCardinality = from_card
        relationship.ToCardinality = to_card
        relationship.CrossFilteringBehavior = (
            CrossFilteringBehavior.BothDirections
            if cross_filter_direction == "both"
            else CrossFilteringBehavior.OneDirection
        )
        model.Relationships.Add(relationship)
        return RelationshipInfo(
            from_table=from_table,
            from_column=from_column,
            to_table=to_table,
            to_column=to_column,
            cardinality=cardinality,
            cross_filter_direction=cross_filter_direction,
        )

    def delete_table(self, table_name: str) -> None:
        model = self._model()
        table = self._find_table(table_name)
        model.Tables.Remove(table)

    def delete_measure(self, table_name: str, measure_name: str) -> None:
        table = self._find_table(table_name)
        measure = self._find_measure(table, measure_name)
        table.Measures.Remove(measure)

    def update_measure(
        self,
        table_name: str,
        measure_name: str,
        dax_expression: str | None,
        format_string: str | None,
    ) -> MeasureInfo:
        table = self._find_table(table_name)
        measure = self._find_measure(table, measure_name)
        if dax_expression is not None:
            measure.Expression = dax_expression
        if format_string is not None:
            measure.FormatString = format_string
        return MeasureInfo(
            table_name=table_name,
            name=measure_name,
            dax_expression=measure.Expression,
            format_string=measure.FormatString or None,
        )

    def delete_relationship(
        self, from_table: str, from_column: str, to_table: str, to_column: str
    ) -> None:
        model = self._model()
        relationship = self._find_relationship(model, from_table, from_column, to_table, to_column)
        model.Relationships.Remove(relationship)

    def create_calculated_column(
        self,
        table_name: str,
        column_name: str,
        dax_expression: str,
        format_string: str | None,
    ) -> ColumnInfo:
        from Microsoft.AnalysisServices.Tabular import CalculatedColumn  # type: ignore[import-not-found]

        table = self._find_table(table_name)
        column = CalculatedColumn()
        column.Name = column_name
        column.Expression = dax_expression
        if format_string:
            column.FormatString = format_string
        table.Columns.Add(column)
        return ColumnInfo(name=column_name, data_type=str(column.DataType))

    def delete_column(self, table_name: str, column_name: str) -> None:
        table = self._find_table(table_name)
        column = self._find_column(table, column_name)
        table.Columns.Remove(column)

    def create_hierarchy(
        self, table_name: str, hierarchy_name: str, levels: list[str]
    ) -> HierarchyInfo:
        from Microsoft.AnalysisServices.Tabular import Hierarchy, Level  # type: ignore[import-not-found]

        table = self._find_table(table_name)
        hierarchy = Hierarchy()
        hierarchy.Name = hierarchy_name
        for ordinal, column_name in enumerate(levels):
            column = self._find_column(table, column_name)
            level = Level()
            level.Column = column
            level.Ordinal = ordinal
            level.Name = column_name
            hierarchy.Levels.Add(level)
        table.Hierarchies.Add(hierarchy)
        return HierarchyInfo(table_name=table_name, name=hierarchy_name, levels=tuple(levels))

    def delete_hierarchy(self, table_name: str, hierarchy_name: str) -> None:
        table = self._find_table(table_name)
        hierarchy = self._find_hierarchy(table, hierarchy_name)
        table.Hierarchies.Remove(hierarchy)

    def list_hierarchies(self) -> tuple[HierarchyInfo, ...]:
        self.refresh_metadata()
        hierarchies = []
        for table in self._model().Tables:
            for hierarchy in table.Hierarchies:
                ordered_levels = sorted(hierarchy.Levels, key=lambda lv: lv.Ordinal)
                hierarchies.append(
                    HierarchyInfo(
                        table_name=table.Name,
                        name=hierarchy.Name,
                        levels=tuple(level.Column.Name for level in ordered_levels),
                    )
                )
        return tuple(hierarchies)

    def create_role(self, role_name: str) -> RoleInfo:
        from Microsoft.AnalysisServices.Tabular import (  # type: ignore[import-not-found]
            ModelPermission,
            ModelRole,
        )

        role = ModelRole()
        role.Name = role_name
        role.ModelPermission = ModelPermission.Read
        self._model().Roles.Add(role)
        return RoleInfo(name=role_name, table_permissions=())

    def add_table_permission(
        self, role_name: str, table_name: str, filter_expression: str
    ) -> RoleInfo:
        from Microsoft.AnalysisServices.Tabular import TablePermission  # type: ignore[import-not-found]

        role = self._find_role(role_name)
        table = self._find_table(table_name)
        permission = TablePermission()
        permission.Table = table
        permission.FilterExpression = filter_expression
        role.TablePermissions.Add(permission)
        return self._role_info(role)

    def delete_role(self, role_name: str) -> None:
        role = self._find_role(role_name)
        self._model().Roles.Remove(role)

    def list_roles(self) -> tuple[RoleInfo, ...]:
        self.refresh_metadata()
        return tuple(self._role_info(role) for role in self._model().Roles)

    def hide_column(self, role_name: str, table_name: str, column_name: str) -> RoleInfo:
        from Microsoft.AnalysisServices.Tabular import ColumnPermission, MetadataPermission  # type: ignore[import-not-found]

        role = self._find_role(role_name)
        table_permission = self._find_table_permission(role, table_name)
        column = self._find_column(table_permission.Table, column_name)
        permission = ColumnPermission()
        permission.Column = column
        # "None" é o nome real do membro do enum -- getattr porque
        # `None` é palavra reservada em Python, não pode ser atributo.
        permission.MetadataPermission = getattr(MetadataPermission, "None")
        table_permission.ColumnPermissions.Add(permission)
        return self._role_info(role)

    def unhide_column(self, role_name: str, table_name: str, column_name: str) -> RoleInfo:
        role = self._find_role(role_name)
        table_permission = self._find_table_permission(role, table_name)
        permission = self._find_column_permission(table_permission, column_name)
        table_permission.ColumnPermissions.Remove(permission)
        return self._role_info(role)

    def _role_info(self, role: object) -> RoleInfo:
        permissions = tuple(
            TablePermissionInfo(
                table_name=p.Table.Name,
                filter_expression=p.FilterExpression,
                hidden_columns=tuple(
                    cp.Column.Name
                    for cp in p.ColumnPermissions
                    if str(cp.MetadataPermission) == "None"
                ),
            )
            for p in role.TablePermissions  # type: ignore[attr-defined]
        )
        return RoleInfo(name=role.Name, table_permissions=permissions)  # type: ignore[attr-defined]

    def _live_ports(self) -> tuple[int, ...]:
        """Portas de instâncias do Desktop abertas agora, pra enriquecer
        a mensagem de StaleConnectionError -- lê só arquivos
        (modeling/discovery.py), custo zero de rede/XMLA. Melhor
        esforço: se a descoberta falhar por qualquer razão, não
        atrapalha o erro original."""
        try:
            from modeling.discovery import find_desktop_instances

            return tuple(instance.port for instance in find_desktop_instances())
        except Exception:
            return ()

    def refresh_table(self, table_name: str) -> None:
        from Microsoft.AnalysisServices.Tabular import RefreshType  # type: ignore[import-not-found]

        table = self._find_table(table_name)
        with wrap_dotnet_errors("refresh_table", self._live_ports):
            table.RequestRefresh(RefreshType.Full)
            self._model().SaveChanges()

    def refresh_model(self) -> None:
        from Microsoft.AnalysisServices.Tabular import RefreshType  # type: ignore[import-not-found]

        with wrap_dotnet_errors("refresh_model", self._live_ports):
            for table in self._model().Tables:
                table.RequestRefresh(RefreshType.Full)
            self._model().SaveChanges()

    def set_table_description(self, table_name: str, description: str) -> None:
        table = self._find_table(table_name)
        table.Description = description

    def set_column_metadata(
        self,
        table_name: str,
        column_name: str,
        description: str | None,
        display_folder: str | None,
    ) -> None:
        table = self._find_table(table_name)
        column = self._find_column(table, column_name)
        if description is not None:
            column.Description = description
        if display_folder is not None:
            column.DisplayFolder = display_folder

    def set_measure_metadata(
        self,
        table_name: str,
        measure_name: str,
        description: str | None,
        display_folder: str | None,
    ) -> None:
        table = self._find_table(table_name)
        measure = self._find_measure(table, measure_name)
        if description is not None:
            measure.Description = description
        if display_folder is not None:
            measure.DisplayFolder = display_folder

    def set_column_sort_by(
        self, table_name: str, column_name: str, sort_by_column: str | None
    ) -> None:
        table = self._find_table(table_name)
        column = self._find_column(table, column_name)
        if sort_by_column is None:
            column.SortByColumn = None
        else:
            column.SortByColumn = self._find_column(table, sort_by_column)

    def set_column_format(
        self,
        table_name: str,
        column_name: str,
        format_string: str | None,
        data_category: str | None,
    ) -> None:
        table = self._find_table(table_name)
        column = self._find_column(table, column_name)
        if format_string is not None:
            column.FormatString = format_string
        if data_category is not None:
            column.DataCategory = data_category

    def set_column_visibility(self, table_name: str, column_name: str, is_hidden: bool) -> None:
        table = self._find_table(table_name)
        column = self._find_column(table, column_name)
        column.IsHidden = is_hidden

    def set_column_related_column(
        self, table_name: str, column_name: str, grouping_column_name: str
    ) -> None:
        from Microsoft.AnalysisServices.Tabular import (  # type: ignore[import-not-found]
            GroupByColumn,
            RelatedColumnDetails,
        )

        table = self._find_table(table_name)
        column = self._find_column(table, column_name)
        grouping_column = self._find_column(table, grouping_column_name)

        related = RelatedColumnDetails()
        group_by_column = GroupByColumn()
        group_by_column.GroupingColumn = grouping_column
        related.GroupByColumns.Add(group_by_column)
        column.RelatedColumnDetails = related

    def set_column_extended_property(
        self, table_name: str, column_name: str, property_name: str, json_value: str
    ) -> None:
        from Microsoft.AnalysisServices.Tabular import JsonExtendedProperty  # type: ignore[import-not-found]

        table = self._find_table(table_name)
        column = self._find_column(table, column_name)

        prop = JsonExtendedProperty()
        prop.Name = property_name
        prop.Value = json_value
        column.ExtendedProperties.Add(prop)

    # --- calculation groups -------------------------------------------
    #
    # Estrutura conforme a doc oficial ("Calculation groups in Analysis
    # Services tabular models" -- TMSL de exemplo): tabela com
    # `CalculationGroup` (precedence + calculationItems), uma coluna de
    # texto com `sourceColumn: "Name"` ordenada (sortByColumn) por uma
    # coluna oculta int64 com `sourceColumn: "Ordinal"`, e uma partição
    # `mode: import` com `source.type: calculationGroup`. Tipos e enums
    # (CalculationGroup, CalculationItem, FormatStringDefinition,
    # CalculationGroupSource, DataColumn.SourceColumn/SummarizeBy,
    # AggregateFunction.None/Sum, DataType.String/Int64, ModeType.Import,
    # Model.DiscourageImplicitMeasures) confirmados por reflexão .NET.

    def get_discourage_implicit_measures(self) -> bool:
        self.refresh_metadata()
        return bool(self._model().DiscourageImplicitMeasures)

    def set_discourage_implicit_measures(self, value: bool) -> None:
        self._model().DiscourageImplicitMeasures = value

    def create_calculation_group(
        self,
        table_name: str,
        column_name: str,
        precedence: int,
        items: tuple[CalculationItemInfo, ...],
    ) -> CalculationGroupInfo:
        from Microsoft.AnalysisServices.Tabular import (  # type: ignore[import-not-found]
            AggregateFunction,
            CalculationGroup,
            CalculationGroupSource,
            DataColumn,
            DataType,
            ModeType,
            Partition,
            Table,
        )

        table = Table()
        table.Name = table_name
        group = CalculationGroup()
        group.Precedence = precedence
        table.CalculationGroup = group

        name_column = DataColumn()
        name_column.Name = column_name
        name_column.DataType = DataType.String
        name_column.SourceColumn = "Name"
        name_column.SummarizeBy = getattr(AggregateFunction, "None")  # "None" é palavra reservada
        ordinal_column = DataColumn()
        ordinal_column.Name = "Ordinal"
        ordinal_column.DataType = DataType.Int64
        ordinal_column.SourceColumn = "Ordinal"
        ordinal_column.IsHidden = True
        ordinal_column.FormatString = "0"
        ordinal_column.SummarizeBy = AggregateFunction.Sum
        table.Columns.Add(name_column)
        table.Columns.Add(ordinal_column)
        name_column.SortByColumn = ordinal_column

        for item in items:
            group.CalculationItems.Add(self._new_calculation_item(item))

        partition = Partition()
        partition.Name = table_name
        partition.Mode = ModeType.Import
        partition.Source = CalculationGroupSource()
        table.Partitions.Add(partition)

        self._model().Tables.Add(table)
        return CalculationGroupInfo(
            table_name=table_name, column_name=column_name, precedence=precedence, items=items
        )

    # --- perspectivas ---------------------------------------------------
    #
    # Reflexão .NET (2026-09-29): Model.Perspectives -> Perspective(Name,
    # Description, PerspectiveTables) -> PerspectiveTable(Table,
    # IncludeAll, PerspectiveColumns/Measures/Hierarchies) ->
    # PerspectiveColumn(Column) / PerspectiveMeasure(Measure) /
    # PerspectiveHierarchy(Hierarchy). Sonda ao vivo: setar a referência
    # (Table/Column/Measure) já preenche o Name.

    def create_perspective(self, perspective: PerspectiveInfo) -> None:
        from Microsoft.AnalysisServices.Tabular import (  # type: ignore[import-not-found]
            Perspective,
            PerspectiveColumn,
            PerspectiveHierarchy,
            PerspectiveMeasure,
            PerspectiveTable,
        )

        new = Perspective()
        new.Name = perspective.name
        if perspective.description:
            new.Description = perspective.description
        for spec in perspective.tables:
            table = self._find_table(spec.table_name)
            perspective_table = PerspectiveTable()
            perspective_table.Table = table
            perspective_table.IncludeAll = spec.include_all
            for column_name in spec.columns:
                item = PerspectiveColumn()
                item.Column = self._find_column(table, column_name)
                perspective_table.PerspectiveColumns.Add(item)
            for measure_name in spec.measures:
                item = PerspectiveMeasure()
                item.Measure = self._find_measure(table, measure_name)
                perspective_table.PerspectiveMeasures.Add(item)
            for hierarchy_name in spec.hierarchies:
                item = PerspectiveHierarchy()
                item.Hierarchy = self._find_hierarchy(table, hierarchy_name)
                perspective_table.PerspectiveHierarchies.Add(item)
            new.PerspectiveTables.Add(perspective_table)
        self._model().Perspectives.Add(new)

    def delete_perspective(self, name: str) -> None:
        model = self._model()
        for perspective in model.Perspectives:
            if perspective.Name == name:
                model.Perspectives.Remove(perspective)
                return
        raise ModelObjectNotFoundError("perspectiva", name, known=[p.Name for p in model.Perspectives])

    def list_perspectives(self) -> tuple[PerspectiveInfo, ...]:
        self.refresh_metadata()
        return tuple(
            PerspectiveInfo(
                name=p.Name,
                description=p.Description or None,
                tables=tuple(
                    PerspectiveTableInfo(
                        table_name=pt.Table.Name,
                        include_all=bool(pt.IncludeAll),
                        columns=tuple(c.Column.Name for c in pt.PerspectiveColumns),
                        measures=tuple(m.Measure.Name for m in pt.PerspectiveMeasures),
                        hierarchies=tuple(h.Hierarchy.Name for h in pt.PerspectiveHierarchies),
                    )
                    for pt in p.PerspectiveTables
                ),
            )
            for p in self._model().Perspectives
        )

    def add_calculation_item(self, table_name: str, item: CalculationItemInfo) -> None:
        group = self._find_calculation_group(table_name)
        group.CalculationItems.Add(self._new_calculation_item(item))

    def delete_calculation_item(self, table_name: str, item_name: str) -> None:
        group = self._find_calculation_group(table_name)
        for item in group.CalculationItems:
            if item.Name == item_name:
                group.CalculationItems.Remove(item)
                return
        raise ModelObjectNotFoundError(
            "item de calculation group", item_name,
            known=[i.Name for i in group.CalculationItems], parent=table_name,
        )

    def list_calculation_groups(self) -> tuple[CalculationGroupInfo, ...]:
        self.refresh_metadata()
        groups = []
        for table in self._model().Tables:
            group = table.CalculationGroup
            if group is None:
                continue
            column_name = next(
                (c.Name for c in table.Columns if getattr(c, "SourceColumn", None) == "Name"),
                table.Name,
            )
            items = tuple(
                CalculationItemInfo(
                    name=i.Name,
                    expression=i.Expression,
                    ordinal=int(i.Ordinal),
                    format_string_expression=(
                        i.FormatStringDefinition.Expression
                        if i.FormatStringDefinition is not None
                        else None
                    ),
                )
                for i in sorted(group.CalculationItems, key=lambda i: i.Ordinal)
            )
            groups.append(
                CalculationGroupInfo(
                    table_name=table.Name,
                    column_name=column_name,
                    precedence=int(group.Precedence),
                    items=items,
                )
            )
        return tuple(groups)

    def _find_calculation_group(self, table_name: str):
        table = self._find_table(table_name)
        if table.CalculationGroup is None:
            raise ModelObjectNotFoundError(
                "calculation group", table_name,
                known=[t.Name for t in self._model().Tables if t.CalculationGroup is not None],
            )
        return table.CalculationGroup

    @staticmethod
    def _new_calculation_item(item: CalculationItemInfo):
        from Microsoft.AnalysisServices.Tabular import (  # type: ignore[import-not-found]
            CalculationItem,
            FormatStringDefinition,
        )

        calculation_item = CalculationItem()
        calculation_item.Name = item.name
        calculation_item.Expression = item.expression
        calculation_item.Ordinal = item.ordinal
        if item.format_string_expression:
            definition = FormatStringDefinition()
            definition.Expression = item.format_string_expression
            calculation_item.FormatStringDefinition = definition
        return calculation_item

    def save_changes(self) -> None:
        with wrap_dotnet_errors("save_changes", self._live_ports):
            self._model().SaveChanges()

    def disconnect(self) -> None:
        self._server.Disconnect()  # type: ignore[attr-defined]
