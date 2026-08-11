# Vision MCP

开发者：AOA3NG

让 Claude Code、Codex、Cursor、Trae 和 WorkBuddy 等 Agent 获得视觉理解、图片生成和视频生成能力。

正式版面向 Windows 10/11 x64 普通用户：安装包已经包含 Python 和全部依赖，不需要安装 Python、运行 pip、配置端口或启动后台服务。管理器使用 Windows WebView2 显示本地页面；安装器会检测 WebView2 Runtime，缺失时通过随安装包提供且经过 Microsoft 签名校验的 Evergreen 引导程序完成安装。

## 普通用户使用

1. 双击 `VisionMCP-Setup-1.0.1-x64.exe`，按提示安装。
2. 打开“Vision MCP 管理器”。
3. 选择服务商、勾选所需模型并填写 API Key。每组服务商配置对应一个 Key；如需多个 Key 备用，请点击“添加服务商”增加配置组。同一服务商和相同模型可以重复添加，各组凭据相互独立。全新安装默认启用智谱 `glm-4.6v-flash` 和 `glm-4.1v-thinking-flash`，按顺序用于视觉理解和自动备用。`cogview-3-flash` 与 `cogvideox-flash` 会显示在模型选择中，但默认不勾选，需要生成图片或视频时再手动启用。
4. 勾选要接入的 Agent，点击“一键配置并测试”。
5. 重启对应 Agent 后即可识图。列表外的 Agent 可使用“复制 MCP 配置”手动接入。

覆盖升级时，安装器会关闭正在占用安装文件的旧版管理器和 stdio 服务进程，未保存的页面编辑会丢失，请先点击“仅保存”。安装结束后可通过完成页选项打开新版管理器；正在使用 Vision MCP 的 Agent 需要重新发起工具调用。

API Key 分别保存在 Windows 凭据管理器；前一组服务商的 Key 无效、无权限、达到频率限制或临时不可用时，程序会在受控的请求预算内继续尝试后续配置组。非敏感配置位于 `%APPDATA%\VisionMCP\config.json`。管理器加载内置 HTML/CSS 并通过受限的 JavaScript/Python 桥调用本地功能，不启动本地 Web 服务。Agent 通过 stdio 按需启动 `vision-mcp-server.exe`，没有后台服务、监听端口或开机自启项。
程序会校验 keyring 实际使用 `Windows Credential Manager` 后端；若系统策略或依赖导致后端不可用，会明确报错而不会回退到明文文件。

## MCP 工具

- `analyze_image`：通用图片、截图、图表和照片分析；未提供图片路径时自动读取 Windows 剪贴板。
- `analyze_clipboard_image`：显式读取 Windows 剪贴板图片的兼容工具；通常直接调用其他图片工具并省略路径即可。
- `analyze_ui`：结构化分析页面布局、组件、文字、颜色和间距；未提供路径时读取剪贴板。
- `extract_text`：按阅读顺序提取可见文字；未提供路径时读取剪贴板。
- `compare_images`：对比设计稿、实现截图或修改前后差异，其中一张可来自剪贴板。
- `analyze_images`：对 1～12 张图片进行比较、关联推理和通用多图问答；未提供列表时读取剪贴板。
- `analyze_document`：分析一页或多页文档图片，支持 OCR、表格、公式、版面和跨页问答。
- `locate_objects`：识别、定位并计数指定物体，返回归一化边界框 JSON。
- `analyze_video`：分析本地小视频或 HTTPS 视频，支持摘要、问答、关键事件和时间线。
- `generate_image`：仅在勾选图片生成模型后提供；文生图并返回模型名称和 HTTPS 图片地址。
- `generate_video`：仅在勾选视频生成模型后提供；支持文生视频或图生视频，并返回视频与封面地址。

`generate_image` 和 `generate_video` 会随每次 stdio 启动读取当前配置。未勾选对应能力时不会出现在 Agent 的工具列表中，避免误调用必然失败的工具。
- `get_config`：查看不含凭据的模型链状态。

支持 JPEG、PNG、WebP 和 GIF 图片，以及 MP4、M4V、MOV、WebM 视频。本地视频上限为 7MB，更大视频需要使用模型服务商可访问的 HTTPS URL。输入会验证真实格式、文件大小和像素数；图片在上传前统一按像素重新编码并移除 EXIF/XMP 等隐藏元数据。图片和视频内容会离开本机，使用前请确认相应模型提供商的隐私条款。MCP 调用方可以指定本地路径，因此只应连接可信 Agent；自定义 API 地址也必须是可信 HTTPS 服务。

Claude Code 等 Agent 使用非视觉基础模型时，直接粘贴图片会先由基础模型处理，可能在调用 MCP 前就报“不支持图片输入”。使用 Snipaste 等工具截图后，请保留图片在剪贴板中但不要在 Agent 输入框按 `Ctrl+V`，直接输入“看下这张图片”“分析下刚才截图的 UI”或“提取剪贴板图片文字”。当没有文件路径或图片 URL 时，Vision MCP 的普通识图、UI 分析、OCR、物体定位、文档图片和多图工具会自动读取当前 Windows 剪贴板。位图只会写入临时目录并在本次调用结束后删除，资源管理器中复制的原图片文件不会被修改。

智谱和阿里云百炼的 OpenAI 兼容通道均支持常用的图片描述、视觉问答、OCR/信息抽取、多图理解、文档页面分析、目标定位与计数和视频理解。阿里云百炼 Coding Plan 的 `qwen3.7-plus` 可接收图片、文本和视频，但只输出文本，因此用于视觉理解，不用于图片或视频生成；百炼的 Qwen-Image、万相等生成模型使用不同的模型与生成接口，当前版本尚未接入。当前生成协议已接入智谱：`cogview-3-flash` 用于图片生成，`cogvideox-flash` 用于视频生成；其他服务商仍可配置视觉理解模型，但只有明确接入相应生成协议后才会用于生成工具。智谱公开的图片生成接口未提供水印控制参数；视频生成接口允许已在平台签署免责声明的账号关闭水印，当前版本为兼容普通账号仍按平台默认要求保留水印。实际效果、任务耗时以及限流额度取决于模型和账号。当前参考并发为 GLM-4.6V-Flash 1、GLM-4.1V-Thinking-Flash 5、CogView-3-Flash 1、CogVideoX-Flash 3，请以账号速率限制页面为准。上游的流式输出和原生 Function Calling 不作为独立 MCP 工具暴露：外层 Agent 负责工具编排，Vision MCP 返回完整结果。原始 PDF/Office 文件目前需先转为页面图片。

## 命令行

安装后的服务程序提供稳定接口：

```powershell
vision-mcp-server.exe stdio
vision-mcp-server.exe check-config
vision-mcp-server.exe protocol-test
vision-mcp-server.exe self-test [--provider UUID]
vision-mcp-server.exe agent configure|remove|status claude|codex|cursor|trae|workbuddy|all
```

开发环境可用 `python vision_server.py <命令>`，需要 Python 3.11 或 3.12。

## 开发与测试

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.lock
.venv\Scripts\pytest
```

测试覆盖配置原子写入、多个 Windows 凭据槽、Agent 配置保护、新旧 Trae 路径检测、WebView2 桥接与凭据脱敏、中文/空格路径、图片验证、备用链错误分类、请求预算和 JSON 输出校验。

## 构建 Windows 安装器

安装 Python 3.12 和 Inno Setup 6，然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

维护者也可以在 GitHub Actions 中手动运行 `build-windows`，由干净的 Windows Server 2022 / Python 3.12 x64 环境执行同一构建脚本，并下载未签名安装器 artifact；工作流不会自动创建或覆盖 Release。

构建脚本只接受 Python 3.12 x64，每次删除并重建临时构建环境，按 `requirements.lock` 安装后先运行测试，再用 PyInstaller 生成两个程序，最后输出当前用户免管理员安装器到 `dist-installer`。脚本会自动查找当前用户或系统安装的 Inno Setup 6；设置 `ISCC_PATH` 可覆盖路径。设置签名证书指纹 `SIGN_CERT_SHA1` 后，两个程序和安装器都会执行 SHA-256 代码签名及时间戳签名；任何一步失败都会终止构建。

更新检查默认关闭。正式发布构建时通过 `VISION_MCP_RELEASES_API` 配置 GitHub Releases latest API 地址。

## 数据安全

- 修改 Agent 配置前会验证原文件并创建时间戳备份，每款 Agent 最多保留最近 5 份。
- 无效 JSON/TOML、同名配置冲突或写入后校验失败时不会覆盖原文件。
- “从 Agent 移除”和卸载只删除 command 指向当前安装程序的 `vision` 条目。
- 卸载默认保留模型配置和凭据；卸载窗口可选择同时删除应用数据、Windows 凭据和旧 `%APPDATA%\vision-mcp` 凭据迁移文件。
- 日志不得包含 API Key、Authorization 请求头、图片内容或完整第三方错误正文。

旧 `%APPDATA%\vision-mcp\keys.json` 迁移成功后会保留一个由当前 Windows 用户 DPAPI 加密的恢复备份，不再保留明文 Key。更多数据流与信任边界见 [SECURITY.md](SECURITY.md)。

## 开源与贡献

项目主页：[github.com/AOA3NG/vision-mcp](https://github.com/AOA3NG/vision-mcp)。源码采用 [MIT License](LICENSE)。贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)；漏洞请按 [SECURITY.md](SECURITY.md) 私密报告。第三方组件许可证摘要见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

提交或打包前建议执行：

```powershell
python scripts\release_check.py
python -m pytest
powershell -ExecutionPolicy Bypass -File packaging\package-source.ps1
```

`dist-installer` 中的安装器是 GitHub Release 附件，不应提交到源码仓库。官方发布应设置 `VISION_MCP_OFFICIAL_RELEASE=1` 和 `SIGN_CERT_SHA1`；没有证书的构建必须明确标记为未签名安装包。完整流程见 [发布检查表](docs/RELEASE_CHECKLIST.md)，其余维护文档见 [docs](docs/README.md)。
