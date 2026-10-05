"""Testes de modeling.discovery: descoberta de instâncias abertas do
Power BI Desktop lendo msmdsrv.port.txt nas AnalysisServicesWorkspaces.

Nenhum destes testes toca .NET nem precisa do Desktop de verdade -- é
tudo manipulação de arquivos num diretório temporário.
"""

from __future__ import annotations

from pathlib import Path

from modeling.discovery import find_desktop_instances


def _make_workspace(root: Path, workspace_name: str, port: int, encoding: str = "utf-16") -> None:
    data_dir = root / workspace_name / "Data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "msmdsrv.port.txt").write_text(str(port), encoding=encoding)


def test_returns_empty_list_when_root_does_not_exist(tmp_path: Path):
    missing_root = tmp_path / "does-not-exist"
    assert find_desktop_instances(search_root=missing_root) == []


def test_returns_empty_list_when_root_is_empty(tmp_path: Path):
    root = tmp_path / "AnalysisServicesWorkspaces"
    root.mkdir()
    assert find_desktop_instances(search_root=root) == []


def test_finds_single_instance_with_utf16_port_file(tmp_path: Path):
    root = tmp_path / "AnalysisServicesWorkspaces"
    _make_workspace(root, "AnalysisServicesWorkspace_Vendas1234", 51542, encoding="utf-16")

    instances = find_desktop_instances(search_root=root)

    assert len(instances) == 1
    assert instances[0].port == 51542
    assert instances[0].workspace_name == "AnalysisServicesWorkspace_Vendas1234"


def test_finds_multiple_instances_sorted_by_workspace_name(tmp_path: Path):
    root = tmp_path / "AnalysisServicesWorkspaces"
    _make_workspace(root, "AnalysisServicesWorkspace_B", 51600, encoding="utf-8")
    _make_workspace(root, "AnalysisServicesWorkspace_A", 51500, encoding="utf-16")

    instances = find_desktop_instances(search_root=root)

    assert [i.workspace_name for i in instances] == [
        "AnalysisServicesWorkspace_A",
        "AnalysisServicesWorkspace_B",
    ]
    assert [i.port for i in instances] == [51500, 51600]


def test_ignores_workspace_folder_without_port_file(tmp_path: Path):
    root = tmp_path / "AnalysisServicesWorkspaces"
    empty_workspace = root / "AnalysisServicesWorkspace_Empty"
    empty_workspace.mkdir(parents=True)

    assert find_desktop_instances(search_root=root) == []


def test_ignores_port_file_with_non_numeric_content(tmp_path: Path):
    root = tmp_path / "AnalysisServicesWorkspaces"
    data_dir = root / "AnalysisServicesWorkspace_Broken" / "Data"
    data_dir.mkdir(parents=True)
    (data_dir / "msmdsrv.port.txt").write_text("not-a-port", encoding="utf-8")

    assert find_desktop_instances(search_root=root) == []


def test_finds_instance_with_utf16_le_port_file_without_bom(tmp_path: Path):
    """O Power BI Desktop instalado via Microsoft Store escreve
    msmdsrv.port.txt em UTF-16 LE *sem* BOM -- descoberto testando
    contra uma instância real. Path.read_text(encoding="utf-16") exige
    BOM e levantaria UnicodeDecodeError nesse arquivo."""
    root = tmp_path / "AnalysisServicesWorkspaces"
    data_dir = root / "AnalysisServicesWorkspace_SemBOM" / "Data"
    data_dir.mkdir(parents=True)
    (data_dir / "msmdsrv.port.txt").write_bytes("51651".encode("utf-16-le"))

    instances = find_desktop_instances(search_root=root)

    assert len(instances) == 1
    assert instances[0].port == 51651


def test_ignores_stray_file_where_workspace_folder_is_expected(tmp_path: Path):
    root = tmp_path / "AnalysisServicesWorkspaces"
    root.mkdir(parents=True)
    (root / "some_stray_file.txt").write_text("noise", encoding="utf-8")

    assert find_desktop_instances(search_root=root) == []


def test_default_search_root_uses_localappdata_env_var(monkeypatch, tmp_path: Path):
    fake_localappdata = tmp_path / "LocalAppData"
    # isola também a raiz da instalação via Store (USERPROFILE), senão
    # este teste pegaria uma instância de Desktop de verdade rodando na
    # máquina que o executa
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "NenhumaInstalacaoStoreAqui"))
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))
    _make_workspace(
        fake_localappdata / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces",
        "AnalysisServicesWorkspace_X",
        51999,
    )

    instances = find_desktop_instances()

    assert len(instances) == 1
    assert instances[0].port == 51999


def test_default_search_root_also_checks_store_app_install_path(monkeypatch, tmp_path: Path):
    """A instalação do Power BI Desktop via Microsoft Store usa
    %USERPROFILE%\\Microsoft\\Power BI Desktop Store App\\... em vez de
    %LOCALAPPDATA%\\Microsoft\\Power BI Desktop\\... -- descoberto
    inspecionando a linha de comando de um msmdsrv.exe real rodando a
    partir de uma instalação Store."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "NenhumaInstalacaoClassicaAqui"))
    fake_userprofile = tmp_path / "UserProfile"
    monkeypatch.setenv("USERPROFILE", str(fake_userprofile))
    _make_workspace(
        fake_userprofile / "Microsoft" / "Power BI Desktop Store App" / "AnalysisServicesWorkspaces",
        "AnalysisServicesWorkspace_StoreApp",
        51651,
    )

    instances = find_desktop_instances()

    assert len(instances) == 1
    assert instances[0].port == 51651
    assert instances[0].workspace_name == "AnalysisServicesWorkspace_StoreApp"


def test_default_search_root_merges_both_install_paths(monkeypatch, tmp_path: Path):
    fake_localappdata = tmp_path / "LocalAppData"
    fake_userprofile = tmp_path / "UserProfile"
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))
    monkeypatch.setenv("USERPROFILE", str(fake_userprofile))
    _make_workspace(
        fake_localappdata / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces",
        "AnalysisServicesWorkspace_Classic",
        51500,
    )
    _make_workspace(
        fake_userprofile / "Microsoft" / "Power BI Desktop Store App" / "AnalysisServicesWorkspaces",
        "AnalysisServicesWorkspace_Store",
        51600,
    )

    instances = find_desktop_instances()

    assert len(instances) == 2
    assert {i.port for i in instances} == {51500, 51600}



# --- is_port_listening: a porta do workspace ainda tem alguém escutando? -----------


def test_is_port_listening_true_for_an_open_socket():
    import socket

    from modeling.discovery import is_port_listening

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        assert is_port_listening(server.getsockname()[1]) is True


def test_is_port_listening_false_for_a_closed_port():
    import socket

    from modeling.discovery import is_port_listening

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert is_port_listening(free_port) is False
