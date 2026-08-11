# GitHub 发布检查表

## 源码

- [ ] `pyproject.toml`、`vision_mcp/__init__.py`、`packaging/installer.iss` 版本一致。
- [ ] `python scripts/release_check.py` 通过。
- [ ] `python -m pytest` 全部通过。
- [ ] 未提交 `.venv`、`build`、`dist`、`dist-installer`、日志、用户配置、凭据或证书。
- [ ] README、CHANGELOG、LICENSE、SECURITY 和第三方组件说明已更新。

## Windows 产物

- [ ] 使用 Python 3.12 x64 的干净环境执行 `packaging\build.ps1`。
- [ ] 官方发布的 `requirements.lock` 包含经审核的 Windows CPython 3.12 x64 wheel SHA-256；构建使用 `--require-hashes`。
- [ ] `vision-mcp-server.exe protocol-test` 通过，stdout 无诊断污染。
- [ ] 管理器在中文/空格路径、高 DPI 和普通用户权限下通过人工检查。
- [ ] 全新安装、覆盖升级、普通卸载、勾选删除个人数据均通过。
- [ ] 官方发布设置 `VISION_MCP_OFFICIAL_RELEASE=1` 与 `SIGN_CERT_SHA1`，两个程序和安装器的 Authenticode 状态均为 Valid。
- [ ] 最终安装器 SHA-256 与 `.sha256` 文件一致。

## GitHub

- [ ] 只提交源码和必要设计资源；安装器作为 Release asset 上传，不提交到仓库。
- [ ] GitHub Actions 的 Windows Python 3.12 测试通过，Dependabot 告警已检查。
- [ ] 创建签名标签 `v1.0.0`，发布说明引用 CHANGELOG。
- [ ] 上传安装器和 `.sha256`；明确标注签名状态及未完成的真实模型/Agent 验证。
