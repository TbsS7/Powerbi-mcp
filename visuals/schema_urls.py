"""URLs e versões dos schemas JSON públicos do PBIR usados por este
projeto, centralizados aqui para que uma mudança de versão (ex.: depois
de validar num Power BI Desktop real, per o README) seja uma edição
neste único arquivo.

Todos os schemas estão publicados em
https://github.com/microsoft/json-schemas/tree/main/fabric/item/report/definition
-- as versões abaixo são as mais recentes disponíveis lá no momento em
que este projeto foi escrito (setembro de 2026). PBIR ainda está em
preview; se o Power BI Desktop passar a exigir versões mais novas,
atualize as constantes aqui.
"""

from __future__ import annotations

_BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"

VERSION_METADATA_SCHEMA = f"{_BASE}/versionMetadata/1.0.0/schema.json"
PAGES_METADATA_SCHEMA = f"{_BASE}/pagesMetadata/1.0.0/schema.json"
PAGE_SCHEMA = f"{_BASE}/page/1.4.0/schema.json"
REPORT_SCHEMA = f"{_BASE}/report/3.3.0/schema.json"
VISUAL_CONTAINER_SCHEMA = f"{_BASE}/visualContainer/2.7.0/schema.json"
# mobile.json -- 2.3.0 é a que aponta pras mesmas formattingObjectDefinitions/
# visualConfiguration da visualContainer/2.7.0 (o Desktop grava 2.7.0,
# ainda não publicada no repositório de schemas em 2026-09-29).
VISUAL_CONTAINER_MOBILE_SCHEMA = f"{_BASE}/visualContainerMobileState/2.3.0/schema.json"
BOOKMARK_SCHEMA = f"{_BASE}/bookmark/1.0.0/schema.json"
BOOKMARKS_METADATA_SCHEMA = f"{_BASE}/bookmarksMetadata/1.0.0/schema.json"

# Schema do conteúdo de um tema de relatório -- publicado num repositório
# diferente (não faz parte da família fabric/item/report/definition
# acima), versionado numericamente (não semver) junto com o Power BI
# Desktop. 2.157.0 era a versão mais recente disponível quando este
# projeto foi escrito.
REPORT_THEME_SCHEMA = (
    "https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/"
    "main/Report%20Theme%20JSON%20Schema/reportThemeSchema-2.157.json"
)

# Conteúdo de definition/version.json. O schema exige o padrão
# major.minor.0 (patch sempre 0); ver versionMetadata acima.
PBIR_DEFINITION_VERSION = "2.1.0"
