# agycli_statushow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-000000.svg)](https://antigravity.google/docs/cli/statusline)

**Google Antigravity CLI (`agy`) Real-time Context & Performance Statusline** —— 直接从本地会话 SQLite 库解码服务端下发的真实压缩阈值（`CheckpointConfig.max_context_tokens`），支持后台自动压缩追踪、Git 分支展示、实时生成速度（TPS）统计与窄屏多级自适应折行，纯 Python 标准库零依赖实现。

> 🌐 English tagline: *A zero-dependency statusline for Google Antigravity CLI that decodes the real server-pushed context limit from local SQLite, tracks silent auto-compactions, and shows live TPS, cache hit rate & session cost.*

---

## 为什么需要它 (Why)

`agy` 原生状态栏展示的上下文占比基于模型物理窗口，而非服务端实际下发的压缩触发阈值，长会话中容易**虚标**——你以为还剩 70%，实际上服务端早已触发静默压缩。本项目通过只读解析本地会话库中的 Protobuf 元数据，还原**真实的**剩余空间，并在逼近压缩红线（`>= 85%`）时提前预警。

---

## 核心特性 (Features)

- **服务端真实上下文阈值解码**：以 SQLite 只读模式（`?mode=ro`）读取 `~/.gemini/antigravity-cli/conversations/<conversation_id>.db` 中服务端下发的 `CheckpointConfig.max_context_tokens`（`gen_metadata` `f1.f9.f10.f4` 与 `executor_metadata` `f10.f2.f5`），取 `min(物理窗口, 服务端上限)` 计算真实占比，避免虚标；新会话首轮落库前自动继承最近会话的服务端上限。
- **静默自动压缩与峰值追踪**：通过 `(inode, offset)` 字节游标增量扫描 `transcript.jsonl`，发生过 `CHECKPOINT` 自动压缩时常驻显示 `压缩×N(峰XXXK)`；支持 `/resume` 恢复会话后回溯上一轮上下文与累计输出。
- **Git 当前分支展示**：优先读取 payload 中的 `worktree.branch` / `git_branch`，兜底沿工作目录向上查找 `.git/HEAD`（兼容 worktree / submodule 的 `.git` 文件），无需拉起 `git` 子进程，超长分支名自动截断至 28 字符。
- **实时生成速度（TPS）监控**：增量扫描本地会话库 `steps` 表中已完成的 `PLANNER_RESPONSE`（`step_type = 15, status = 3`），解析 Protobuf 起止时间戳与输出 token 数，展示最新一轮 TPS（`>= 60` 绿、`>= 25` 青、`< 25` 黄）；累计 `>= 2` 轮且非紧凑模式时同时显示会话均值 `TPS XX.X(均XX.X)`。
- **缓存命中、输出、费用与红线预警**：展示 Prompt 缓存命中率（`>= 50%` 绿色高亮）、累计输出 token、会话费用（`cost.total_usd`），当上下文占用 `>= 85%` 时触发红色预警 `即将触发压缩`。
- **宽字符感知的多级自适应排版**：精确计算含中文在内的终端显示宽度，依据 `terminal_width` 自动在“完整信息 → 紧凑模式 → 隐藏模型名 → 隐藏输出/费用”四级间降级，并支持最多两行平滑折行。
- **零外部依赖、叠加不覆盖原生状态栏**：仅依赖 Python 3 标准库，默认开启 `"stack_with_default": true`，在 `agy` 原生状态栏下方追加展示。

---

## 显示效果 (Preview)

**日常活跃会话：**
```text
◈ Gemini 4 Hydrogen (High) · (main) · context 32.5% (166.4K/512K) · 缓存 94% (152.1K) · 输出 18.2K · TPS 68.5(均61.2)
```

**经历过后台自动压缩的长会话：**
```text
◈ Gemini 4 Hydrogen (High) · (feat/auth) · context 43.4% (222.3K/512K) · 压缩×4(峰511.8K) · 缓存 98% · 输出 420.6K · TPS 54.0(均58.3)
```

**临近服务端自动压缩红线（`>= 85%` 红色预警）：**
```text
◈ Claude Opus 4.5 (High) · (main) · context 88.2% (451.6K/512K) · 缓存 95% (420.1K) · 输出 38.4K · TPS 42.1 · 费用 $1.42 · 即将触发压缩
```

> 实际终端中带 ANSI 颜色：上下文占比随占用率升高呈 青 → 黄 → 红 渐变，TPS 按速度着绿 / 青 / 黄。欢迎 PR 提交真实终端截图 📸

---

## 工作原理 (How It Works)

```text
agy（stdin 下发 JSON payload）
  ├─ model / cost / terminal_width ...      → 直接取自 payload
  ├─ conversations/<id>.db（SQLite 只读）  → Protobuf 解码服务端压缩阈值 + steps 表 TPS 增量扫描
  └─ brain/<id>/.../transcript.jsonl        → (inode, offset) 字节游标增量扫描 CHECKPOINT 压缩计数与峰值上下文
        ↓
  渲染输出（stdout：宽字符感知的多级自适应 ANSI 彩色状态行）
```

| 数据 | 来源 | 读取方式 |
|------|------|----------|
| 真实压缩阈值 | `CheckpointConfig.max_context_tokens` | SQLite `?mode=ro` + 纯 Python Protobuf wire 解码 |
| 压缩次数 / 峰值上下文 | `transcript.jsonl` 的 `CHECKPOINT` / `PLANNER_RESPONSE` 事件 | 字节游标增量扫描，只读新增部分 |
| TPS | `steps` 表已完成步骤（`step_type=15, status=3`） | Protobuf 时间戳 + 输出 token 解析 |
| Git 分支 | payload `worktree.branch` / `.git/HEAD` | 纯文件读取，不拉起子进程 |

---

## 系统要求 (Requirements)

- 已安装并登录 [Google Antigravity CLI](https://antigravity.google/docs/cli/statusline)（`agy`）
- Python 3.8+（仅标准库，无需 pip 安装任何依赖）
- Windows / macOS / Linux 均可

---

## 快速安装 (Quick Start)

### Windows (PowerShell)

克隆本仓库后在项目目录运行：

```powershell
git clone https://github.com/Bellwxy/agycli_statushow.git
cd agycli_statushow
.\install.ps1
```

安装脚本会自动：
1. 将 `statushow.py` 复制到 `%USERPROFILE%\.gemini\antigravity-cli\statushow.py`
2. 备份现有 `settings.json` 为 `settings.json.bak_statusline`
3. 写入 `statusLine` 配置并启用 `stack_with_default: true`

### macOS / Linux

```bash
git clone https://github.com/Bellwxy/agycli_statushow.git
cd agycli_statushow
chmod +x install.sh uninstall.sh
./install.sh
```

> 💡 也可以不运行安装脚本，直接执行 `python statushow.py --install`，脚本会自安装到 `~/.gemini/antigravity-cli/` 并写入配置（首次安装前不覆盖已有 `settings.json.bak_statusline` 备份）。

---

## 手动配置 (Manual Setup)

1. 将 [statushow.py](statushow.py) 复制到 `~/.gemini/antigravity-cli/statushow.py`（Windows 下为 `%USERPROFILE%\.gemini\antigravity-cli\statushow.py`）。
2. 编辑 `~/.gemini/antigravity-cli/settings.json`，添加或更新 `statusLine` 字段：

**Windows 示例：**
```json
{
  "statusLine": {
    "type": "command",
    "command": "python C:\\Users\\<你的用户名>\\.gemini\\antigravity-cli\\statushow.py",
    "enabled": true,
    "stack_with_default": true
  }
}
```

**macOS / Linux 示例：**
```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.gemini/antigravity-cli/statushow.py",
    "enabled": true,
    "stack_with_default": true
  }
}
```

---

## 立即生效与日常命令 (Usage)

- **新开的 `agy` 终端会话**：安装完成后直接运行 `agy` 即可自动生效。
- **当前已打开的 `agy` 窗口**：在输入框执行热加载命令：
  ```text
  /statusline python C:\Users\<你的用户名>\.gemini\antigravity-cli\statushow.py
  ```
  （macOS / Linux 可使用 `/statusline python3 ~/.gemini/antigravity-cli/statushow.py`）
- **临时开关状态栏**：在 `agy` 内输入 `/statusline off` 或 `/statusline on`。

---

## 卸载 (Uninstall)

**Windows (PowerShell)：**
```powershell
.\uninstall.ps1
```

**macOS / Linux：**
```bash
./uninstall.sh
```

卸载后可在仍打开的 `agy` 会话中执行 `/statusline delete` 清除当前窗口状态栏。

---

## 常见问题 (FAQ)

**Q1：新会话第一轮显示“上限 512K”，和实际不符？**
服务端阈值在第一轮对话完成后才落库。此前本工具自动继承最近会话的服务端上限；发送第一条消息后即自动刷新为真实值。

**Q2：为什么占比和 agy 原生状态栏不一致？**
这是预期行为。本工具以服务端下发的 `CheckpointConfig.max_context_tokens` 为准，取 `min(模型物理窗口, 服务端上限)` 计算，而原生状态栏基于物理窗口，长会话中会虚标。

**Q3：没有显示 TPS / 费用？**
TPS 需要至少一个已完成的 `PLANNER_RESPONSE` 步骤；费用依赖 payload 中的 `cost.total_usd` 字段，agy 未下发时不显示。

**Q4：Windows 提示找不到 Python？**
安装脚本会依次探测 `python` / `python3` / `py`。请确认 Python 3.8+ 已安装并加入 PATH，或使用 `py` 启动器。

**Q5：修改了仓库源码，状态栏没变化？**
安装时会将脚本复制到 `~/.gemini/antigravity-cli/statushow.py`，修改源码后需重新执行 `install.ps1` / `install.sh`，或在已打开的 `agy` 会话中重新执行一次 `/statusline` 命令。

---

## 隐私说明 (Privacy)

- 全程**只读**：以 SQLite `?mode=ro` 打开会话库，绝不写入 agy 的任何数据文件
- **无网络请求**：不联网、不上报，所有数据均留在本机
- 唯一写入的是自身性能缓存 `%TEMP%/agy_ctx_status_<uid>.json`（卸载脚本会自动清理）

---

## 开发与调试 (Development)

无需真实会话即可本地调试，直接向 stdin 喂入模拟 payload：

```bash
echo '{"model":{"display_name":"Gemini 4 Hydrogen","effort":"High"},"terminal_width":120,"context_window":{"context_window_size":512000,"used_percentage":32.5,"current_usage":{"input_tokens":80000,"cache_read_input_tokens":80000,"cache_creation_input_tokens":6000,"output_tokens":400}},"cost":{"total_usd":0.42},"conversation_id":"","transcript_path":""}' | python statushow.py
```

项目结构：

```text
├── statushow.py        # 核心脚本：渲染 + Protobuf 解码 + SQLite/JSONL 增量扫描
├── install.ps1 / .sh   # 一键安装（复制脚本 + 写入 settings.json）
├── uninstall.ps1 / .sh # 一键卸载（清理脚本、配置与缓存）
└── LICENSE
```

---

## 贡献 (Contributing)

- 欢迎 Issue / PR：Bug 报告、新字段解码、终端截图、排版优化均可
- 提交 PR 前请确保 `python statushow.py < 模拟 payload` 可正常渲染，且未引入任何第三方依赖

---

## License

[MIT License](LICENSE) © 2026 Bellwxy
