"""Automação de janela do Windows para acionar "Salvar" (Ctrl+S) no
Power BI Desktop -- e só isso.

Por quê isso existe: TOM/XMLA não tem comando de "salvar arquivo".
`runtime.save_changes()` (`Model.SaveChanges()`) persiste no modelo
*vivo* dentro do processo do Desktop -- não no `.pbip` em disco. Ctrl+S
é uma ação da própria interface do Desktop, fora do que o protocolo
XMLA expõe (ver README, seção "O ciclo salvar / reabrir"). A única
forma de disparar isso de fora é automação de janela: achar a janela
certa e mandar a tecla, como um usuário faria.

Segurança -- a parte que mais importa aqui: só enviamos a tecla se
conseguirmos identificar, SEM AMBIGUIDADE, qual janela do Desktop
corresponde à porta TOM conectada. A cadeia de correlação é:

    porta TOM ativa
      -> workspace_name (via modeling.discovery, mesmo mapeamento que
         connect_to_desktop já usa)
      -> processo msmdsrv.exe cuja linha de comando cita esse workspace
      -> processo pai desse msmdsrv.exe (tem que ser PBIDesktop.exe)

Se qualquer um desses passos não achar exatamente uma correspondência,
recusamos em vez de arriscar mandar Ctrl+S para a janela errada.

ATENÇÃO -- ver README: isso nunca deve ser chamado logo depois de
create_report_page/add_visual/set_page_layout/apply_dashboard_blueprint
terem escrito páginas/visuais. Confirmado ao vivo: o Power BI Desktop
reescreve toda a pasta definition/pages/ do projeto com o que está na
memória dele ao salvar, apagando qualquer página que ainda não tenha
carregado.

`find_desktop_process_id` é a parte pura, testável (recebe a lista de
processos via injeção). `_list_processes` (consulta real ao Windows via
PowerShell) e `send_save_keystroke` (ativa a janela e manda a tecla) são
a fronteira de I/O -- sem cobertura de teste automatizado, mesmo padrão
já usado em modeling.tom_runtime para a fronteira com .NET.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from errors import DesktopSaveFailedError, DesktopWindowNotFoundError
from modeling import connection, discovery

_POWERSHELL_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    """Um processo do Windows, só com os campos que a correlação usa."""

    pid: int
    name: str
    command_line: str
    parent_pid: int


def find_desktop_process_id(
    port: int,
    list_processes: Callable[[], list[ProcessInfo]] = lambda: _list_processes(),
) -> int:
    """Acha o PID do processo PBIDesktop.exe correspondente à `port`
    (a mesma porta que connect_to_desktop usou).

    Raises:
        DesktopWindowNotFoundError: qualquer passo da correlação
            (porta -> workspace -> msmdsrv -> PBIDesktop pai) não achar
            exatamente uma correspondência.
    """
    instance = next((i for i in discovery.find_desktop_instances() if i.port == port), None)
    if instance is None:
        raise DesktopWindowNotFoundError(
            f"Nenhuma instância do Power BI Desktop foi descoberta na porta {port}."
        )

    processes = list_processes()

    msmdsrv_matches = [
        p
        for p in processes
        if p.name.lower() == "msmdsrv.exe" and instance.workspace_name in p.command_line
    ]
    if len(msmdsrv_matches) != 1:
        raise DesktopWindowNotFoundError(
            f"Esperava exatamente um processo msmdsrv.exe para o workspace "
            f"'{instance.workspace_name}' (porta {port}); encontrados: "
            f"{len(msmdsrv_matches)}."
        )

    parent_pid = msmdsrv_matches[0].parent_pid
    parent = next((p for p in processes if p.pid == parent_pid), None)
    if parent is None or parent.name.lower() != "pbidesktop.exe":
        raise DesktopWindowNotFoundError(
            f"O processo pai (PID {parent_pid}) do msmdsrv.exe da porta {port} "
            f"não é o PBIDesktop.exe -- não é seguro identificar a janela."
        )

    return parent.pid


def _list_processes() -> list[ProcessInfo]:
    """Consulta os processos do Windows de verdade, via PowerShell.
    Sem cobertura de teste automatizado nesta máquina."""
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId, Name, CommandLine, ParentProcessId | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=_POWERSHELL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise DesktopWindowNotFoundError(f"Falha ao listar processos do Windows: {result.stderr}")

    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = [data]
    return [
        ProcessInfo(
            pid=item["ProcessId"],
            name=item.get("Name") or "",
            command_line=item.get("CommandLine") or "",
            parent_pid=item.get("ParentProcessId") or 0,
        )
        for item in data
    ]


def send_save_keystroke(pid: int) -> None:
    """Ativa a janela do processo `pid` e manda Ctrl+S.

    Sem cobertura de teste automatizado nesta máquina -- é automação de
    janela real contra um processo real.

    Raises:
        DesktopSaveFailedError: não foi possível ativar a janela, ou o
            PowerShell falhou ao enviar a tecla.
    """
    script = f"""
$ws = New-Object -ComObject WScript.Shell
$activated = $ws.AppActivate({pid})
if (-not $activated) {{
    Write-Error "Não foi possível ativar a janela do processo {pid}."
    exit 1
}}
Start-Sleep -Milliseconds 300
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("^s")
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise DesktopSaveFailedError(
            f"Falha ao ativar a janela (PID {pid}) ou enviar Ctrl+S: {result.stderr}"
        )


def save_desktop() -> dict[str, Any]:
    """Salva (Ctrl+S) o projeto aberto na conexão TOM ativa.

    Raises:
        DesktopNotFoundError: nenhuma conexão ativa (propagado por
            connection.get_active_runtime).
        DesktopWindowNotFoundError: não foi possível identificar, sem
            ambiguidade, a janela correspondente.
        DesktopSaveFailedError: a janela foi identificada, mas ativá-la
            ou enviar Ctrl+S falhou.
    """
    port = connection.get_active_runtime().port
    pid = find_desktop_process_id(port)
    send_save_keystroke(pid)
    return {"port": port, "pid": pid, "action": "Ctrl+S enviado"}
