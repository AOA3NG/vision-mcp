# 安全策略

## 支持范围

当前维护 `1.0.x`。安全修复会进入最新补丁版本；旧安装包不保证继续获得修复。

## 报告漏洞

请优先使用 GitHub 仓库的 **Security → Report a vulnerability** 私密报告入口。不要在公开 Issue 中提交 API Key、个人配置、图片、日志或可直接利用的漏洞细节。报告请包含受影响版本、复现条件、影响和最小化的证明材料。

项目维护者会尽快确认收到报告，并在完成复现和修复协调后公开说明。请在修复发布前避免公开披露。

## 信任边界

- Vision MCP 仅使用本地 stdio，不监听网络端口，也不安装后台服务。
- MCP 调用方可以要求读取本地媒体路径，并把处理后的内容发送给用户配置的第三方模型。只应连接可信 Agent，并遵守模型服务商的隐私条款。
- 自定义 API 地址拥有接收媒体和 API Key 所授权请求的能力，只能填写可信的 HTTPS 服务。
- API Key 存储在 Windows Credential Manager。旧版明文凭据迁移备份使用当前 Windows 用户的 DPAPI 加密。
- Agent 配置备份可能包含个人路径和第三方 Agent 自有设置；程序只保留最近 5 份。

## 发布安全

官方 GitHub Release 应使用已签名的 Windows 安装器。构建时设置 `VISION_MCP_OFFICIAL_RELEASE=1` 和 `SIGN_CERT_SHA1`，脚本会在缺少证书或签名验证失败时终止。无签名产物只能标记为测试构建。
