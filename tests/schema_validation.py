"""Helper de teste: valida os arquivos PBIR gerados por este projeto
contra os schemas oficiais públicos, offline, usando os arquivos
vendorizados em tests/schemas/.

Não faz parte do pacote publicado -- é só infraestrutura de teste. Cada
schema vendorizado cobre exatamente o que este projeto gera; propriedades
que este projeto nunca escreve dependem de outro schema que não precisa
ser vendorizado, porque o validador só resolve `$ref` das chaves
realmente presentes na instância -- por isso `formattingObjectDefinitions/
1.3.0` (referenciado por `page.json.objects` e pelas propriedades de
formatação de `filterConfiguration`, nenhuma delas escrita por este
projeto) não está aqui, enquanto `formattingObjectDefinitions/1.5.0` está
(o visual `textbox` usa `objects.general[].properties.paragraphs` para o
próprio conteúdo de texto -- diferente dos outros 7 tipos, que só usam
`query`). `filterConfiguration/1.1.0` e `semanticQuery/1.2.0` foram
vendorizados para validar `filterConfig` de página de drillthrough
(`visuals.page_writer.add_drillthrough_field`).
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource

SCHEMAS_DIR = Path(__file__).parent / "schemas"

_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"

# URI sob a qual cada arquivo precisa ser registrado para que os $ref
# relativos de QUEM APONTA para ele resolvam corretamente. Note que o
# $id interno declarado em visualConfiguration.2.3.0.schema-embedded.json
# tem um typo (".embedded.json" em vez de "-embedded.json") -- por isso
# registramos explicitamente sob a URI com hífen, que é a que
# visualContainer.json (e page.json) realmente referenciam.
_RESOURCE_FILES: dict[str, str] = {
    f"{_BASE}/visualContainer/2.7.0/schema.json": "visualContainer.2.7.0.json",
    f"{_BASE}/visualConfiguration/2.3.0/schema-embedded.json": (
        "visualConfiguration.2.3.0.schema-embedded.json"
    ),
    f"{_BASE}/semanticQuery/1.4.0/schema.json": "semanticQuery.1.4.0.json",
    f"{_BASE}/page/1.4.0/schema.json": "page.1.4.0.json",
    f"{_BASE}/pagesMetadata/1.0.0/schema.json": "pagesMetadata.1.0.0.json",
    f"{_BASE}/versionMetadata/1.0.0/schema.json": "versionMetadata.1.0.0.json",
    f"{_BASE}/report/3.3.0/schema.json": "report.3.3.0.json",
    f"{_BASE}/formattingObjectDefinitions/1.5.0/schema.json": "formattingObjectDefinitions.1.5.0.json",
    # bookmark/1.0.0 aponta pra formattingObjectDefinitions/1.0.0 (que usa
    # semanticQuery/1.0.0) quando o bookmark tem `objects.merge` -- caso
    # do bookmark de reset (create_reset_bookmark).
    f"{_BASE}/formattingObjectDefinitions/1.0.0/schema.json": "formattingObjectDefinitions.1.0.0.json",
    f"{_BASE}/semanticQuery/1.0.0/schema.json": "semanticQuery.1.0.0.json",
    f"{_BASE}/bookmark/1.0.0/schema.json": "bookmark.1.0.0.json",
    f"{_BASE}/bookmarksMetadata/1.0.0/schema.json": "bookmarksMetadata.1.0.0.json",
    # Mesmo typo de visualConfiguration (".schema.embedded.json" no $id
    # interno do arquivo vs "-embedded.json" no $ref de quem aponta pra
    # ele) -- registrado sob a URI com hífen, a que page.json usa de
    # verdade.
    f"{_BASE}/filterConfiguration/1.1.0/schema-embedded.json": "filterConfiguration.1.1.0.json",
    f"{_BASE}/semanticQuery/1.2.0/schema.json": "semanticQuery.1.2.0.json",
    # report.json aponta pra 1.3.0 (page.json usa 1.1.0) -- vendorizado
    # pra validar filtro de relatório (visuals.filter_writer). Mesmo
    # typo de $id que a 1.1.0; seus $ref externos (semanticQuery/1.4.0,
    # formattingObjectDefinitions/1.5.0) já estão registrados acima.
    f"{_BASE}/filterConfiguration/1.3.0/schema-embedded.json": "filterConfiguration.1.3.0.json",
    # mobile.json (layout de celular, visuals.mobile_layout). A 2.3.0
    # aponta pras mesmas formattingObjectDefinitions/1.5.0 e
    # visualConfiguration/2.3.0 já registradas acima.
    f"{_BASE}/visualContainerMobileState/2.3.0/schema.json": "visualContainerMobileState.2.3.0.json",
}

# O schema de tema de relatório é publicado num repositório diferente
# (microsoft/powerbi-desktop-samples, não microsoft/json-schemas) e não
# tem $ref externo nenhum -- registrado à parte, fora de _RESOURCE_FILES/
# _BASE, que são específicos da família fabric/item/report/definition.
_REPORT_THEME_SCHEMA_FILE = "reportThemeSchema.2.157.json"


def _load(filename: str) -> dict:
    return json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))


def _build_registry() -> Registry:
    resources = [(uri, Resource.from_contents(_load(fn))) for uri, fn in _RESOURCE_FILES.items()]
    return Registry().with_resources(resources)


_REGISTRY = _build_registry()


def _validator_for(filename: str) -> Draft7Validator:
    return Draft7Validator(_load(filename), registry=_REGISTRY)


def validate_visual_json(instance: dict) -> None:
    """Valida contra o schema oficial visualContainer/2.7.0."""
    _validator_for("visualContainer.2.7.0.json").validate(instance)


def validate_mobile_json(instance: dict) -> None:
    """Valida contra o schema oficial visualContainerMobileState/2.3.0
    (mobile.json)."""
    _validator_for("visualContainerMobileState.2.3.0.json").validate(instance)


def validate_page_json(instance: dict) -> None:
    """Valida contra o schema oficial page/1.4.0."""
    _validator_for("page.1.4.0.json").validate(instance)


def validate_pages_metadata_json(instance: dict) -> None:
    """Valida contra o schema oficial pagesMetadata/1.0.0 (pages.json)."""
    _validator_for("pagesMetadata.1.0.0.json").validate(instance)


def validate_version_json(instance: dict) -> None:
    """Valida contra o schema oficial versionMetadata/1.0.0 (version.json)."""
    _validator_for("versionMetadata.1.0.0.json").validate(instance)


def validate_report_json(instance: dict) -> None:
    """Valida contra o schema oficial report/3.3.0 (report.json)."""
    _validator_for("report.3.3.0.json").validate(instance)


def validate_bookmark_json(instance: dict) -> None:
    """Valida contra o schema oficial bookmark/1.0.0."""
    _validator_for("bookmark.1.0.0.json").validate(instance)


def validate_bookmarks_metadata_json(instance: dict) -> None:
    """Valida contra o schema oficial bookmarksMetadata/1.0.0 (bookmarks.json)."""
    _validator_for("bookmarksMetadata.1.0.0.json").validate(instance)


def validate_report_theme_json(instance: dict) -> None:
    """Valida contra o schema oficial de tema de relatório (Report Theme
    JSON Schema, microsoft/powerbi-desktop-samples)."""
    Draft7Validator(_load(_REPORT_THEME_SCHEMA_FILE)).validate(instance)
