# AiCode for macOS

[![build](https://github.com/cat881/AiCodeMac/actions/workflows/build.yml/badge.svg)](https://github.com/cat881/AiCodeMac/actions/workflows/build.yml)

macOS 上的 AI 编程 Agent 客户端 — 功能对齐 Android 版 [AiCode](https://github.com/jieapi/AiCode)：AI Agent 工具循环、终端、文件编辑器、Git、检查点、MCP、多供应商流式对话、Token 统计。

## 架构

```
 AiCode.app ── WKWebView ──► http://127.0.0.1:<随机端口>
                 ▲                    │
                 │                    ▼
          Swift 外壳 (AppKit)    Python 3 标准库后端 (零第三方依赖)
                                  ├─ Agent 循环 + 11 个内置工具
                                  ├─ OpenAI / Anthropic / Gemini SSE
                                  ├─ PTY 终端 (pty.openpty + zsh -l)
                                  ├─ 文件树 / 编辑器 / Git / 检查点
                                  └─ MCP stdio + HTTP 客户端
```

前端为自建单页应用，依赖已内置于 `web/vendor/`（xterm.js、CodeMirror、marked、DOMPurify、highlight.js），完全离线可用。

## 构建

需要 macOS 12+、Xcode 命令行工具（`xcode-select --install`）。

```bash
bash mac/build.sh          # 产物: build/AiCode.app
open build/AiCode.app
```

GitHub Actions 在每次 push 时用 macOS runner 编译并上传 `AiCode-macos-<arch>.zip` / `.dmg`；打 `v*` tag 会自动发布 Release。

## 开发模式

```bash
python3 server/main.py --port 8765   # 后端
open http://127.0.0.1:8765           # 任意浏览器
```

后端数据位于 `~/Library/Application Support/AiCodeMac`（`AICODE_DATA` 可覆盖），包含 `config.json`、`sessions/`、`checkpoints/`、`stats.jsonl`。

## 首次使用

1. 打开 `设置 → 供应商`，填入 API Key（支持 OpenAI / Anthropic / Gemini，以及 DeepSeek、Moonshot、智谱、通义、OpenRouter、SiliconFlow 预设）。
2. 选择工作区文件夹。
3. 在 `BUILD / PLAN / AUTO` 三种模式中选择运行方式，开始对话。

## 功能

- Agent 工具：读文件、写文件、精确替换编辑、列目录、grep、文件名搜索、Shell、交互终端、待办清单、网页抓取、网页搜索
- 三种模式：`PLAN` 只读规划、`BUILD` 写操作逐次审批、`AUTO` 全自动
- 检查点：每次对话前快照，可回滚单文件
- 上下文压缩：超过阈值自动摘要历史
- 终端：xterm.js + 真实 PTY，SSE 长轮询回传
- Git：状态、暂存、提交、分支切换、diff 查看
- 统计：调用次数、token、按模型费用
- MCP：stdio / HTTP 双传输，工具自动注入 Agent
- 备份：导出 / 导入完整配置与会话

## 许可

GPL-3.0，与原项目一致。
