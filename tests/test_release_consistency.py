import re
from pathlib import Path

from vision_mcp import __version__


def test_release_versions_are_consistent():
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    installer = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    version_info = (root / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
    assert f'#define MyAppVersion "{__version__}"' in installer
    assert f"StringStruct('FileVersion', '{__version__}')" in version_info
    assert f"StringStruct('ProductVersion', '{__version__}')" in version_info
    numeric = tuple(int(part) for part in __version__.split(".")) + (0,)
    assert f"filevers={numeric}" in version_info
    assert f"prodvers={numeric}" in version_info
    assert '#define MyAppPublisher "AOA3NG"' in installer
    assert "StringStruct('CompanyName', 'AOA3NG')" in version_info
    assert "Copyright © AOA3NG" in version_info


def test_installer_force_closes_running_app_during_upgrade():
    root = Path(__file__).parents[1]
    installer = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "CloseApplications=force" in installer
    assert "RestartApplications=no" in installer
    assert "CloseApplications=yes" not in installer
    assert "function PrepareToInstall(var NeedsRestart: Boolean): String;" in installer
    assert "StopInstalledVisionProcesses" in installer
    assert "{app}\\{#MyAppExeName}" in installer
    assert "{app}\\vision-mcp-server.exe" in installer
    assert "taskkill" not in installer.lower()


def test_release_lock_contains_pinned_build_dependencies():
    root = Path(__file__).parents[1]
    lock = (root / "requirements.lock").read_text(encoding="utf-8")
    assert "fastmcp==3.4.6" in lock
    assert "keyring==25.7.0" in lock
    assert "pywebview==6.2.1" in lock
    assert "pyinstaller==6.21.0" in lock
    assert "pytest==9.1.1" in lock
    for line in lock.splitlines():
        if line and not line.startswith("#"):
            assert "==" in line


def test_build_uses_a_unique_temporary_environment():
    root = Path(__file__).parents[1]
    script = (root / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "[Guid]::NewGuid().ToString('N')" in script
    assert '"vision-mcp-build-venv-$PID-' in script
    assert "$ReuseBuildVenv" in script
    assert "} finally {" in script
    assert '$ResolvedLeaf.StartsWith("vision-mcp-build-venv-"' in script


def test_pyinstaller_collects_windows_credential_dependencies():
    root = Path(__file__).parents[1]
    spec = (root / "packaging" / "vision-mcp.spec").read_text(encoding="utf-8")
    assert '"keyring.backends.Windows"' in spec
    assert '"win32timezone"' in spec
    assert '"webview.platforms.edgechromium"' in spec
    assert 'collect_all("jsonschema_specifications")' in spec
    assert "jsonschema_data" in spec
    assert "exclude_binaries=True" not in spec
    assert "COLLECT(" not in spec


def test_release_uses_custom_application_icon():
    root = Path(__file__).parents[1]
    spec = (root / "packaging" / "vision-mcp.spec").read_text(encoding="utf-8")
    installer = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "vision-mcp.ico" in spec
    assert "SetupIconFile=vision-mcp.ico" in installer
    assert (root / "design" / "vision-mcp-icon-source.png").is_file()
    assert (root / "design" / "vision-mcp-icon.png").is_file()


def test_installer_allows_directory_selection_and_defaults_desktop_shortcut():
    root = Path(__file__).parents[1]
    installer = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "DisableDirPage=no" in installer
    assert 'Name: "desktopicon"; Description: "创建桌面快捷方式"' in installer
    desktop_task = next(line for line in installer.splitlines() if line.startswith('Name: "desktopicon"'))
    assert "unchecked" not in desktop_task
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in installer
    assert "--maintenance agent remove all --server" in installer
    assert "function RemoveInstalledAgentEntries(): Boolean;" in installer
    assert "function PrepareUninstallCleanup(): Boolean;" in installer
    assert "AgentEntriesRemoved := RemoveInstalledAgentEntries();" in installer
    assert "ProcessesStopped := StopInstalledVisionProcesses();" in installer
    assert "Result := PrepareUninstallCleanup();" in installer
    assert "[UninstallRun]" not in installer
    assert "--maintenance purge-data" in installer
    assert 'Filename: "{app}\\vision-mcp-server.exe"' not in installer
    assert 'Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"' in installer
    assert (root / "packaging" / "ChineseSimplified.isl").is_file()


def test_web_manager_preserves_agent_selection_and_reserves_results_panel():
    root = Path(__file__).parents[1]
    script = (root / "design" / "vision-mcp-manager.js").read_text(encoding="utf-8")
    html = (root / "design" / "vision-mcp-config-prototype.html").read_text(encoding="utf-8")
    assert "renderAgents(response.state.agents, selected)" in script
    assert "selectedAgentState" in script
    assert "results.scrollIntoView" not in script
    assert ".agent-workspace" in html
    assert 'id="results"' in html
    assert 'id="copyMcpConfig"' in html
    assert 'id="closeManager"' in html
    assert 'id="providerNotice"' not in html
    assert "按排序调用，异常时自动切换" in html
    assert 'id="rateLimitLink"' not in html
    assert "missingKeyMessage" in script
    assert "个服务商未填写 API Key" in script
    assert "重新配置并测试" in script
    assert "close_manager" in script
    assert "open_rate_limit_page" not in script
    assert "#runTest { order: 1; margin-left: auto; }" in html
    assert "#saveOnly { order: 2; }" in html
    assert "#closeManager { order: 3; }" in html
    assert ".more-wrap { position: relative; order: 4; }" in html
