"""Validação de nomes usados como componente de caminho de arquivo
dentro da pasta .Report (page_name -> definition/pages/<page_name>/).

Duas razões para essa validação, não só uma:

1. Segurança: sem ela, um page_name como "../../../Windows/System32/x"
   escaparia da pasta pages/ pretendida (path traversal) quando
   concatenado via Path / page_name -- page_writer.create_report_page,
   visual_writer.add_visual e layout.set_page_layout constroem esse
   caminho diretamente a partir do valor recebido.
2. Corretude PBIR: o formato exige que o `name` de um objeto (diferente
   do `displayName`, que aceita qualquer texto) use só letras, dígitos,
   underscore ou hífen -- ver a seção "PBIR naming convention" em
   https://learn.microsoft.com/power-bi/developer/projects/projects-report

O regex abaixo (só [A-Za-z0-9_-], sem barras/pontos/dois-pontos) já
torna path traversal estruturalmente impossível -- uma string sem
separadores de caminho não tem como virar "..", um caminho absoluto ou
sair da pasta pai. Mesmo assim, os chamadores (page_writer,
visual_writer, layout) também confirmam com
`page_dir.resolve().is_relative_to(pages_dir.resolve())` antes de
escrever, como defesa em profundidade.
"""

from __future__ import annotations

import re
from pathlib import Path

from errors import InvalidPageNameError

_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

_RESERVED_WINDOWS_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def is_valid_object_name(name: str) -> bool:
    """True se `name` é seguro para usar como componente de caminho de
    arquivo em qualquer lugar do PBIR (page_name, visual_name digitado
    por fora, bookmark_name, theme_name, ...) -- mesma regra em todo
    lugar, porque a razão (path traversal + convenção de nomes do PBIR)
    é a mesma independente do tipo de objeto. Não levanta -- quem chama
    decide qual erro específico (com a mensagem certa) levantar."""
    if not _VALID_NAME_RE.match(name):
        return False
    return name.upper() not in _RESERVED_WINDOWS_NAMES


def validate_page_name(page_name: str) -> None:
    """Levanta InvalidPageNameError se `page_name` não for seguro para
    usar como nome de pasta (e não seguir a convenção de nomes do
    PBIR)."""
    if not is_valid_object_name(page_name):
        raise InvalidPageNameError(page_name)


def resolve_page_dir(pages_dir: Path, page_name: str) -> Path:
    """Valida `page_name` e devolve `pages_dir / page_name`, confirmado
    como realmente dentro de `pages_dir` (defesa em profundidade -- o
    regex de validate_page_name já torna escapar estruturalmente
    impossível, mas checar de novo aqui é barato).

    Usada por todo lugar que grava dentro de definition/pages/<page_name>/:
    page_writer.create_report_page, visual_writer.add_visual,
    layout.set_page_layout.
    """
    validate_page_name(page_name)
    page_dir = pages_dir / page_name
    if not page_dir.resolve().is_relative_to(pages_dir.resolve()):
        raise InvalidPageNameError(page_name)
    return page_dir
