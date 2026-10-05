"""Localização e validação da pasta .Report (formato PBIR) de um projeto
.pbip.

Só lida com a existência/formato das pastas -- não cria nem escreve
nada. A criação do esqueleto `definition/` (quando a primeira página é
adicionada a um relatório ainda não salvo em PBIR) é responsabilidade de
page_writer.py, que conhece o conteúdo exato de cada arquivo.
"""

from __future__ import annotations

from pathlib import Path

from errors import ReportProjectNotFoundError


def resolve_report_dir(pbip_path: str) -> Path:
    """Localiza a pasta `<Nome>.Report` a partir de `pbip_path`.

    Aceita, nessa ordem de tentativa: o caminho de um arquivo .pbip, a
    pasta raiz do projeto (que contém a pasta `*.Report`), ou já a
    própria pasta `*.Report`.

    Raises:
        ReportProjectNotFoundError: nenhuma pasta `.Report` foi
            encontrada a partir do caminho informado.
    """
    path = Path(pbip_path)

    if path.is_dir() and path.name.endswith(".Report"):
        return path

    if path.is_file() and path.suffix.lower() == ".pbip":
        # Vários projetos podem dividir a mesma pasta: usar o relatório que
        # ESTE .pbip declara (artifacts[].report.path), depois o
        # <nome>.Report do mesmo nome. Antes, o primeiro *.Report em ordem
        # alfabética era usado -- e gravava páginas em outro projeto
        # (achado em 2026-10-03, dashboard Cristallo).
        import json

        try:
            artifacts = json.loads(path.read_text(encoding="utf-8-sig")).get("artifacts", [])
        except (OSError, ValueError, AttributeError):
            artifacts = []
        for artifact in artifacts:
            report_path = artifact.get("report", {}).get("path") if isinstance(artifact, dict) else None
            if report_path and (path.parent / report_path).is_dir():
                return path.parent / report_path
        if path.with_suffix(".Report").is_dir():
            return path.with_suffix(".Report")

    search_dir = path.parent if path.is_file() else path
    if search_dir.is_dir():
        matches = sorted(
            entry
            for entry in search_dir.iterdir()
            if entry.is_dir() and entry.name.endswith(".Report")
        )
        if len(matches) > 1 and path.is_file():
            # o .pbip não aponta pra nenhum deles: adivinhar já gravou em
            # outro projeto (revisão final de 2026-10-03)
            raise ReportProjectNotFoundError(
                f"'{pbip_path}' não declara um relatório existente e a pasta tem "
                f"{len(matches)} relatórios ({', '.join(m.name for m in matches)}). "
                "Informe a pasta .Report desejada."
            )
        if matches:
            return matches[0]

    raise ReportProjectNotFoundError(
        f"Não foi possível encontrar uma pasta .Report a partir de "
        f"'{pbip_path}'. Informe o caminho do arquivo .pbip, da pasta "
        "do projeto, ou da própria pasta .Report."
    )


def has_pbir_definition(report_dir: Path) -> bool:
    """True se `report_dir` já tem uma definição no formato PBIR
    (`definition/pages/` existe)."""
    return (report_dir / "definition" / "pages").is_dir()


def is_legacy_report(report_dir: Path) -> bool:
    """True se `report_dir` está no formato PBIR-Legacy: um
    `report.json` na raiz da pasta .Report (não dentro de definition/,
    que é onde o PBIR moderno o coloca), sem uma definição PBIR."""
    return (report_dir / "report.json").is_file() and not has_pbir_definition(report_dir)


def get_definition_dir(report_dir: Path) -> Path:
    """Devolve `report_dir/definition`, já validada.

    Raises:
        ReportProjectNotFoundError: se o relatório está no formato
            PBIR-Legacy (precisa ser convertido no Power BI Desktop
            primeiro -- ver README, seção "PBIR é um formato em
            preview"), ou se ainda não tem nenhuma definição (relatório
            nunca salvo, nem em PBIR nem em PBIR-Legacy).
    """
    if has_pbir_definition(report_dir):
        return report_dir / "definition"

    if is_legacy_report(report_dir):
        raise ReportProjectNotFoundError(
            f"'{report_dir}' está no formato PBIR-Legacy (report.json na "
            "raiz), não no formato PBIR (pasta definition/). Habilite a "
            "preview feature 'Store reports using enhanced metadata "
            "format (PBIR)' no Power BI Desktop, salve o projeto para "
            "converter, e tente novamente. Veja o README, seção 'PBIR é "
            "um formato em preview'."
        )

    raise ReportProjectNotFoundError(
        f"'{report_dir}' ainda não tem uma definição de relatório "
        "(nem PBIR nem PBIR-Legacy). Abra o projeto no Power BI Desktop "
        "e salve-o ao menos uma vez antes de usar este servidor."
    )
