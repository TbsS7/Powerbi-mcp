# powerbi-fullstack-mcp

> **In English.** An MCP server (Python) that lets an AI assistant build
> Power BI work end to end: **data modeling** (tables, DAX measures,
> relationships, calculation groups, roles, field parameters) through
> TOM/XMLA against an open Power BI Desktop, and **reports** (pages,
> visuals, formatting, bookmarks, navigation, themes) written as PBIR
> files inside a `.pbip` project. Every visual is cross-checked against
> the real model before it is written, so generated dashboards don't
> break on open. 103 tools, 888 offline tests (no Desktop needed), and
> each feature validated live in Power BI Desktop, including a real
> dashboard built for a university People Analytics competition.
>
> **Requirements:** Windows, Power BI Desktop, Python 3.10+. The Microsoft
> TOM / ADOMD.NET DLLs are *not* bundled: `python scripts/setup_tom.py`
> fetches them from the official NuGet packages.
> **Install:** `pip install -e ".[dev,modeling]"`, then register `server.py`
> in your MCP client (see `claude_desktop_config.example.json`).
> The rest of this README, including the live-validation log, is in
> Portuguese. License: [MIT](LICENSE). Third-party schemas:
> [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Servidor MCP em Python que une duas capacidades que hoje só existem
separadas em outros MCPs de Power BI:

- **Modelagem de dados** — criar tabelas, medidas DAX e relacionamentos
  no modelo tabular, via TOM/XMLA contra uma instância aberta do Power
  BI Desktop.
- **Visuais e dashboards** — criar páginas e visuais no formato PBIR
  (arquivos JSON dentro da pasta `.Report` de um projeto `.pbip`).

O valor central é a **validação cruzada**: nenhum visual é escrito sem
que cada tabela/coluna/medida que ele referencia tenha sido confirmada
contra o modelo real — o que impede o caso mais comum de dashboard
gerado por agente que quebra ao abrir.

## Estrutura do projeto

```
MCPPowerBI/
├── server.py           # registra as ferramentas MCP (lista completa abaixo)
├── errors.py           # hierarquia de erros de domínio
├── modeling/            # TOM/XMLA (estrutura) + ADOMD.NET (consulta) + leitura offline de .tmdl
├── visuals/             # leitura/escrita de arquivos PBIR
├── orchestrator/         # contrato em 2 etapas (plan / apply)
├── scripts/setup_tom.py  # baixa e verifica as DLLs cliente do TOM e do ADOMD.NET
└── tests/                # testes unitários, com fakes para TOM e ADOMD.NET
```

## Ferramentas disponíveis

| Camada | Ferramenta | O que faz |
|---|---|---|
| Modelagem | `connect_to_desktop` | Conecta à instância aberta do Power BI Desktop via XMLA local |
| Modelagem | `save_desktop` | Salva (Ctrl+S) o projeto via automação de janela -- só depois de mudanças de modelo, nunca depois de escrever visuais |
| Modelagem | `create_table` | Cria tabela calculada (DAX) |
| Modelagem | `create_measure` | Cria medida DAX numa tabela existente |
| Modelagem | `create_relationship` | Cria relacionamento entre duas tabelas |
| Modelagem | `list_model_metadata` | Lista tabelas, colunas, medidas e relacionamentos (XMLA ou TMDL) |
| Modelagem | `evaluate_dax` | Executa uma consulta DAX e devolve valores reais (via ADOMD.NET) -- diferente de list_model_metadata, que só lista estrutura |
| Modelagem | `create_perspective` / `delete_perspective` / `list_perspectives` | Perspectivas: recorte do modelo (tabelas inteiras e/ou campos avulsos) usado no "Personalizar visuais" -- não é segurança |
| Modelagem | `profile_measures` | Diagnóstico de DAX lento: mede cada medida (a frio e a quente), ordena da mais lenta e aponta padrões lentos do guia oficial da Microsoft -- só leitura |
| Modelagem | `evaluate_dax_as_role` | Simulação de RLS: executa DAX "como se fosse" um role -- o "Exibir como" do Desktop, só leitura (não simula um usuário específico) |
| Modelagem | `update_measure` | Atualiza `dax_expression`/`format_string` de uma medida existente (só o que for passado muda) |
| Modelagem | `delete_measure` | Remove uma medida do modelo |
| Modelagem | `delete_relationship` | Remove um relacionamento existente |
| Modelagem | `delete_table` | Remove uma tabela -- recusa se algum relacionamento ainda apontar pra ela |
| Modelagem | `create_calculated_column` | Cria uma coluna calculada (avaliada linha a linha, armazenada no modelo) numa tabela existente |
| Modelagem | `delete_column` | Remove uma coluna (calculada ou de origem) de uma tabela |
| Modelagem | `create_hierarchy` | Cria uma hierarquia de drill-down (ex: Ano > Trimestre > Mês) numa tabela |
| Modelagem | `delete_hierarchy` | Remove uma hierarquia |
| Modelagem | `list_hierarchies` | Lista as hierarquias existentes no modelo (conexão XMLA ativa) |
| Modelagem | `create_role` | Cria um role de RLS (segurança em nível de linha), sem filtro ainda |
| Modelagem | `add_table_permission` | Define o filtro DAX de RLS de um role para uma tabela |
| Modelagem | `delete_role` | Remove um role de RLS (e todos os filtros dele) |
| Modelagem | `list_roles` | Lista os roles de RLS/OLS existentes no modelo (conexão XMLA ativa) |
| Modelagem | `hide_column` | Esconde uma coluna por completo (dado e metadado) para um role -- OLS |
| Modelagem | `unhide_column` | Reverte hide_column |
| Modelagem | `set_table_description` | Define a descrição de uma tabela (tooltip no painel de campos) |
| Modelagem | `set_column_metadata` | Define descrição e/ou pasta de exibição de uma coluna |
| Modelagem | `set_measure_metadata` | Define descrição e/ou pasta de exibição de uma medida |
| Modelagem | `set_column_sort_by` | Ordena uma coluna por outra (ex: nome do mês pelo número do mês) |
| Modelagem | `set_column_format` | Format string e/ou categoria de dado (ex: País/Região) de uma coluna |
| Modelagem | `set_column_visibility` | Esconde/reexibe uma coluna do painel de Campos pra todo mundo (diferente de hide_column, que é por role) |
| Modelagem | `create_time_intelligence_measures` | Gera medidas YTD/QTD/MTD/PY/PM/YoY %/MoM % a partir de uma medida base |
| Modelagem | `create_field_parameter` | Cria um field parameter (seletor de medida/coluna pro usuário trocar num slicer) |
| Modelagem | `refresh_table` | Dispara uma nova leitura dos dados de uma tabela -- pode demorar, sem timeout embutido |
| Modelagem | `refresh_model` | Igual, para todas as tabelas do modelo de uma vez |
| Modelagem | `create_calculation_group` / `create_time_intelligence_calculation_group` | Calculation group: itens (ex: Atual/YTD/PY/YoY %) que valem pra qualquer medida via SELECTEDMEASURE() -- exige opt-in pra ligar "Discourage implicit measures" |
| Modelagem | `add_calculation_item` / `delete_calculation_item` / `list_calculation_groups` | Mantém e lista os itens de um calculation group |
| Modelagem | `audit_model` | Aponta problemas de qualidade/documentação do modelo (medida sem formato/descrição, chave órfã, tabela desconectada, coluna oculta sem uso) -- só leitura, não corrige nada |
| Visuais | `create_report_page` | Cria uma página no relatório PBIR |
| Visuais | `delete_report_page` | Remove uma página (e todos os visuais dela) |
| Visuais | `add_drillthrough_field` / `remove_drillthrough_field` | Torna uma página destino de drill-through por um campo (clique direito → página de detalhe filtrada) |
| Visuais | `add_visual` | Adiciona um visual a uma página, validando os campos contra o modelo |
| Visuais | `update_visual` | Atualiza um visual existente no lugar -- reposiciona e/ou substitui o conteúdo (`fields`/`text`) |
| Visuais | `delete_visual` | Remove um visual de uma página |
| Visuais | `list_visuals` | Lista os visuais de uma página (tipo, posição, campos/texto) |
| Visuais | `set_slicer_config` | Slicer: estilo (lista, dropdown, entre, relativo...), modo de seleção, "Selecionar tudo" e caixa de pesquisa |
| Visuais | `set_visual_field_parameter` | Liga um visual a um field parameter (o visual troca de medida/coluna conforme o slicer) |
| Visuais | `set_page_layout` | Reorganiza os visuais de uma página (`grid` ou `kpi_row`); `top`/`keep_fixed` reservam a faixa do título no topo |
| Visuais | `set_slicer_sync` | Sincroniza um slicer com outros do mesmo grupo (em qualquer página) |
| Visuais | `remove_slicer_sync` | Reverte set_slicer_sync |
| Visuais | `add_page_filter` / `remove_page_filter` | Filtro com valor numa página inteira (categórico, faixa ou comparação), sem slicer |
| Visuais | `add_report_filter` / `remove_report_filter` | Filtro com valor no relatório inteiro (todas as páginas), preservando tema/resto do report.json |
| Visuais | `add_navigation_button` | Botão que navega pra uma página, aplica um bookmark ou limpa as segmentações ("voltar ao padrão"); pode ser transparente (por cima de um desenho), ter texto, um ícone personalizado (imagem sua), cor de fundo e cantos arredondados |
| Visuais | `create_bookmark` | Bookmark de navegação de página, ou de mostrar/esconder visuais (painel de informações) |
| Visuais | `create_reset_bookmark` | Bookmark "voltar ao padrão" da página (slicers, filtros, drill, clique em gráfico) -- pra um botão de resetar tudo |
| Visuais | `delete_bookmark` | Remove um bookmark |
| Visuais | `list_bookmarks` | Lista os bookmarks existentes no relatório |
| Visuais | `set_visual_color` | Cor de uma série (medida) -- ou, com `value`, de UM item de uma coluna de legenda/categoria (ex: "PY" cinza) |
| Visuais | `set_visual_title` | Texto/tamanho/cor do título de um visual (ou esconder) e o subtítulo automático (esconder/trocar) |
| Visuais | `set_textbox_style` | Texto de um textbox (título de página): tamanho, negrito, itálico, sublinhado, cor, fonte, alinhamento -- no texto todo ou numa linha |
| Visuais | `set_visual_container_style` | Moldura de qualquer visual: cor/transparência do fundo, borda (cor, largura, cantos arredondados) e margem interna |
| Visuais | `set_visual_alt_text` | Texto alternativo do visual (acessibilidade: o que o leitor de tela lê) |
| Visuais | `set_visual_tooltip_page` | Liga um visual a uma página de tooltip (`create_report_page(tooltip=True)`) -- a mini-página aparece ao passar o mouse |
| Visuais | `set_mobile_layout` | Layout de celular da página (empilha título, cartões em dupla e gráficos na tela de 324px) |
| Visuais | `import_custom_visual` / `list_custom_visuals` / `remove_custom_visual` | Visual personalizado (.pbiviz, ex: do AppSource): importa no relatório e passa a valer em `add_visual`/blueprint com os campos do próprio visual |
| Visuais | `set_page_perspective` | Perspectiva que o leitor vê no "Personalizar visuais" da página |
| Visuais | `add_visual_filter` / `remove_visual_filter` | Filtro com valor em um visual só (ex: limitar um gráfico aos itens "Atual" e "PY" de um calculation group) |
| Visuais | `set_visual_hidden` | Esconde/mostra um visual (ex: painel que aparece por bookmark) |
| Visuais | `set_button_slicer_style` | Slicer de botões (`advancedSlicerVisual`): cores normal/selecionado, seleção única, ladrilhos por linha, contorno, cantos |
| Visuais | `set_page_background` | Cor de fundo da página (tela atrás dos visuais) e do papel de parede (área fora da página) |
| Visuais | `add_image` | Visual Imagem a partir de um arquivo (ícone PNG/SVG, logo), com ajuste fit/stretch/fill |
| Visuais | `set_page_background_image` | Imagem de fundo da página ou do papel de parede (ex: fundo desenhado no PowerPoint/Figma), com ajuste Fit/Fill/Stretch -- reaproveita a imagem se já estiver no projeto |
| Visuais | `set_card_style` | Cartão (KPI): tamanho, cor, negrito e unidade do valor + texto de baixo (mostrar, tamanho, cor, trocar o texto) -- `cardVisual` e `card` legado; no `cardVisual`, também o preenchimento e a borda internos e um ícone/imagem dentro do cartão |
| Visuais | `set_visual_tooltip_style` | Cores da dica de ferramenta (caixa ao passar o mouse): rótulo, valor e fundo |
| Visuais | `set_table_data_bars` | Barra de dados dentro das células de uma coluna numérica de tabela/matriz (cor, só a barra, também no total) |
| Visuais | `set_table_style` | Cores e fonte de tabela/matriz: cabeçalho, linhas (zebra opcional) e total -- ex: tabela escura em dashboard escuro |
| Visuais | `set_visual_default_color` | Cor de gráfico de uma série só (ex: todas as barras em laranja) |
| Visuais | `set_slicer_style` | Cabeçalho e itens do slicer clássico: mostrar, cores e tamanho |
| Visuais | `set_table_column_format` | Formato do número de uma coluna de tabela/matriz: unidade (mil/milhão) e casas decimais |
| Visuais | `set_visual_field_name` | Renomeia um campo só naquele visual (cabeçalho de coluna, legenda, eixo) sem mudar o modelo |
| Visuais | `expand_decomposition_tree` | Abre os níveis de uma árvore de decomposição (ex: segmento -> país dentro de um segmento) pra ela já aparecer aberta |
| Visuais | `set_decomposition_tree_style` | Cores e layout da árvore de decomposição: barras, nomes, valores, cabeçalho, conectores, barras por nível |
| Visuais | `set_line_style` | Estilo das linhas de gráfico de linha/área: tracejada/pontilhada, espessura, marcadores, curva -- de uma série ou de todas |
| Visuais | `set_visual_data_labels` | Rótulos de dado: mostrar, posição, unidade (mil/milhão), casas decimais, fonte, cor |
| Visuais | `set_visual_legend` | Legenda: mostrar, posição, título, fonte |
| Visuais | `set_visual_axis` | Eixo de categorias ou de valores: mostrar, título, fonte, inverter, início/fim, unidade, linhas de grade, largura mínima de categoria, eixo categórico/contínuo |
| Visuais | `apply_report_theme` | Cria/substitui o tema de cores do relatório inteiro |
| Visuais | `remove_report_theme` | Remove o tema customizado (volta ao padrão do Power BI) |
| Visuais | `set_visual_color_gradient` | Gradiente de cor (2 ou 3 pontos) baseado no valor de um campo |
| Visuais | `set_visual_conditional_color` | Cor por regra/limiar (ex: verde se >= 500, vermelho se < 0) |
| Orquestração | `plan_dashboard` | 1ª etapa: devolve metadata + schema de blueprint para quem chamou decidir o dashboard |
| Orquestração | `apply_dashboard_blueprint` | 2ª etapa: valida e executa o blueprint, criando modelo e visuais |

### Por que `build_dashboard_from_description` virou duas ferramentas

Este servidor não tem um LLM embutido — ele só executa código Python.
Decidir "quais tabelas usar" e "que layout fazer sentido" para uma
descrição em linguagem natural é trabalho de um modelo de linguagem, não
do servidor. Por isso o fluxo é:

1. Chame `plan_dashboard(description, pbip_path)`. Ele devolve o
   metadata completo do modelo, o catálogo de tipos de visual (com seus
   roles) e o JSON Schema do blueprint esperado.
2. Você (o agente/Claude que está chamando) decide o conteúdo do
   blueprint — usando exatamente os nomes de tabela/medida existentes ou
   os que decidir criar.
3. Chame `apply_dashboard_blueprint(blueprint, pbip_path)`. Ele valida
   tudo, cria o que falta no modelo, relê o metadata para confirmar, e
   só então escreve os arquivos de página/visual.

### Limitação: visuais não podem usar colunas de uma tabela nova no mesmo blueprint

Um blueprint pode criar uma tabela (`new_tables`) e pode criar visuais,
mas **um visual não pode referenciar uma coluna de uma tabela listada em
`new_tables` desse mesmo blueprint**. O motivo: as colunas de uma tabela
nova só existem depois que o Power BI Desktop avalia a expressão M/DAX
dela — algo que este servidor não faz (e não pode simular). Medidas não
têm esse problema, porque o nome de uma medida é conhecido sem avaliar
nada, então `new_measures` numa tabela nova funciona normalmente.

Na prática: crie a tabela num blueprint (ou via `create_table`), chame
`list_model_metadata`/`plan_dashboard` de novo para confirmar as
colunas reais, e só então monte o blueprint dos visuais que as usam.
`apply_dashboard_blueprint` detecta essa situação e falha com uma
mensagem explicando isso, antes de qualquer execução.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Para a camada de modelagem (TOM/XMLA), instale também o extra
`modeling`, que traz o `pythonnet`:

```bash
pip install -e ".[modeling]"
```

## Licenciamento e obtenção do TOM e do ADOMD.NET

A camada de modelagem depende do **Tabular Object Model (TOM)**, uma
biblioteca .NET da Microsoft (`Microsoft.AnalysisServices.Tabular.dll` e
suas dependências `Microsoft.AnalysisServices.Core.dll` e
`Microsoft.AnalysisServices.Tabular.Json.dll`) — define a *estrutura*
do modelo, nunca executa uma consulta. A ferramenta `evaluate_dax`
depende de uma biblioteca .NET **separada e independente**, o
**ADOMD.NET** (`Microsoft.AnalysisServices.AdomdClient.dll` e
dependências) — executa DAX/MDX e devolve valores reais, mas não sabe
criar/alterar nada no modelo. São duas fronteiras .NET distintas neste
projeto (`modeling/tom_runtime.py` e `modeling/query_runtime.py`), cada
uma com seu próprio pacote NuGet.

Este repositório **não inclui nenhuma dessas DLLs** — elas são
distribuídas pela Microsoft sob seus próprios termos de licença (via
pacotes NuGet ou instaladores como `sql_as_amo.msi`), não por cópia de
arquivo dentro de outro projeto. Redistribuí-las junto com este
servidor exigiria revisão de licenciamento própria.

### Obtendo as DLLs

```bash
python scripts/setup_tom.py
```

Baixa os pacotes oficiais `Microsoft.AnalysisServices.NetCore.retail.amd64`
(TOM) e `Microsoft.AnalysisServices.AdomdClient.NetCore.retail.amd64`
(ADOMD.NET) direto do nuget.org, **confere o SHA-512 de cada um contra o
valor publicado pela Microsoft** (protege contra um arquivo adulterado
no meio do caminho) e extrai as DLLs de ambos para `.tom-dlls/dlls/` —
que `resolve_tom_dll_dir()` e `resolve_adomd_dll_dir()` já checam
automaticamente, sem precisar configurar nada mais.

> **Por que não pegar as DLLs do próprio Power BI Desktop:** testamos
> contra uma instalação real via Microsoft Store, e ela só traz as DLLs
> internas do motor servidor (`Microsoft.AnalysisServices.Server.Tabular.dll`
> etc., com prefixo "Server." e uma API diferente) — não as DLLs
> cliente que um TOM/ADOMD externo precisa. Por isso o script busca os
> pacotes cliente certos.

Alternativas, se preferir não rodar o script (nessa ordem de
prioridade em `resolve_tom_dll_dir()` / `resolve_adomd_dll_dir()`):

1. Definir `TOM_DLL_PATH` (ou `ADOMD_DLL_PATH`, para `evaluate_dax`)
   apontando para um diretório com as DLLs correspondentes.
2. Ter o **Tabular Editor** ou o **SQL Server Management Studio (SSMS)**
   instalado, que trazem essas DLLs.
3. Ter o pacote `Microsoft.AnalysisServices.retail.amd64` do SQL Server
   instalado em
   `C:\Program Files\Microsoft SQL Server\<versão>\SDK\Assemblies`
   (só para o TOM).

Se nenhuma DLL for encontrada, a ferramenta falha com uma mensagem que
lista os caminhos verificados e aponta para esta seção.

### Troubleshooting: TypeLoadException ao conectar

No Windows, o pythonnet carrega **.NET Framework** por padrão — mas as
DLLs baixadas por `scripts/setup_tom.py` são a variante **NetCore**
(`netcoreapp3.0`). Carregar um assembly .NET Core dentro do .NET
Framework produz `System.TypeLoadException` em assemblies de fachada
como `System.ComponentModel.Primitives`. `modeling/tom_runtime.py`
já corrige isso chamando `pythonnet.load("coreclr")` antes do primeiro
`import clr` — validado com uma conexão real (Power BI Desktop via
Microsoft Store, `compatibility_level` 1606). Se você usar DLLs do
.NET Framework em vez das NetCore (ex.: as que vêm com o Tabular
Editor), defina `PYTHONNET_RUNTIME=netfx` para que o runtime carregado
volte a casar com elas.

### Descoberta de instâncias abertas

`connect_to_desktop` (quando `port` não é informado) checa
automaticamente as duas formas de instalação: a clássica
(`%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces`)
e a via Microsoft Store
(`%USERPROFILE%\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces`,
que usa um caminho diferente e grava `msmdsrv.port.txt` em UTF-16 sem
BOM) — confirmado testando contra uma instalação Store real.

`list_model_metadata` e a camada de visuais (`create_report_page`,
`add_visual`, `set_page_layout`) **não** exigem essas DLLs quando usadas
com `pbip_path` — nesse caso o metadata é lido diretamente dos arquivos
`.tmdl` do projeto, sem precisar do Power BI Desktop aberto nem do TOM.

**Instâncias já fechadas são ignoradas (2026-09-30).** Achado no uso: a
pasta de workspace de um Desktop que já foi fechado (ex: de forma
abrupta) pode ficar pra trás com o `msmdsrv.port.txt` -- `connect_to_desktop`
chegou a listar 3 instâncias com só 1 aberta, obrigando a passar `port`
na mão. Agora só conta instância cuja porta ainda responde
(`discovery.is_port_listening`: conexão TCP em 127.0.0.1 e ::1, 0,5 s);
conferido ao vivo que a instância viva aceita em milissegundos. Se só
sobrarem pastas de instâncias fechadas, o erro diz isso. (Não deu pra
reproduzir a pasta velha de novo no teste -- o Desktop fechado
normalmente limpou a dele; a filtragem é coberta por teste automatizado.)

### Fronteira de confiança: expressões DAX são código, não dado

**Atualização 2026-09-23**: suporte a Power Query (M) foi **removido**
deste servidor (decisão do usuário -- ver README e o
"REMOVIDO em 2026-09-23" na seção "Validação real" acima). Isso reduz
bastante o risco descrito nesta seção: `create_table` só aceita
`dax_expression` agora, e DAX não tem operação de I/O de arquivo/rede
(diferente de M, que podia rodar `File.Contents`/`Web.Contents` de
verdade dentro do Power BI Desktop).

Ainda assim, **trate `dax_expression` como código, não como dado**: o
servidor não sanitiza nem valida a expressão antes de mandá-la pro TOM
(a validação de sintaxe só acontece no `SaveChanges`/`refresh_table` do
próprio motor). Se você (ou um agente atuando por você) monta um
`DashboardBlueprint` a partir de uma descrição em linguagem natural
vinda de alguém não confiável, revise qualquer expressão DAX sugerida
antes de deixá-la chegar a `apply_dashboard_blueprint`.

## PBIR é um formato em preview

A camada de visuais escreve no formato **PBIR** (Power BI Enhanced
Report Format), que na data deste projeto ainda está em **preview** no
Power BI Desktop. Antes de abrir um projeto gerado por este servidor:

1. Vá em **Arquivo → Opções e configurações → Opções → Recursos de
   pré-visualização**.
2. Marque **Store reports using enhanced metadata format (PBIR)**.
3. Reinicie o Power BI Desktop.

Se o seu `.pbip` ainda estiver no formato legado (`report.json` em vez
da pasta `definition/`), abra-o no Desktop com a preview feature ligada
e salve — ele será convertido para PBIR. **Essa conversão não pode ser
desfeita pela interface** (o Desktop cria um backup automático, mas
reverter exige restaurá-lo manualmente).

## O ciclo salvar / reabrir

Modelagem e visuais escrevem em dois lugares diferentes, e isso importa
na hora de usar o servidor:

- **Modelagem** (via TOM/XMLA) muda o modelo **em memória** dentro do
  processo do Power BI Desktop aberto. Essa mudança só é persistida em
  disco quando você salva o `.pbip` no Desktop.
- **Visuais** (arquivos PBIR) são escritos **direto no disco**. Se o
  Power BI Desktop já estiver com esse relatório aberto, ele não vê os
  novos arquivos até você clicar em **Apply external changes**
  ("Aplicar alterações externas") ou fechar e reabrir o projeto.

> **Atalho confirmado ao vivo (2026-09-30): "Apply external changes".**
> Versões recentes do Desktop percebem sozinhas que os arquivos do
> projeto mudaram e mostram a faixa "This project's files were changed
> externally" com o botão **Apply external changes** -- ele recarrega os
> arquivos escritos pelo MCP **sem fechar e reabrir** (testado com
> visual personalizado novo + registro no report.json). O botão avisa
> "may overwrite your unsaved edits ... can't be undone": vale a MESMA
> regra de sempre -- se houver mudança de modelo ainda não salva, salve
> (Ctrl+S) ANTES de aplicar, senão ela se perde como ao fechar sem salvar.

**Nunca crie objetos de modelo (tabela/medida/relacionamento) e os
visuais que os usam na mesma leva.** Fluxo recomendado, em duas etapas
separadas:

**Etapa 1 -- modelo:**
1. Deixe o servidor criar as tabelas/medidas/relacionamentos que
   faltam (via TOM) -- sem nenhuma página/visual junto.
2. Salve o arquivo (Ctrl+S) -- manualmente, ou peça pro agente chamar
   `save_desktop` (que automatiza só esse passo, via automação de
   janela do Windows, e só é seguro chamar aqui, na Etapa 1). Isso
   persiste as mudanças de modelo feitas em memória.

**Etapa 2 -- visuais, só depois da Etapa 1 estar salva:**
3. Deixe o servidor criar as páginas/visuais (arquivos PBIR), usando os
   nomes de tabela/medida que a Etapa 1 já confirmou existir.
4. Clique em **Apply external changes** (no Desktop em português,
   **Aplicar alterações externas**) na faixa que o Desktop mostra -- ou,
   em versões antigas sem essa faixa, feche e reabra o projeto. Isso
   carrega os novos arquivos PBIR. **Não salve de novo antes disso**
   (ver abaixo).

> **Por que essas duas etapas não podem ser uma só -- dois achados
> reais, testando ao vivo, não hipóteses:**
>
> 1. **Fechar/reabrir sem salvar perde o modelo.** Criamos medidas via
>    TOM e os visuais que as usam via PBIR na mesma leva, e fechamos/
>    reabrimos o Desktop sem salvar primeiro. Reabrir recarregou o
>    modelo do que estava salvo em disco -- sem as medidas novas, que só
>    existiam na sessão em memória que acabou de ser descartada. Os
>    visuais (escritos direto no disco, e que continuam lá) passaram a
>    referenciar medidas inexistentes, e o Power BI Desktop mostrou
>    "Há algo errado com um ou mais campos" / erro `Missing_References`.
> 2. **A "correção óbvia" -- salvar antes de fechar/reabrir -- é
>    perigosa quando há visuais novos no meio.** Testamos: criamos uma
>    página nova via PBIR enquanto o Desktop já estava aberto (sem
>    fechar/reabrir ainda), e apertamos Ctrl+S nessa mesma sessão. A
>    página **desapareceu do disco**. O Power BI Desktop não faz merge
>    ao salvar -- Ctrl+S reescreve toda a pasta `definition/pages/` do
>    projeto com o que está na memória do Desktop, e qualquer página
>    que ele ainda não tenha carregado é descartada nesse processo.
>
> Ou seja: salvar apaga visual novo que o Desktop não viu ainda;
> fechar/reabrir sem salvar apaga modelo novo que só estava em memória.
> Não existe uma ação só que resolve as duas coisas ao mesmo tempo --
> por isso as duas etapas acima têm que ficar em chamadas separadas,
> com o salvar acontecendo **entre** elas, nunca depois de escrever um
> visual novo.
>
> Se você já criou as duas coisas juntas sem saber disso: feche e
> reabra sem salvar (perde o modelo, mantém os visuais), recrie
> exatamente as tabelas/medidas/relacionamentos que sumiram (confirme
> com `list_model_metadata`), e só então salve -- essa segunda rodada
> não cria nenhuma página nova, então salvar é seguro.
>
> 3. **Terceiro achado (2026-09-20): confirmar visualmente na sessão
>    viva NÃO é a mesma coisa que estar salvo -- e o processo do
>    Desktop pode reiniciar sozinho, sem fechar/reabrir manual nenhum.**
>    Criamos medidas de inteligência de tempo + `sort_by_column` +
>    `data_category` via TOM, confirmamos visualmente que funcionavam
>    na sessão ao vivo, e seguimos trabalhando por várias rodadas sem
>    nunca chamar `save_desktop` (só `save_changes()` do TOM, que fica
>    em memória). Bem depois, um visual mal formado (field parameter
>    vinculado errado a um cartão) causou um erro de renderização que
>    fez o processo interno do Desktop (`msmdsrv.exe`) reiniciar sozinho
>    -- confirmado pela porta XMLA mudar numa reconexão
>    (`connect_to_desktop` devolveu uma porta/`database_name`
>    diferentes de antes). Esse reinício apagou TODA mudança de
>    modelagem feita desde a última vez que o arquivo foi salvo de
>    verdade -- as medidas de inteligência de tempo, o sort_by_column e
>    o data_category, todas confirmadas visualmente antes, sumiram
>    junto. **Conclusão: "funcionou na sessão ao vivo" não é garantia
>    de nada até `save_desktop` rodar de verdade -- não adie o save só
>    porque a coisa parece estar funcionando.**

Sempre que `apply_dashboard_blueprint` escreve páginas/visuais, a
resposta inclui um campo `note` lembrando desse passo 3. Não é possível
detectar com certeza, só a partir do sistema de arquivos, se uma
instância aberta do Power BI Desktop corresponde a este projeto
específico — por isso o aviso aparece sempre que páginas/visuais são
escritos, mesmo que o Desktop não esteja com este projeto aberto no
momento.

## Configuração no Claude Desktop

Copie [`claude_desktop_config.example.json`](claude_desktop_config.example.json)
para o arquivo de configuração do Claude Desktop
(`%APPDATA%\Claude\claude_desktop_config.json` no Windows), ajustando:

- O caminho do `python.exe` da venv deste projeto.
- O caminho de `server.py`.
- `TOM_DLL_PATH` / `ADOMD_DLL_PATH`, se as DLLs do TOM / ADOMD.NET não
  estiverem em um dos locais descobertos automaticamente.

## Testes

```bash
python -m pytest tests/ -v
```

Toda a suíte roda **sem precisar do Power BI Desktop instalado ou
aberto** — a camada de modelagem é testada contra um fake do TOM
(`tests/fakes/fake_tom.py`) e a camada de visuais é testada contra um
projeto `.pbip` de exemplo (`tests/fixtures/sample_pbip/`), com os
`visual.json` gerados validados contra os schemas oficiais do PBIR
(`tests/schemas/`).

## Status

- [x] Fase 1 — esqueleto e as 10 ferramentas MCP registradas
- [x] Fase 2 — camada de modelagem (TOM/XMLA + leitor TMDL)
- [x] Fase 3 — camada de visuais (PBIR)
- [x] Fase 4 — orquestração (`plan_dashboard` / `apply_dashboard_blueprint`)
- [x] Validado contra um Power BI Desktop real (instalação via
      Microsoft Store) — ver "Validação real" abaixo.

## Validação real

Além da suíte automática, cada ferramenta foi testada contra o **Power BI
Desktop real** antes de ser considerada pronta. O método:

- **Fonte oficial antes de código:** todo formato PBIR (visual, página,
  bookmark, tema, filtros) foi conferido contra os schemas JSON da
  Microsoft (vendorizados em `tests/schemas/`) e contra a documentação
  oficial de autoria de PBIR.
- **Comparação com o que o Desktop grava:** quando a documentação não
  cobria um caso (gráfico de dispersão, KPI, botões, gráfico combinado,
  árvore de decomposição, cor condicional em cartões), a mesma ação foi
  feita pela interface do Desktop e o arquivo salvo foi comparado com o
  que o servidor gera. Os pontos que ficaram por "melhor esforço" estão
  marcados no código.
- **Conferência por caminho independente:** números comparados com
  consultas DAX diretas (`evaluate_dax`) e com as DMVs do motor
  (`INFO.MEASURES()`, `INFO.COLUMNS()`...); arquivos lidos de volta do
  disco depois de cada escrita.

Projetos usados nos testes ao vivo: um relatório de exemplo (Financial
Sample), réplicas de dashboards públicos (Banking, Employee Management) e
um **dashboard real de People Analytics** com 5 páginas (capa, visão
geral, retenção, equidade e recomendações, com simulador, navegação por
abas, painéis de ajuda e botões de "voltar ao padrão"), construído para
uma competição universitária.

**Limitações conhecidas:**

- PBIR ainda é um formato em preview (ver seção acima).
- Power Query (M) não é suportado: tratamento de dados fica no editor do
  próprio Desktop.
- Relacionamentos inativos ainda não são criados pela ferramenta.
- Coluna calculada nova + `refresh_table` já deixou o Desktop ocupado por
  vários minutos numa base pequena; prefira criar a coluna no Power Query.
- `set_line_style` ainda não aceita o gráfico combinado (colunas + linha).
