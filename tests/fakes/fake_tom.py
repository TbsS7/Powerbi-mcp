"""Fake do TomRuntime Protocol: um grafo de objetos em memória que
espelha a superfície do TOM real (Server > Database > Model >
Tables/Measures/Relationships + SaveChanges), usado para testar toda a
camada de modelagem sem Power BI Desktop nem pythonnet.

Além de imitar o comportamento, registra cada chamada em `.calls` --
usado pelo teste de aceitação (Fase 4) para confirmar que as operações
de modelagem chegaram na ordem certa antes de qualquer arquivo PBIR ser
escrito.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modeling.metadata import (
    CalculationGroupInfo,
    CalculationItemInfo,
    ColumnDetail,
    ColumnInfo,
    HierarchyInfo,
    MeasureDetail,
    MeasureInfo,
    PerspectiveInfo,
    ModelDetails,
    RelationshipInfo,
    RoleInfo,
    TableDetail,
    TableInfo,
    TablePermissionInfo,
)


@dataclass
class _FakeTable:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    hierarchies: list[HierarchyInfo] = field(default_factory=list)


@dataclass
class _FakeRole:
    name: str
    table_permissions: list[TablePermissionInfo] = field(default_factory=list)


def _infer_row_constructor_columns(dax_expression: str) -> list[ColumnInfo]:
    """Se `dax_expression` for um construtor de tupla sem nome de coluna
    (`{("a", NAMEOF(...), 0), ...}`), devolve as colunas `Value1..N` que
    o DAX gera automaticamente pra esse padrão -- senão, lista vazia
    (mesmo comportamento de antes: tabela sem coluna nenhuma até algo
    popular via add_table). Não é um parser de DAX de verdade -- só
    conta os elementos de nível 1 da primeira tupla, o suficiente pro
    único padrão que este projeto gera (field parameters)."""
    stripped = dax_expression.strip()
    if not stripped.startswith("{(") or ")" not in stripped:
        return []

    start = stripped.index("(")
    depth = 0
    end = None
    for i in range(start, len(stripped)):
        if stripped[i] == "(":
            depth += 1
        elif stripped[i] == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return []

    row = stripped[start + 1 : end]
    depth = 0
    element_count = 1
    for ch in row:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            element_count += 1
    return [ColumnInfo(name=f"Value{i}", data_type="String") for i in range(1, element_count + 1)]


class FakeTomRuntime:
    """Implementação em memória de modeling.tom_runtime.TomRuntime.

    `port`, `database_name` e `compatibility_level` são fixados na
    construção, como se já tivessem vindo de uma conexão bem-sucedida --
    a lógica de descoberta/conexão (discovery.py, tom_runtime.connect)
    não faz parte deste fake, que representa só o estado do modelo já
    conectado.
    """

    def __init__(
        self,
        database_name: str = "FakeDatabase",
        port: int = 51999,
        compatibility_level: int = 1600,
        tables: list[TableInfo] | None = None,
    ) -> None:
        self._port = port
        self._database_name = database_name
        self._compatibility_level = compatibility_level
        self._tables: dict[str, _FakeTable] = {}
        self._measures: list[MeasureInfo] = []
        self._relationships: list[RelationshipInfo] = []
        self._roles: dict[str, _FakeRole] = {}
        self.calls: list[tuple[str, dict]] = []
        self.save_changes_count = 0
        # Estado das propriedades "de documentação" -- guardado pelos
        # setters (set_table_description, set_column_*, ...) e lido por
        # list_model_details, pra auditoria (modeling.audit).
        self._table_meta: dict[str, dict] = {}
        self._column_meta: dict[tuple[str, str], dict] = {}
        self._measure_meta: dict[tuple[str, str], dict] = {}
        # calculation groups: table_name -> CalculationGroupInfo
        self._calculation_groups: dict[str, CalculationGroupInfo] = {}
        self._perspectives: dict[str, PerspectiveInfo] = {}
        self.discourage_implicit_measures = False

        for table in tables or []:
            self._tables[table.name] = _FakeTable(name=table.name, columns=list(table.columns))

    def written_calls(self) -> list[tuple[str, dict]]:
        """`.calls` sem as entradas automáticas de `refresh_metadata` --
        inseridas antes de cada leitura desde que TomRuntime passou a
        ressincronizar o modelo (`Model.Sync()`, ver
        `_PythonnetTomRuntime.refresh_metadata`). Use no lugar de
        indexar `.calls` direto quando o teste quer conferir só as
        chamadas "de negócio" (escrita, ou leitura explícita)."""
        return [c for c in self.calls if c[0] != "refresh_metadata"]

    # --- propriedades de conexão ------------------------------------

    @property
    def port(self) -> int:
        return self._port

    @property
    def database_name(self) -> str:
        return self._database_name

    @property
    def compatibility_level(self) -> int:
        return self._compatibility_level

    # --- leitura ------------------------------------------------------

    def refresh_metadata(self) -> None:
        # O fake não tem estado "obsoleto" pra ressincronizar (é um
        # único dict em memória, sempre atual) -- só registra a chamada,
        # pra testes confirmarem que os métodos de leitura chamam isto
        # antes de ler, igual o runtime real faz com Model.Sync().
        self.calls.append(("refresh_metadata", {}))

    def list_tables(self) -> tuple[TableInfo, ...]:
        self.refresh_metadata()
        return tuple(
            TableInfo(name=t.name, columns=tuple(t.columns)) for t in self._tables.values()
        )

    def list_measures(self) -> tuple[MeasureInfo, ...]:
        self.refresh_metadata()
        return tuple(self._measures)

    def list_relationships(self) -> tuple[RelationshipInfo, ...]:
        self.refresh_metadata()
        return tuple(self._relationships)

    def list_model_details(self) -> ModelDetails:
        self.refresh_metadata()
        tables = tuple(
            TableDetail(
                name=t.name,
                description=self._table_meta.get(t.name, {}).get("description"),
                is_hidden=False,
                columns=tuple(
                    ColumnDetail(
                        name=c.name,
                        data_type=c.data_type,
                        description=self._col(t.name, c.name).get("description"),
                        is_hidden=self._col(t.name, c.name).get("is_hidden", False),
                        display_folder=self._col(t.name, c.name).get("display_folder"),
                        sort_by_column=self._col(t.name, c.name).get("sort_by_column"),
                        extended_properties=tuple(
                            self._col(t.name, c.name).get("extended_properties", ())
                        ),
                    )
                    for c in t.columns
                ),
            )
            for t in self._tables.values()
        )
        measures = tuple(
            MeasureDetail(
                table_name=m.table_name,
                name=m.name,
                dax_expression=m.dax_expression,
                format_string=m.format_string,
                description=self._measure_meta.get((m.table_name, m.name), {}).get("description"),
                display_folder=self._measure_meta.get((m.table_name, m.name), {}).get("display_folder"),
            )
            for m in self._measures
        )
        return ModelDetails(tables=tables, measures=measures)

    def _col(self, table_name: str, column_name: str) -> dict:
        return self._column_meta.setdefault((table_name, column_name), {})

    # --- escrita --------------------------------------------------------

    def create_calculated_table(self, table_name: str, dax_expression: str) -> TableInfo:
        self.calls.append(
            ("create_calculated_table", {"table_name": table_name, "dax_expression": dax_expression})
        )
        # O TOM real só descobre as colunas de uma tabela calculada ao
        # processar a expressão (o que exige um save) -- fora do caso
        # especial abaixo (construtor de tupla sem nome de coluna, ex:
        # `{("a", 1, 0), ...}`, usado por field parameters), onde os
        # nomes "Value1"/"Value2".../"ValueN" são previsíveis pela
        # própria regra do DAX (confirmado ao vivo via evaluate_dax
        # nesta sessão: `EVALUATE {[Medida]}` devolveu coluna "Value").
        # Inferir aqui, de cara, evita ter que simular o save() só pra
        # popular colunas -- não é um TOM de verdade, só o suficiente
        # pra testar a lógica de quem chama.
        columns = _infer_row_constructor_columns(dax_expression)
        table = _FakeTable(name=table_name, columns=columns)
        self._tables[table_name] = table
        return TableInfo(name=table.name, columns=tuple(columns))

    def create_measure(
        self,
        table_name: str,
        measure_name: str,
        dax_expression: str,
        format_string: str | None,
    ) -> MeasureInfo:
        self.calls.append(
            (
                "create_measure",
                {
                    "table_name": table_name,
                    "measure_name": measure_name,
                    "dax_expression": dax_expression,
                    "format_string": format_string,
                },
            )
        )
        measure = MeasureInfo(
            table_name=table_name,
            name=measure_name,
            dax_expression=dax_expression,
            format_string=format_string,
        )
        self._measures.append(measure)
        return measure

    def create_relationship(
        self,
        from_table: str,
        from_column: str,
        to_table: str,
        to_column: str,
        cardinality: str,
        cross_filter_direction: str,
    ) -> RelationshipInfo:
        self.calls.append(
            (
                "create_relationship",
                {
                    "from_table": from_table,
                    "from_column": from_column,
                    "to_table": to_table,
                    "to_column": to_column,
                    "cardinality": cardinality,
                    "cross_filter_direction": cross_filter_direction,
                },
            )
        )
        relationship = RelationshipInfo(
            from_table=from_table,
            from_column=from_column,
            to_table=to_table,
            to_column=to_column,
            cardinality=cardinality,
            cross_filter_direction=cross_filter_direction,
        )
        self._relationships.append(relationship)
        return relationship

    # --- remoção / atualização -----------------------------------------

    def delete_table(self, table_name: str) -> None:
        self.calls.append(("delete_table", {"table_name": table_name}))
        del self._tables[table_name]

    def delete_measure(self, table_name: str, measure_name: str) -> None:
        self.calls.append(
            ("delete_measure", {"table_name": table_name, "measure_name": measure_name})
        )
        self._measures = [
            m for m in self._measures if not (m.table_name == table_name and m.name == measure_name)
        ]

    def update_measure(
        self,
        table_name: str,
        measure_name: str,
        dax_expression: str | None,
        format_string: str | None,
    ) -> MeasureInfo:
        self.calls.append(
            (
                "update_measure",
                {
                    "table_name": table_name,
                    "measure_name": measure_name,
                    "dax_expression": dax_expression,
                    "format_string": format_string,
                },
            )
        )
        index, existing = next(
            (i, m)
            for i, m in enumerate(self._measures)
            if m.table_name == table_name and m.name == measure_name
        )
        updated = MeasureInfo(
            table_name=table_name,
            name=measure_name,
            dax_expression=dax_expression if dax_expression is not None else existing.dax_expression,
            format_string=format_string if format_string is not None else existing.format_string,
        )
        self._measures[index] = updated
        return updated

    def delete_relationship(
        self, from_table: str, from_column: str, to_table: str, to_column: str
    ) -> None:
        self.calls.append(
            (
                "delete_relationship",
                {
                    "from_table": from_table,
                    "from_column": from_column,
                    "to_table": to_table,
                    "to_column": to_column,
                },
            )
        )
        self._relationships = [
            r
            for r in self._relationships
            if not (
                r.from_table == from_table
                and r.from_column == from_column
                and r.to_table == to_table
                and r.to_column == to_column
            )
        ]

    def create_calculated_column(
        self,
        table_name: str,
        column_name: str,
        dax_expression: str,
        format_string: str | None,
    ) -> ColumnInfo:
        self.calls.append(
            (
                "create_calculated_column",
                {
                    "table_name": table_name,
                    "column_name": column_name,
                    "dax_expression": dax_expression,
                    "format_string": format_string,
                },
            )
        )
        # O TOM real infere o data_type avaliando a expressão DAX -- este
        # fake não pode fazer isso sem um motor DAX, então usa "Double"
        # como padrão (a maioria das colunas calculadas é numérica).
        column = ColumnInfo(name=column_name, data_type="Double")
        self._tables[table_name].columns.append(column)
        return column

    def delete_column(self, table_name: str, column_name: str) -> None:
        self.calls.append(
            ("delete_column", {"table_name": table_name, "column_name": column_name})
        )
        table = self._tables[table_name]
        table.columns = [c for c in table.columns if c.name != column_name]

    def create_hierarchy(
        self, table_name: str, hierarchy_name: str, levels: list[str]
    ) -> HierarchyInfo:
        self.calls.append(
            ("create_hierarchy", {"table_name": table_name, "hierarchy_name": hierarchy_name, "levels": levels})
        )
        hierarchy = HierarchyInfo(table_name=table_name, name=hierarchy_name, levels=tuple(levels))
        self._tables[table_name].hierarchies.append(hierarchy)
        return hierarchy

    def delete_hierarchy(self, table_name: str, hierarchy_name: str) -> None:
        self.calls.append(
            ("delete_hierarchy", {"table_name": table_name, "hierarchy_name": hierarchy_name})
        )
        table = self._tables[table_name]
        table.hierarchies = [h for h in table.hierarchies if h.name != hierarchy_name]

    def list_hierarchies(self) -> tuple[HierarchyInfo, ...]:
        self.refresh_metadata()
        return tuple(h for t in self._tables.values() for h in t.hierarchies)

    def create_role(self, role_name: str) -> RoleInfo:
        self.calls.append(("create_role", {"role_name": role_name}))
        self._roles[role_name] = _FakeRole(name=role_name)
        return RoleInfo(name=role_name, table_permissions=())

    def add_table_permission(
        self, role_name: str, table_name: str, filter_expression: str
    ) -> RoleInfo:
        self.calls.append(
            (
                "add_table_permission",
                {"role_name": role_name, "table_name": table_name, "filter_expression": filter_expression},
            )
        )
        role = self._roles[role_name]
        role.table_permissions.append(
            TablePermissionInfo(table_name=table_name, filter_expression=filter_expression)
        )
        return RoleInfo(name=role_name, table_permissions=tuple(role.table_permissions))

    def delete_role(self, role_name: str) -> None:
        self.calls.append(("delete_role", {"role_name": role_name}))
        del self._roles[role_name]

    def list_roles(self) -> tuple[RoleInfo, ...]:
        self.refresh_metadata()
        return tuple(
            RoleInfo(name=r.name, table_permissions=tuple(r.table_permissions))
            for r in self._roles.values()
        )

    def hide_column(self, role_name: str, table_name: str, column_name: str) -> RoleInfo:
        self.calls.append(
            ("hide_column", {"role_name": role_name, "table_name": table_name, "column_name": column_name})
        )
        role = self._roles[role_name]
        index, existing = next(
            (i, p) for i, p in enumerate(role.table_permissions) if p.table_name == table_name
        )
        role.table_permissions[index] = TablePermissionInfo(
            table_name=table_name,
            filter_expression=existing.filter_expression,
            hidden_columns=tuple(existing.hidden_columns) + (column_name,),
        )
        return RoleInfo(name=role_name, table_permissions=tuple(role.table_permissions))

    def unhide_column(self, role_name: str, table_name: str, column_name: str) -> RoleInfo:
        self.calls.append(
            ("unhide_column", {"role_name": role_name, "table_name": table_name, "column_name": column_name})
        )
        role = self._roles[role_name]
        index, existing = next(
            (i, p) for i, p in enumerate(role.table_permissions) if p.table_name == table_name
        )
        role.table_permissions[index] = TablePermissionInfo(
            table_name=table_name,
            filter_expression=existing.filter_expression,
            hidden_columns=tuple(c for c in existing.hidden_columns if c != column_name),
        )
        return RoleInfo(name=role_name, table_permissions=tuple(role.table_permissions))

    def refresh_table(self, table_name: str) -> None:
        self.calls.append(("refresh_table", {"table_name": table_name}))

    def refresh_model(self) -> None:
        self.calls.append(("refresh_model", {}))

    def set_table_description(self, table_name: str, description: str) -> None:
        self.calls.append(
            ("set_table_description", {"table_name": table_name, "description": description})
        )
        self._table_meta.setdefault(table_name, {})["description"] = description

    def set_column_metadata(
        self,
        table_name: str,
        column_name: str,
        description: str | None,
        display_folder: str | None,
    ) -> None:
        self.calls.append(
            (
                "set_column_metadata",
                {
                    "table_name": table_name, "column_name": column_name,
                    "description": description, "display_folder": display_folder,
                },
            )
        )
        meta = self._col(table_name, column_name)
        if description is not None:
            meta["description"] = description
        if display_folder is not None:
            meta["display_folder"] = display_folder

    def set_measure_metadata(
        self,
        table_name: str,
        measure_name: str,
        description: str | None,
        display_folder: str | None,
    ) -> None:
        self.calls.append(
            (
                "set_measure_metadata",
                {
                    "table_name": table_name, "measure_name": measure_name,
                    "description": description, "display_folder": display_folder,
                },
            )
        )
        meta = self._measure_meta.setdefault((table_name, measure_name), {})
        if description is not None:
            meta["description"] = description
        if display_folder is not None:
            meta["display_folder"] = display_folder

    def set_column_sort_by(
        self, table_name: str, column_name: str, sort_by_column: str | None
    ) -> None:
        self.calls.append(
            (
                "set_column_sort_by",
                {
                    "table_name": table_name, "column_name": column_name,
                    "sort_by_column": sort_by_column,
                },
            )
        )
        self._col(table_name, column_name)["sort_by_column"] = sort_by_column

    def set_column_format(
        self,
        table_name: str,
        column_name: str,
        format_string: str | None,
        data_category: str | None,
    ) -> None:
        self.calls.append(
            (
                "set_column_format",
                {
                    "table_name": table_name, "column_name": column_name,
                    "format_string": format_string, "data_category": data_category,
                },
            )
        )

    def set_column_visibility(self, table_name: str, column_name: str, is_hidden: bool) -> None:
        self.calls.append(
            (
                "set_column_visibility",
                {"table_name": table_name, "column_name": column_name, "is_hidden": is_hidden},
            )
        )
        self._col(table_name, column_name)["is_hidden"] = is_hidden

    def set_column_related_column(
        self, table_name: str, column_name: str, grouping_column_name: str
    ) -> None:
        self.calls.append(
            (
                "set_column_related_column",
                {
                    "table_name": table_name, "column_name": column_name,
                    "grouping_column_name": grouping_column_name,
                },
            )
        )

    def set_column_extended_property(
        self, table_name: str, column_name: str, property_name: str, json_value: str
    ) -> None:
        self.calls.append(
            (
                "set_column_extended_property",
                {
                    "table_name": table_name, "column_name": column_name,
                    "property_name": property_name, "json_value": json_value,
                },
            )
        )
        self._col(table_name, column_name).setdefault("extended_properties", []).append(property_name)

    # --- calculation groups --------------------------------------------

    def get_discourage_implicit_measures(self) -> bool:
        self.refresh_metadata()
        return self.discourage_implicit_measures

    def set_discourage_implicit_measures(self, value: bool) -> None:
        self.calls.append(("set_discourage_implicit_measures", {"value": value}))
        self.discourage_implicit_measures = value

    def create_calculation_group(
        self,
        table_name: str,
        column_name: str,
        precedence: int,
        items: tuple[CalculationItemInfo, ...],
    ) -> CalculationGroupInfo:
        self.calls.append(
            (
                "create_calculation_group",
                {
                    "table_name": table_name, "column_name": column_name,
                    "precedence": precedence, "items": tuple(items),
                },
            )
        )
        # Mesmas duas colunas que o runtime real cria (doc oficial):
        # nome (texto) + Ordinal (int64, oculta, alvo do sort-by).
        self._tables[table_name] = _FakeTable(
            name=table_name,
            columns=[ColumnInfo(name=column_name, data_type="String"), ColumnInfo(name="Ordinal", data_type="Int64")],
        )
        group = CalculationGroupInfo(
            table_name=table_name, column_name=column_name, precedence=precedence, items=tuple(items)
        )
        self._calculation_groups[table_name] = group
        return group

    def add_calculation_item(self, table_name: str, item: CalculationItemInfo) -> None:
        self.calls.append(("add_calculation_item", {"table_name": table_name, "item": item}))
        group = self._calculation_groups[table_name]
        self._calculation_groups[table_name] = CalculationGroupInfo(
            table_name=group.table_name, column_name=group.column_name,
            precedence=group.precedence, items=group.items + (item,),
        )

    def delete_calculation_item(self, table_name: str, item_name: str) -> None:
        self.calls.append(("delete_calculation_item", {"table_name": table_name, "item_name": item_name}))
        group = self._calculation_groups[table_name]
        self._calculation_groups[table_name] = CalculationGroupInfo(
            table_name=group.table_name, column_name=group.column_name,
            precedence=group.precedence, items=tuple(i for i in group.items if i.name != item_name),
        )

    def list_calculation_groups(self) -> tuple[CalculationGroupInfo, ...]:
        self.refresh_metadata()
        return tuple(
            CalculationGroupInfo(
                table_name=g.table_name, column_name=g.column_name, precedence=g.precedence,
                items=tuple(sorted(g.items, key=lambda i: i.ordinal)),
            )
            for g in self._calculation_groups.values()
        )

    def create_perspective(self, perspective: PerspectiveInfo) -> None:
        self.calls.append(("create_perspective", {"perspective": perspective}))
        self._perspectives[perspective.name] = perspective

    def delete_perspective(self, name: str) -> None:
        self.calls.append(("delete_perspective", {"name": name}))
        del self._perspectives[name]

    def list_perspectives(self) -> tuple[PerspectiveInfo, ...]:
        self.refresh_metadata()
        return tuple(self._perspectives.values())

    def save_changes(self) -> None:
        self.calls.append(("save_changes", {}))
        self.save_changes_count += 1

    def disconnect(self) -> None:
        self.calls.append(("disconnect", {}))

    # --- utilitário só de teste -----------------------------------------

    def add_table(self, table: TableInfo) -> None:
        """Popula uma tabela pré-existente no fake, sem passar por
        create_calculated_table (e sem registrar em .calls) -- para
        montar o estado inicial de um teste."""
        self._tables[table.name] = _FakeTable(name=table.name, columns=list(table.columns))
