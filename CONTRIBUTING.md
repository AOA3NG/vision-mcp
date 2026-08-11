# 参与贡献

感谢参与 Vision MCP。提交前请先搜索已有 Issue；较大的行为变更建议先开 Issue 说明使用场景，避免破坏配置格式、凭据兼容性和 Agent 配置保护。

## 本地环境

需要 Windows 10/11 x64、Python 3.12 x64。安装 Inno Setup 6 仅在构建安装器时需要。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pytest
```

## 提交要求

- 不得提交真实 API Key、用户配置、日志、媒体文件、本机绝对路径、签名证书或构建缓存。
- 不得通过删除测试或降低断言绕过失败。
- Agent 配置读写必须保持原子性；解析或写入失败时原文件字节级不变。
- stdout 仅用于 MCP 协议，诊断信息写入 stderr 或日志。
- UI 后台线程不得直接操作 WebView/Tkinter 控件。
- 新功能应补充回归测试，并更新 README 或对应文档。

提交 Pull Request 前运行：

```powershell
.venv\Scripts\python scripts\release_check.py
.venv\Scripts\python -m pytest
```
