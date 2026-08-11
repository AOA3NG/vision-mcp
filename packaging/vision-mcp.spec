# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

root = os.path.dirname(SPECPATH)

fastmcp_data, fastmcp_bins, fastmcp_hidden = collect_all("fastmcp")
keyring_data, keyring_bins, keyring_hidden = collect_all("keyring")
webview_data, webview_bins, webview_hidden = collect_all("webview")
jsonschema_data, jsonschema_bins, jsonschema_hidden = collect_all("jsonschema_specifications")
hidden = fastmcp_hidden + keyring_hidden + jsonschema_hidden + ["keyring.backends.Windows", "win32timezone", "PIL._tkinter_finder", "PIL.ImageGrab"]
manager_hidden = hidden + webview_hidden + ["clr", "webview.platforms.winforms", "webview.platforms.edgechromium"]
version_info = os.path.join(root, "packaging", "version_info.txt")
app_icon = os.path.join(root, "packaging", "vision-mcp.ico")
manager_assets = [
    (os.path.join(root, "design", "vision-mcp-config-prototype.html"), "design"),
    (os.path.join(root, "design", "vision-mcp-manager.js"), "design"),
    (os.path.join(root, "design", "vision-mcp-icon.png"), "design"),
]

server_a = Analysis(
    [os.path.join(root, "vision_server.py")], pathex=[root], binaries=fastmcp_bins + keyring_bins,
    datas=fastmcp_data + keyring_data + jsonschema_data, hiddenimports=hidden,
    excludes=[], noarchive=False,
)
server_pyz = PYZ(server_a.pure)
server = EXE(
    server_pyz, server_a.scripts, server_a.binaries, server_a.datas, [],
    name="vision-mcp-server", console=True, disable_windowed_traceback=False, version=version_info, icon=app_icon,
)

manager_a = Analysis(
    [os.path.join(root, "vision_manager.py")], pathex=[root], binaries=fastmcp_bins + keyring_bins + webview_bins,
    datas=fastmcp_data + keyring_data + jsonschema_data + webview_data + manager_assets, hiddenimports=manager_hidden,
    excludes=[], noarchive=False,
)
manager_pyz = PYZ(manager_a.pure)
manager = EXE(
    manager_pyz, manager_a.scripts, manager_a.binaries, manager_a.datas, [],
    name="Vision MCP 管理器", console=False, disable_windowed_traceback=False, version=version_info, icon=app_icon,
)
