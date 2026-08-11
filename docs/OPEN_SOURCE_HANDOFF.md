# GitHub 开源维护

预期仓库地址：<https://github.com/AOA3NG/vision-mcp>

仓库只提交源码、文档、测试和设计资源；安装器通过 GitHub Release 分发。

## 维护者发布步骤

1. 运行 `python scripts/release_check.py`、`python -m pytest` 和 `powershell -ExecutionPolicy Bypass -File packaging\package-source.ps1`。源码打包脚本只复制明确允许发布的内容，并检查实际压缩包暂存目录。
2. 审阅 LICENSE、SECURITY、CONTRIBUTING、第三方组件说明和发布清单。
3. 只提交 `packaging/source-manifest.txt` 明确列出的文件；不要强制添加被 `.gitignore` 排除的内容。
4. 将 `dist-installer` 中的安装器与 `.sha256` 作为 GitHub Release asset 上传，而不是提交到 Git 历史。
5. 为正式发布生成包含 Windows CPython 3.12 x64 wheel 哈希的 `requirements.lock`，并使用签名证书执行官方发布模式。
6. 检查 GitHub Actions、Dependabot 和 Private vulnerability reporting 状态。

## 当前产物说明

现有 `dist-installer` 产物是未签名测试包，用于功能验收。没有 Authenticode 证书时不要将其描述为经过发布者身份验证的正式安装器。
