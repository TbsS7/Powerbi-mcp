"""Testes de modeling.desktop_automation: correlação entre a porta TOM
conectada e o processo PBIDesktop.exe correspondente.

`find_desktop_process_id` é a parte pura e testável (recebe a lista de
processos via injeção); a consulta real ao SO (`_list_processes`) e o
envio de fato da tecla (`send_save_keystroke`) são a fronteira de I/O
com o Windows -- sem cobertura de teste automatizado, mesmo padrão já
usado em modeling.tom_runtime para a fronteira com .NET.
"""

from __future__ import annotations

import pytest

from errors import DesktopWindowNotFoundError
from modeling import desktop_automation
from modeling.desktop_automation import ProcessInfo, find_desktop_process_id
from modeling.discovery import DesktopInstance

WORKSPACE = "AnalysisServicesWorkspace_174eb94b-f265-4382-b61c-722b87b0935e"


def _msmdsrv(pid: int, workspace: str, parent_pid: int) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name="msmdsrv.exe",
        command_line=(
            f'"C:\\...\\msmdsrv.exe" -c -n {workspace} '
            f'-s "C:\\Users\\...\\{workspace}\\Data"'
        ),
        parent_pid=parent_pid,
    )


def _pbidesktop(pid: int) -> ProcessInfo:
    return ProcessInfo(pid=pid, name="PBIDesktop.exe", command_line="...\\pbidesktop.exe", parent_pid=1)


@pytest.fixture(autouse=True)
def _fake_discovery(monkeypatch):
    monkeypatch.setattr(
        desktop_automation.discovery,
        "find_desktop_instances",
        lambda: [DesktopInstance(port=51651, workspace_name=WORKSPACE)],
    )


def test_finds_pid_when_exactly_one_clean_match():
    processes = [_msmdsrv(pid=200, workspace=WORKSPACE, parent_pid=999), _pbidesktop(999)]

    pid = find_desktop_process_id(51651, list_processes=lambda: processes)

    assert pid == 999


def test_raises_when_port_was_not_discovered(monkeypatch):
    monkeypatch.setattr(desktop_automation.discovery, "find_desktop_instances", lambda: [])

    with pytest.raises(DesktopWindowNotFoundError):
        find_desktop_process_id(51651, list_processes=lambda: [])


def test_raises_when_no_msmdsrv_process_matches_the_workspace():
    processes = [_msmdsrv(pid=200, workspace="OutroWorkspace_diferente", parent_pid=999), _pbidesktop(999)]

    with pytest.raises(DesktopWindowNotFoundError):
        find_desktop_process_id(51651, list_processes=lambda: processes)


def test_raises_when_multiple_msmdsrv_processes_match():
    processes = [
        _msmdsrv(pid=200, workspace=WORKSPACE, parent_pid=999),
        _msmdsrv(pid=201, workspace=WORKSPACE, parent_pid=998),
        _pbidesktop(999),
        _pbidesktop(998),
    ]

    with pytest.raises(DesktopWindowNotFoundError):
        find_desktop_process_id(51651, list_processes=lambda: processes)


def test_raises_when_parent_process_is_not_pbidesktop():
    processes = [
        _msmdsrv(pid=200, workspace=WORKSPACE, parent_pid=999),
        ProcessInfo(pid=999, name="explorer.exe", command_line="...", parent_pid=1),
    ]

    with pytest.raises(DesktopWindowNotFoundError):
        find_desktop_process_id(51651, list_processes=lambda: processes)


def test_raises_when_parent_process_id_is_not_in_the_list():
    processes = [_msmdsrv(pid=200, workspace=WORKSPACE, parent_pid=999)]  # PID 999 não existe na lista

    with pytest.raises(DesktopWindowNotFoundError):
        find_desktop_process_id(51651, list_processes=lambda: processes)
