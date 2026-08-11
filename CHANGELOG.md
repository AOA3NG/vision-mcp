# 更新记录

本项目遵循语义化版本。日期使用 `YYYY-MM-DD`。

## 1.0.1 - 2026-08-11

- 普通识图、UI 分析、OCR、物体定位、文档图片和多图工具在未提供图片来源时自动读取 Windows 剪贴板。
- 比较图片时允许其中一张直接来自剪贴板；继续保留 `analyze_clipboard_image` 兼容旧 Agent。
- 增加 MCP 服务级使用说明，让 Agent 将“这张图”“刚才截图”和“剪贴板 UI”等表达路由到对应视觉工具。
- 剪贴板被截图工具短暂占用时自动重试，并兼容部分截图工具提供的自定义 PNG 剪贴板格式。
- GitHub Actions 更新到官方 `checkout@v7` 与 `setup-python@v7`，构建依赖更新到 PyInstaller 6.21.0。

## 1.0.0 - 2026-08-11

- 新增 `analyze_clipboard_image`，让非多模态 Agent 在不直接粘贴图片的情况下分析 Windows 剪贴板图片。
- 模型请求禁止自动 HTTP 重定向，避免 API Key 或媒体被转发到非配置目标；同时增加请求正文和问答文本长度上限。
- 开源源码包改为逐文件发布清单，不再递归收集目录中的未知文件。
- Agent 高频连续备份使用唯一文件名，并按实际修改时间选择最近备份。
- 构建依赖升级到已修复安全公告的 setuptools 84.0.0 和 pytest 9.1.1。
- 安装器与卸载器通过无控制台窗口的管理器执行隐藏维护命令，避免 Windows Terminal 弹出空白的 `vision-mcp-server.exe` 窗口。
- 覆盖升级时允许安装器强制关闭占用安装文件的旧版管理器或 stdio 服务，避免停在“Closing applications”；安装完成后只按安装器选项启动新版管理器。
- 模型选择支持预设多选和逐个添加自定义模型输入框，不再要求使用逗号分隔。
- 同一服务商支持最多 5 个独立 Windows 凭据槽，按顺序故障转移，并增加请求级尝试与时间预算。
- 智谱默认模型直接显示参考并发限制；新增内置使用说明和包含 GitHub 地址的关于页。
- Trae 检测兼容 `Trae CN`、`TRAE SOLO CN`、`TRAE SOLO`、用户配置目录和当前安装注册信息。
- 新增显式白名单的开源源码打包脚本，发布前检查实际压缩包暂存内容。
- 首个 Windows x64 开源版本。
- 提供 WebView2 管理器、Windows Credential Manager 凭据存储和 stdio MCP 服务。
- 支持智谱、阿里云百炼及自定义 OpenAI/Anthropic 兼容视觉服务。
- 支持 Claude Code、Codex、Cursor、Trae、WorkBuddy 和标准 MCP 手动配置。
- 提供图片、多图、文档页面、目标定位和视频分析工具。
- 同一服务商可在一个配置中选择多个能力模型并共享 API Key；默认勾选两个智谱视觉模型，免费的 CogView/CogVideoX 生成模型保留为可选项但默认不勾选。
- 每组服务商配置只保留一个 API Key；备用 Key 通过新增服务商配置组实现，相同服务商和模型允许使用不同凭据重复配置。
- 新增 `generate_image` 与 `generate_video`，支持文生图、文生视频和图生视频。
- Agent 配置采用备份、冲突保护和原子写入。
