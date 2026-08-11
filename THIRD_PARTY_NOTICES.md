# 第三方组件说明

Vision MCP 通过 `requirements.lock` 使用开源 Python 组件。主要直接依赖包括：

| 组件 | 许可证 |
| --- | --- |
| FastMCP | Apache-2.0 |
| Pillow | MIT-CMU |
| keyring | MIT |
| pywebview | BSD-3-Clause |
| PyInstaller | GPL-2.0-or-later，含引导程序例外 |
| pytest | MIT |

完整的直接与间接依赖版本以 `requirements.lock` 为准。各组件版权与许可文本由其上游项目保留；发布二进制前应使用当前锁文件重新核对随包组件及其许可证。
