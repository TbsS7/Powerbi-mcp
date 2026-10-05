"""Segunda etapa do contrato de orquestração: valida o blueprint,
executa as operações de modelagem que faltam e escreve os arquivos PBIR
resultantes de forma atômica.

Ordem de execução (a mesma em dry_run e em execução real, até o passo
5 -- é isso que garante que uma falha de validação nunca deixa nada pela
metade, escrito ou executado):

1. Valida o shape do blueprint (Pydantic).
2. Lê o metadata atual do modelo.
3. Recusa qualquer campo de visual que referencie uma COLUNA de uma
   tabela listada em `new_tables` deste mesmo blueprint -- colunas de
   tabela nova só são conhecidas depois que o Power BI Desktop avalia a
   expressão M/DAX, o que este servidor não faz (medidas são permitidas,
   porque o nome de uma medida é conhecido sem avaliar nada).
4. Monta um metadata "prospectivo" (atual + o que este blueprint
   promete criar) e valida cada campo de cada visual contra ele.
5. Se dry_run: para aqui, devolve um relatório do que seria feito.
6. Executa as operações de modelagem que faltam, na ordem
   tabelas -> medidas -> relacionamentos (cada uma usando
   modeling.operations, que valida de novo contra o estado real, com
   save=False), e faz um único runtime.save_changes() no final -- uma
   falha no meio não deixa nada persistido no modelo.
7. Escreve páginas/visuais de forma atômica: copia o projeto inteiro
   para um diretório de staging, aplica todas as mudanças lá (reusando
   visuals.page_writer/visual_writer/layout sem alteração nenhuma), e só
   troca o `definition/` real pelo staged se TUDO suceder. Uma falha no
   meio do caminho não deixa o `.pbip` real pela metade.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from errors import BlueprintValidationError, PageAlreadyExistsError
from modeling import connection
from modeling import metadata as modeling_metadata
from modeling import operations
from modeling.metadata import MeasureInfo, ModelMetadata, RelationshipInfo, TableInfo
from orchestrator.blueprint import DashboardBlueprint, PageSpec
from visuals import layout as layout_module
from visuals import formatting, page_writer, project, visual_writer
from visuals.validator import validate_visual_fields


def apply_dashboard_blueprint(
    blueprint: dict[str, Any],
    pbip_path: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    parsed = _parse_blueprint(blueprint)
    current_metadata = modeling_metadata.get_model_metadata(pbip_path=pbip_path)

    _reject_new_table_column_references(parsed, current_metadata)
    prospective_metadata = _build_prospective_metadata(parsed, current_metadata)
    _validate_all_visual_fields(parsed, prospective_metadata, pbip_path)

    if dry_run:
        return {
            "dry_run": True,
            "tables_created": [t.table_name for t in parsed.new_tables],
            "measures_created": [m.measure_name for m in parsed.new_measures],
            "relationships_created": [
                {"from": f"{r.from_table}.{r.from_column}", "to": f"{r.to_table}.{r.to_column}"}
                for r in parsed.new_relationships
            ],
            "pages": [
                {"page_name": p.page_name, "visual_count": len(p.visuals)} for p in parsed.pages
            ],
        }

    tables_created = _create_tables(parsed)
    measures_created = _create_measures(parsed)
    relationships_created = _create_relationships(parsed)
    if tables_created or measures_created or relationships_created:
        # Um único SaveChanges para as três etapas acima: se uma delas
        # falhar no meio (ex.: relacionamento inválido depois de tabela
        # e medida já criadas), nada desta chamada é persistido -- as
        # etapas anteriores ficam só como objetos pendentes no cliente
        # TOM em memória, nunca commitadas no modelo. (Esses objetos
        # pendentes continuam visíveis via list_model_metadata *nesta
        # mesma conexão* até ela ser refeita com connect_to_desktop --
        # é uma característica do próprio TOM, não deste servidor: o
        # objeto Model local reflete mudanças não salvas antes mesmo do
        # SaveChanges.)
        connection.get_active_runtime().save_changes()
    pages_report = _apply_pages_atomically(pbip_path, parsed.pages) if parsed.pages else []

    result: dict[str, Any] = {
        "dry_run": False,
        "tables_created": tables_created,
        "measures_created": measures_created,
        "relationships_created": relationships_created,
        "pages": pages_report,
    }
    if pages_report and (tables_created or measures_created or relationships_created):
        result["note"] = (
            "ATENÇÃO -- esta chamada misturou duas coisas que não têm "
            "uma ordem de salvar segura em comum: criou objetos no "
            "modelo (tabela/medida/relacionamento, só em memória até "
            "salvar) E escreveu página(s)/visual(is) que os referenciam "
            "(só em disco até o Desktop os carregar). Confirmado "
            "testando ao vivo: o Power BI Desktop NÃO faz merge ao "
            "salvar -- Ctrl+S reescreve toda a pasta de páginas do "
            "projeto com o que está na memória do Desktop, então "
            "salvar agora apagaria a página recém-escrita (o Desktop "
            "ainda não a conhece). E fechar/reabrir sem salvar antes "
            "perde os objetos de modelo (só existiam em memória). Não "
            "existe uma ação só que resolve as duas coisas.\n"
            "Caminho de recuperação, nessa ordem: (1) clique em 'Apply "
            "external changes' ('Aplicar alterações externas') no Desktop (ou feche e reabra o projeto SEM "
            "salvar) -- a página sobrevive, os objetos de modelo se "
            "perdem; (2) recrie exatamente as tabelas/medidas/"
            "relacionamentos que sumiram (confirme antes com "
            "list_model_metadata); (3) só então salve (Ctrl+S) -- como "
            "essa segunda rodada não cria nenhuma página nova, salvar "
            "agora é seguro.\n"
            "Para não cair nisso de novo: nunca peça new_tables/"
            "new_measures/new_relationships e pages no mesmo "
            "apply_dashboard_blueprint -- crie e salve o modelo "
            "primeiro, só depois crie os visuais numa chamada separada."
        )
    elif pages_report:
        result["note"] = (
            "Páginas/visuais foram escritos direto em disco (arquivos PBIR). "
            "Se o Power BI Desktop já estiver com este projeto aberto, ele "
            "só mostra esses arquivos novos depois de clicar em 'Apply "
            "external changes' ('Aplicar alterações externas', a faixa que ele exibe) ou de ser fechado sem "
            "salvar e reaberto -- as duas coisas descartam mudança de modelo "
            "ainda não salva, então salve o modelo antes. Não é "
            "possível detectar com certeza, só a partir do sistema de "
            "arquivos, se uma instância aberta do Desktop corresponde a este "
            "projeto específico, então este aviso aparece sempre que "
            "páginas/visuais são escritos, mesmo que o Desktop não esteja "
            "com este projeto aberto. Veja o README, seção 'O ciclo salvar / "
            "reabrir'."
        )
    return result


def _parse_blueprint(blueprint: dict[str, Any]) -> DashboardBlueprint:
    try:
        return DashboardBlueprint.model_validate(blueprint)
    except PydanticValidationError as exc:
        raise BlueprintValidationError(f"Blueprint inválido: {exc}") from exc


# --- validação prévia (antes de qualquer execução) -------------------------


def _reject_new_table_column_references(
    parsed: DashboardBlueprint, current_metadata: ModelMetadata
) -> None:
    new_table_names = {t.table_name for t in parsed.new_tables}
    if not new_table_names:
        return

    known_measure_names = set(current_metadata.measure_names()) | {
        m.measure_name for m in parsed.new_measures
    }

    for page in parsed.pages:
        for visual in page.visuals:
            for references in visual.fields.values():
                for reference in references:
                    table_name, _, property_name = reference.partition(".")
                    if table_name in new_table_names and property_name not in known_measure_names:
                        raise BlueprintValidationError(
                            f"O visual na página '{page.page_name}' referencia "
                            f"'{reference}', mas '{table_name}' está sendo criada "
                            "neste mesmo blueprint (new_tables) -- as colunas de "
                            "uma tabela nova só são conhecidas depois que o Power "
                            "BI Desktop avalia sua expressão M/DAX, o que este "
                            "servidor não faz. Crie a tabela num blueprint "
                            "separado primeiro, confirme suas colunas com "
                            "list_model_metadata, e só então monte o blueprint "
                            "dos visuais que a usam."
                        )


def _build_prospective_metadata(
    parsed: DashboardBlueprint, current_metadata: ModelMetadata
) -> ModelMetadata:
    """Metadata atual + o que este blueprint promete criar, para validar
    os visuais antes de executar qualquer coisa. Tabelas novas entram
    sem colunas (ver _reject_new_table_column_references -- é por isso
    que nenhum visual pode referenciar uma coluna delas aqui)."""
    new_tables = tuple(TableInfo(name=t.table_name, columns=()) for t in parsed.new_tables)
    new_measures = tuple(
        MeasureInfo(
            table_name=m.table_name,
            name=m.measure_name,
            dax_expression=m.dax_expression,
            format_string=m.format_string,
        )
        for m in parsed.new_measures
    )
    new_relationships = tuple(
        RelationshipInfo(
            from_table=r.from_table,
            from_column=r.from_column,
            to_table=r.to_table,
            to_column=r.to_column,
            cardinality=r.cardinality,
            cross_filter_direction=r.cross_filter_direction,
        )
        for r in parsed.new_relationships
    )
    return ModelMetadata(
        tables=current_metadata.tables + new_tables,
        measures=current_metadata.measures + new_measures,
        relationships=current_metadata.relationships + new_relationships,
    )


def _validate_all_visual_fields(parsed: DashboardBlueprint, metadata: ModelMetadata, pbip_path: str) -> None:
    # report_dir só pra reconhecer visual personalizado importado no
    # relatório (ver visuals.custom_visuals)
    report_dir = project.resolve_report_dir(pbip_path) if parsed.pages else None
    for page in parsed.pages:
        for visual in page.visuals:
            validate_visual_fields(visual.visual_type, visual.fields, metadata, report_dir)


# --- execução real: modelo ------------------------------------------------


def _create_tables(parsed: DashboardBlueprint) -> list[str]:
    created = []
    for table in parsed.new_tables:
        operations.create_table(
            table_name=table.table_name, dax_expression=table.dax_expression, save=False,
            refresh=False,
        )
        created.append(table.table_name)
    return created


def _create_measures(parsed: DashboardBlueprint) -> list[str]:
    created = []
    for measure in parsed.new_measures:
        operations.create_measure(
            table_name=measure.table_name,
            measure_name=measure.measure_name,
            dax_expression=measure.dax_expression,
            format_string=measure.format_string,
            save=False,
        )
        created.append(measure.measure_name)
    return created


def _create_relationships(parsed: DashboardBlueprint) -> list[dict[str, str]]:
    created = []
    for relationship in parsed.new_relationships:
        operations.create_relationship(
            from_table=relationship.from_table,
            from_column=relationship.from_column,
            to_table=relationship.to_table,
            to_column=relationship.to_column,
            cardinality=relationship.cardinality,
            cross_filter_direction=relationship.cross_filter_direction,
            save=False,
        )
        created.append(
            {
                "from": f"{relationship.from_table}.{relationship.from_column}",
                "to": f"{relationship.to_table}.{relationship.to_column}",
            }
        )
    return created


# --- execução real: páginas/visuais (atômica via staging) ------------------


def _apply_pages_atomically(pbip_path: str, pages: list[PageSpec]) -> list[dict[str, Any]]:
    report_dir = project.resolve_report_dir(pbip_path)
    project_root = report_dir.parent
    project_base_name = report_dir.name.removesuffix(".Report")
    semantic_model_dir = project_root / f"{project_base_name}.SemanticModel"

    staging_root = Path(tempfile.mkdtemp(prefix="powerbi_mcp_staging_"))
    try:
        # Copiamos só as pastas do PRÓPRIO projeto (.Report e, se
        # existir, .SemanticModel) -- nunca o diretório-pai inteiro.
        # Achado testando ao vivo: um projeto salvo direto na pasta do
        # usuário (ex.: C:\Users\<usuario>\) fazia project_root virar
        # essa pasta inteira, e copiá-la (Documentos, Desktop, etc.)
        # travava por minutos copiando decenas de milhares de arquivos
        # que nada têm a ver com o relatório.
        staged_report_dir = staging_root / report_dir.name
        shutil.copytree(report_dir, staged_report_dir)

        if semantic_model_dir.is_dir():
            shutil.copytree(semantic_model_dir, staging_root / semantic_model_dir.name)

        # resolve_report_dir acha a pasta .Report dentro de um diretório
        # -- não precisamos copiar o .pbip em si para isso funcionar.
        staged_pbip_path = str(staging_root)

        pages_report = [_apply_one_page(staged_pbip_path, page) for page in pages]

        _swap_definition(real_report_dir=report_dir, staged_report_dir=staged_report_dir)
        return pages_report
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _apply_one_page(staged_pbip_path: str, page: PageSpec) -> dict[str, Any]:
    try:
        page_writer.create_report_page(
            pbip_path=staged_pbip_path, page_name=page.page_name, display_name=page.display_name
        )
    except PageAlreadyExistsError:
        pass  # página já existe -- só adiciona os visuais a ela

    if page.background_color is not None:
        formatting.set_page_background(
            pbip_path=staged_pbip_path, page_name=page.page_name, color=page.background_color
        )

    title_visual = _add_page_title(staged_pbip_path, page) if page.title is not None else None
    # sem layout, o y de cada visual conta a partir de baixo da faixa do título
    y_offset = page.title.height if page.title is not None and page.layout is None else 0

    visuals_report = []
    for visual in page.visuals:
        result = visual_writer.add_visual(
            pbip_path=staged_pbip_path,
            page_name=page.page_name,
            visual_type=visual.visual_type,
            x=visual.x,
            y=visual.y + y_offset,
            width=visual.width,
            height=visual.height,
            fields=visual.fields,
        )
        if visual.alt_text:
            formatting.set_visual_alt_text(
                pbip_path=staged_pbip_path, page_name=page.page_name,
                visual_name=result["visual_name"], text=visual.alt_text,
            )
        visuals_report.append(result)

    if page.layout is not None:
        if title_visual is None:
            layout_module.set_page_layout(
                pbip_path=staged_pbip_path, page_name=page.page_name, layout=page.layout
            )
        else:
            layout_module.set_page_layout(
                pbip_path=staged_pbip_path, page_name=page.page_name, layout=page.layout,
                top=page.title.height + layout_module.MARGIN, keep_fixed=[title_visual],
            )

    report: dict[str, Any] = {"page_name": page.page_name, "visuals": visuals_report}
    if title_visual is not None:
        report["title_visual"] = title_visual
    return report


def _add_page_title(staged_pbip_path: str, page: PageSpec) -> str:
    """Faixa de título: textbox da largura da página no topo, com texto
    e fundo formatados pelas mesmas tools públicas (set_textbox_style,
    set_visual_container_style)."""
    title = page.title
    page_width, _ = layout_module.get_page_size(staged_pbip_path, page.page_name)
    visual_name = visual_writer.add_visual(
        pbip_path=staged_pbip_path, page_name=page.page_name, visual_type="textbox",
        x=0, y=0, width=page_width, height=title.height, text=title.text,
    )["visual_name"]
    formatting.set_textbox_style(
        pbip_path=staged_pbip_path, page_name=page.page_name, visual_name=visual_name,
        font_size=title.font_size, bold=title.bold, color=title.color, alignment=title.alignment,
    )
    formatting.set_visual_container_style(
        pbip_path=staged_pbip_path, page_name=page.page_name, visual_name=visual_name,
        background_color=title.background_color,
    )
    return visual_name


def _swap_definition(real_report_dir: Path, staged_report_dir: Path) -> None:
    staged_definition = staged_report_dir / "definition"
    real_definition = real_report_dir / "definition"

    backup_dir = None
    if real_definition.is_dir():
        backup_dir = real_report_dir / f".definition-backup-{uuid.uuid4().hex}"
        real_definition.rename(backup_dir)
    try:
        shutil.copytree(staged_definition, real_definition)
    except Exception:
        if backup_dir is not None:
            if real_definition.exists():
                shutil.rmtree(real_definition, ignore_errors=True)
            backup_dir.rename(real_definition)
        raise
    else:
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)
