"""Descoberta de instâncias abertas do Power BI Desktop.

Cada relatório aberto no Power BI Desktop roda seu próprio motor local de
Analysis Services (msmdsrv.exe) numa porta TCP aleatória, anotada em
AnalysisServicesWorkspaces\\<workspace>\\Data\\msmdsrv.port.txt. Este
módulo só lê esses arquivos -- nenhuma linha aqui toca .NET ou XMLA, por
isso é testável com um diretório temporário comum.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

PORT_FILE_ENCODINGS = ("utf-16-le", "utf-16", "utf-8", "utf-8-sig")
# utf-16-le vem primeiro: é o que uma instalação real do Power BI
# Desktop (testado com a versão via Microsoft Store) escreve -- UTF-16
# little-endian *sem* BOM. Path.read_text(encoding="utf-16") sozinho
# levanta UnicodeDecodeError nesse caso, porque a variante genérica
# "utf-16" do Python exige BOM para decidir a ordem de bytes; "utf-16-le"
# não precisa dele. Mantemos "utf-16" (com BOM) na lista também, caso
# outra forma de instalação escreva o arquivo diferente.


@dataclass(frozen=True, slots=True)
class DesktopInstance:
    """Uma instância do Power BI Desktop encontrada localmente."""

    port: int
    workspace_name: str


def default_workspaces_root() -> Path:
    """Diretório onde a instalação clássica do Power BI Desktop (MSI /
    instalador .exe da Microsoft) cria uma pasta por instância aberta."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    return Path(local_app_data) / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces"


def store_app_workspaces_root() -> Path:
    """Diretório equivalente para a instalação via Microsoft Store.

    Descoberto inspecionando a linha de comando de um msmdsrv.exe real:
    a instalação Store roda com `-s "...Power BI Desktop Store
    App\\AnalysisServicesWorkspaces\\..."`, sob %USERPROFILE%, não sob
    %LOCALAPPDATA%\\Microsoft\\Power BI Desktop\\ como a instalação
    clássica."""
    user_profile = os.environ.get("USERPROFILE", "")
    return (
        Path(user_profile)
        / "Microsoft"
        / "Power BI Desktop Store App"
        / "AnalysisServicesWorkspaces"
    )


def default_workspaces_roots() -> list[Path]:
    """As raízes conhecidas onde alguma instalação do Power BI Desktop
    pode ter criado workspaces -- checadas ambas, porque não há como
    saber de antemão qual forma de instalação (clássica ou Store) o
    usuário tem."""
    return [default_workspaces_root(), store_app_workspaces_root()]


def find_desktop_instances(search_root: Path | None = None) -> list[DesktopInstance]:
    """Varre `search_root` (ou, se omitido, todas as raízes conhecidas --
    ver default_workspaces_roots) por instâncias abertas do Power BI
    Desktop.

    Ordena por nome de workspace para um resultado determinístico. Pastas
    sem `Data/msmdsrv.port.txt`, ou com conteúdo não numérico nesse
    arquivo, são silenciosamente ignoradas -- são o retrato normal de um
    workspace que já foi fechado ou está sendo criado.
    """
    roots = [search_root] if search_root is not None else default_workspaces_roots()

    instances: list[DesktopInstance] = []
    for root in roots:
        if not root.is_dir():
            continue
        for workspace_dir in sorted(root.iterdir(), key=lambda p: p.name):
            if not workspace_dir.is_dir():
                continue
            port = _read_port_file(workspace_dir / "Data" / "msmdsrv.port.txt")
            if port is None:
                continue
            instances.append(DesktopInstance(port=port, workspace_name=workspace_dir.name))

    return sorted(instances, key=lambda i: i.workspace_name)


def is_port_listening(port: int, timeout: float = 0.5) -> bool:
    """A porta do workspace ainda tem um motor escutando? Achado no uso
    (2026-09-30): a pasta de um Desktop que já foi fechado (ex: fechado
    de forma abrupta) pode ficar pra trás com o msmdsrv.port.txt --
    connect_to_desktop chegou a listar 3 instâncias com só 1 aberta.
    Conferido ao vivo: a instância viva aceita conexão em milissegundos
    (127.0.0.1 e ::1); porta sem ninguém é recusada na hora."""
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _read_port_file(port_file: Path) -> int | None:
    if not port_file.is_file():
        return None
    for encoding in PORT_FILE_ENCODINGS:
        try:
            raw = port_file.read_text(encoding=encoding)
        except (OSError, UnicodeError):
            continue
        text = raw.strip().strip("\x00").lstrip("﻿")
        if text.isdigit():
            return int(text)
    return None
