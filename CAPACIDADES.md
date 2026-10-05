# O que o powerbi-fullstack-mcp faz hoje

Servidor MCP que une modelagem de dados (TOM/XMLA) e visuais/dashboards
(PBIR) do Power BI. **103 ferramentas**, 888 testes automatizados verdes
(atualizado em 2026-10-03). Quase tudo confirmado ao vivo contra o Power
BI Desktop real -- as exceções estão marcadas abaixo. Como cada uma foi
validada: [README.md](README.md), seção "Validação real".

`tests/test_docs_consistency.py` garante que toda ferramenta registrada
aparece aqui e no README -- se este arquivo ficar pra trás, a suíte quebra.

## Conexão

| Ferramenta | O que faz |
|---|---|
| `connect_to_desktop` | Conecta à instância aberta do Desktop (descobre a porta sozinho, ignorando instâncias já fechadas). Se o Desktop reiniciar e a porta mudar, as próximas chamadas avisam e sugerem a porta nova |
| `save_desktop` | Salva o projeto (Ctrl+S automatizado) -- só depois de mudança de modelo, nunca logo depois de escrever visual |

## Modelagem (dados/estrutura)

| Ferramenta | O que faz |
|---|---|
| `list_model_metadata` | Lista tabelas/colunas/medidas/relacionamentos (sempre atualizado, mesmo com tabela criada pela UI depois de conectar) |
| `evaluate_dax` | Executa DAX de verdade (valores reais) -- `max_rows`/`truncated`, `DEFINE MEASURE` ad-hoc |
| `create_table` / `delete_table` | Tabela calculada (DAX), devolvendo as colunas reais / remover (recusa se houver relacionamento) |
| `create_measure` / `update_measure` / `delete_measure` | Medida DAX |
| `create_relationship` / `delete_relationship` | Relacionamento |
| `create_calculated_column` / `delete_column` | Coluna calculada / remover coluna |
| `create_hierarchy` / `delete_hierarchy` / `list_hierarchies` | Hierarquia de drill-down (ex: Ano > Trimestre > Mês) |
| `create_role` / `add_table_permission` / `delete_role` / `list_roles` | RLS (segurança em nível de linha) |
| `hide_column` / `unhide_column` | OLS (esconder coluna por completo pra um role) |
| `create_perspective` / `delete_perspective` / `list_perspectives` | Perspectivas: recorte do modelo com só as tabelas/campos de um assunto, usado no "Personalizar visuais" (não é segurança) |
| `profile_measures` | Diagnóstico de DAX lento: mede quanto cada medida demora (a frio e a quente), ordena da mais lenta e dá dicas do guia oficial da Microsoft -- só leitura |
| `evaluate_dax_as_role` | Simulação de RLS: DAX "como se fosse" um role (o "Exibir como" do Desktop) -- simula role, não um usuário específico (RLS dinâmico não funciona no Desktop local) |
| `refresh_table` / `refresh_model` | Nova leitura dos dados |
| `set_table_description` / `set_column_metadata` / `set_measure_metadata` | Descrição e pasta de exibição |
| `set_column_sort_by` | Ordenar uma coluna por outra (ex: nome do mês pelo número) |
| `set_column_format` | Format string / categoria de dado (ex: País) -- *format string só testado automatizado* |
| `set_column_visibility` | Esconder/reexibir coluna pra todo mundo |
| `create_time_intelligence_measures` | Medidas YTD/QTD/MTD/PY/PM/YoY %/MoM % a partir de uma medida base |
| `create_field_parameter` | Field parameter (usuário troca a medida/coluna de um visual num slicer) |
| `create_calculation_group` / `create_time_intelligence_calculation_group` | Calculation group: itens (Atual/YTD/PY/YoY %...) que valem pra qualquer medida. Exige opt-in pra ligar "Discourage implicit measures" |
| `add_calculation_item` / `delete_calculation_item` / `list_calculation_groups` | Manter/listar itens de um calculation group |
| `audit_model` | Aponta problemas de qualidade/documentação do modelo -- só leitura, não corrige nada |

## Visuais / relatório

| Ferramenta | O que faz |
|---|---|
| `create_report_page` / `delete_report_page` | Criar/remover página (inclusive página de tooltip) |
| `add_visual` / `update_visual` / `delete_visual` / `list_visuals` | CRUD de visual -- 25 tipos, inclusive o slicer de botões `advancedSlicerVisual` (`azureMap` bloqueado por política do tenant) |
| `set_page_layout` | Reorganiza os visuais de uma página (`grid`/`kpi_row`); pode reservar a faixa do título no topo e deixar visuais fixos |
| `add_page_filter` / `remove_page_filter` | Filtro com valor na página inteira (lista de valores, faixa, comparação) |
| `add_report_filter` / `remove_report_filter` | Filtro com valor no relatório inteiro |
| `add_drillthrough_field` / `remove_drillthrough_field` | Drill-through (clique direito → página de detalhe filtrada) -- *vários campos na mesma página só testado automatizado* |
| `set_slicer_sync` / `remove_slicer_sync` | Sincronizar slicers entre páginas |
| `set_slicer_config` | Slicer: estilo (lista, dropdown, entre, relativo...), modo de seleção (única / múltipla com CTRL / múltipla), "Selecionar tudo" e caixa de pesquisa |
| `set_visual_field_parameter` | Liga um visual a um field parameter |
| `add_navigation_button` | Botão que navega pra uma página, aplica um bookmark ou limpa as segmentações; pode ser transparente (por cima de um desenho), ter texto, ícone personalizado, cor de fundo e cantos arredondados |
| `create_bookmark` / `delete_bookmark` / `list_bookmarks` | Bookmarks: ir pra uma página, ou mostrar/esconder visuais (painel de informações) |
| `create_reset_bookmark` | Bookmark "voltar ao padrão" da página (slicers, filtros, drill, clique em gráfico) -- pra um botão de resetar tudo |
| `set_visual_color` / `set_visual_title` | Cor de série (medida) ou de um item de legenda/categoria; título e subtítulo |
| `set_textbox_style` | Texto de textbox (título de página): tamanho, negrito, itálico, sublinhado, cor, fonte, alinhamento -- texto todo ou uma linha |
| `set_visual_container_style` | Moldura de qualquer visual: fundo (cor, transparência), borda (cor, largura, cantos) e margem interna |
| `set_visual_alt_text` | Texto alternativo do visual (acessibilidade: o que o leitor de tela lê) |
| `set_visual_tooltip_page` | Tooltip personalizado: ao passar o mouse, mostra uma mini-página (criada com `create_report_page(tooltip=True)`) |
| `set_mobile_layout` | Layout de celular da página, sem mexer no da área de trabalho |
| `import_custom_visual` / `list_custom_visuals` / `remove_custom_visual` | Visual personalizado (arquivo .pbiviz, ex: do AppSource, ou um .pbix que já use o visual): importa e usa em `add_visual`/blueprint |
| `set_page_perspective` | Perspectiva da página no "Personalizar visuais" (o leitor só vê os campos dela) |
| `add_visual_filter` / `remove_visual_filter` | Filtro com valor em um visual só |
| `set_visual_hidden` | Esconde/mostra um visual (painel que aparece por bookmark) |
| `set_button_slicer_style` | Slicer de botões (anos, moedas, "cartões clicáveis"): cores normal/selecionado, seleção única, layout |
| `set_page_background` | Cor de fundo da página (tela atrás dos visuais) e do papel de parede |
| `add_image` | Imagem a partir de um arquivo: ícones personalizados, logo |
| `set_page_background_image` | Imagem de fundo da página (ex: fundo desenhado no PowerPoint/Figma/Canva) ou do papel de parede |
| `set_card_style` | Cartão (KPI): tamanho/cor/negrito/unidade do valor e o texto de baixo -- cartão atual (`cardVisual`) e legado (`card`); preenchimento/borda internos e ícone/imagem dentro do `cardVisual` |
| `set_visual_tooltip_style` | Cores da dica de ferramenta: rótulo, valor e fundo |
| `set_table_data_bars` | Barra de dados dentro das células de uma coluna numérica de tabela/matriz |
| `set_table_style` | Cores e fonte de tabela/matriz: cabeçalho, linhas (zebra opcional) e total |
| `set_visual_default_color` | Cor de gráfico de uma série só |
| `set_slicer_style` | Cabeçalho e itens do slicer clássico |
| `set_table_column_format` | Unidade (mil/milhão) e casas decimais de uma coluna de tabela/matriz |
| `set_visual_field_name` | Renomeia um campo só naquele visual (cabeçalho, legenda, eixo) |
| `expand_decomposition_tree` | Abre os níveis de uma árvore de decomposição pra ela já aparecer aberta |
| `set_decomposition_tree_style` | Cores e layout da árvore de decomposição |
| `set_line_style` | Linha tracejada/pontilhada, espessura, marcadores e curva -- de uma série ou de todas |
| `set_visual_data_labels` / `set_visual_legend` / `set_visual_axis` | Rótulos de dado, legenda e eixos -- valida por tipo de visual contra o schema oficial de tema |
| `set_visual_color_gradient` / `set_visual_conditional_color` | Cor por gradiente ou por regra/limiar |
| `apply_report_theme` / `remove_report_theme` | Tema de cores do relatório inteiro |

## Orquestração

| Ferramenta | O que faz |
|---|---|
| `plan_dashboard` / `apply_dashboard_blueprint` | Dashboard a partir de uma descrição: 1) devolve metadata + schema, 2) valida e executa o blueprint (modelo + visuais). Cada página pode sair com faixa de título formatada e cor de fundo |

## O que NÃO faz (de propósito)

- **Power Query / M** -- removido em 2026-09-23: o TOM não consegue
  descobrir colunas de uma fonte M, e editar M sem isso era frágil.
  Tabelas novas só como tabela calculada (DAX).
- **Credencial de fonte de dados** -- nunca pede nem guarda senha.
- **Publicar no Power BI Service** -- fica pra um humano.
