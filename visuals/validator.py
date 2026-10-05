"""Resolução e validação de campos referenciados por um visual.

Esta é a garantia central do projeto: `visual_writer.add_visual` só
aceita `ResolvedField` -- nunca uma string crua -- e o único jeito de
produzir um `ResolvedField` é passando por `resolve_field`/
`validate_visual_fields` aqui. Não existe caminho de código que leve uma
referência não validada até o JSON de um visual.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errors import InvalidVisualRoleError, UnknownFieldError
from modeling.metadata import ModelMetadata
from visuals.catalog import get_visual_spec


@dataclass(frozen=True, slots=True)
class ResolvedField:
    """Uma referência de campo já confirmada contra o modelo: existe,
    tem o tipo certo, e carrega a query_ref/native_query_ref prontas
    para ir no visual.json."""

    entity: str
    property: str
    kind: str  # "column" ou "measure"
    query_ref: str
    native_query_ref: str
    # Tipo da coluna ("String", "Int64", "Double", "DateTime", ...), como
    # veio do ModelMetadata -- None pra medida. Usado pra formatar o
    # literal de um filtro com valor (visuals.filters.format_literal).
    data_type: str | None = None


def resolve_field(metadata: ModelMetadata, reference: str) -> ResolvedField:
    """Resolve uma referência "Tabela.Campo" contra `metadata`.

    Tenta coluna primeiro (precisa existir exatamente na tabela
    informada); se não achar, tenta medida (medidas são únicas em todo o
    modelo, então o nome basta -- a query_ref usa a tabela real onde a
    medida foi criada, não necessariamente a que o chamador digitou).

    Raises:
        UnknownFieldError: nenhuma coluna nem medida corresponde à
            referência.
    """
    table_name, property_name = _split_reference(reference)

    table = metadata.find_table(table_name)
    if table is not None:
        column = next((c for c in table.columns if c.name == property_name), None)
        if column is not None:
            return ResolvedField(
                entity=table_name,
                property=property_name,
                kind="column",
                query_ref=f"{table_name}.{property_name}",
                native_query_ref=property_name,
                data_type=column.data_type,
            )

    measure = metadata.find_measure(property_name)
    if measure is not None:
        return ResolvedField(
            entity=measure.table_name,
            property=measure.name,
            kind="measure",
            query_ref=f"{measure.table_name}.{measure.name}",
            native_query_ref=measure.name,
        )

    raise UnknownFieldError(
        entity=table_name, property=property_name, suggestions=_suggest(metadata, reference)
    )


def field_reference_node(field: ResolvedField) -> dict[str, Any]:
    """Nó `Column`/`Measure` (`Expression.SourceRef.Entity` + `Property`)
    pra um `ResolvedField` já resolvido -- a mesma forma de referência de
    campo usada tanto na projeção de um visual quanto em `field`/
    `fieldExpr` de um filtro (filterConfiguration/1.1.0)."""
    kind_key = "Column" if field.kind == "column" else "Measure"
    return {kind_key: {"Expression": {"SourceRef": {"Entity": field.entity}}, "Property": field.property}}


def validate_visual_fields(
    visual_type: str,
    fields: dict[str, list[str]],
    metadata: ModelMetadata,
    report_dir: Path | None = None,
) -> dict[str, list[ResolvedField]]:
    """Resolve e valida todos os campos de `fields` contra o catálogo do
    tipo de visual e contra `metadata`.

    Ordem: primeiro resolve cada referência (UnknownFieldError se algum
    campo não existir no modelo), depois valida arity e tipo de cada
    role (InvalidVisualRoleError). Roles opcionais ausentes de `fields`
    simplesmente não aparecem no resultado.

    Raises:
        UnknownVisualTypeError: `visual_type` não está no catálogo
            (propagado por catalog.get_visual_spec).
        UnknownFieldError: alguma referência não existe no modelo.
        InvalidVisualRoleError: role desconhecido para esse tipo de
            visual, role obrigatório ausente, número de campos fora do
            permitido, ou tipo de campo (coluna/medida) não aceito
            naquele role.
    """
    spec = get_visual_spec(visual_type, report_dir)

    unknown_roles = set(fields) - set(spec.roles)
    if unknown_roles:
        raise InvalidVisualRoleError(
            f"Role(s) {sorted(unknown_roles)} não existem para o tipo de "
            f"visual '{visual_type}'. Roles válidos: {sorted(spec.roles)}."
        )

    resolved_by_role: dict[str, list[ResolvedField]] = {}
    for role_name, role in spec.roles.items():
        references = fields.get(role_name, [])
        resolved = [resolve_field(metadata, ref) for ref in references]

        if len(resolved) < role.min_fields or (
            role.max_fields is not None and len(resolved) > role.max_fields
        ):
            raise InvalidVisualRoleError(
                f"Role '{role_name}' do visual '{visual_type}' espera entre "
                f"{role.min_fields} e {role.max_fields or 'qualquer número de'} "
                f"campo(s); recebeu {len(resolved)}."
            )

        for field in resolved:
            if field.kind not in role.allowed_kinds:
                raise InvalidVisualRoleError(
                    f"Role '{role_name}' do visual '{visual_type}' não aceita "
                    f"campo do tipo '{field.kind}' ('{field.query_ref}'). "
                    f"Tipos aceitos: {', '.join(role.allowed_kinds)}."
                )

        if resolved:
            resolved_by_role[role_name] = resolved

    return resolved_by_role


def _split_reference(reference: str) -> tuple[str, str]:
    if "." not in reference:
        raise UnknownFieldError(entity=reference, property="", suggestions=[])
    table_name, _, property_name = reference.partition(".")
    return table_name, property_name


def _suggest(metadata: ModelMetadata, reference: str) -> list[str]:
    candidates = [f"{t.name}.{c.name}" for t in metadata.tables for c in t.columns]
    candidates += [f"{m.table_name}.{m.name}" for m in metadata.measures]
    return difflib.get_close_matches(reference, candidates, n=3, cutoff=0.6)
