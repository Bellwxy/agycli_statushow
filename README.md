# agycli_statushow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-000000.svg)](https://antigravity.google/docs/cli/statusline)

**Google Antigravity CLI (`agy`) 零虚标实时上下文与性能监控状态栏** —— 参考并基于 [zzusec/agy-statusline](https://github.com/zzusec/agy-statusline) 改造，保留服务端真实压缩阈值解码与增量压缩追踪，并新增 **Git 分支展示、实时 TPS（Tokens/s）监控、窄屏多级自适应折行**，纯 Python 标准库零依赖实现。

---

## 核心特性与改进 (Features)

继承自原版 `agy-statusline` 的核心能力：
- **100% 服务端真实上下文分母**：以 SQLite 只读模式（`?mode=ro`）直接解码 `~/.gemini/antigravity-cli/conversations/<conversation_id>.db` 中服务端每轮下发的 `CheckpointConfig.max_context_tokens`（`gen_metadata` `f1.f9.f10.f4` 与 `executor_metadata` `f10.f2.f5`），取 `min(物理窗口, 服务端上限)`，避免 `1.0M` 物理上限造成的百分比虚标；新会话未首轮落库前自动继承最近会话的服务端上限。
- **静默自动压缩次数与峰值追踪**：通过 `(inode, offset)` 字节游标增量扫描 `transcript.jsonl`，发生过 `CHECKPOINT` 自动压缩时常驻显示 `压缩×N(峰XXXK)`；支持 `/resume` 恢复会话后回溯上一轮上下文与累计输出。
- **缓存命中、输出、费用与红线预警**：展示 Prompt 缓存命中率（`>= 50%` 绿色高亮）、累计输出 token、会话费用（`cost.total_usd`），当上下文占用 `>= 85%` 时触发红色预警 `即将触发压缩`。
- **零外部依赖、叠加不覆盖原生状态栏**：仅依赖 Python 3 标准库，默认开启 `"stack_with_default": true`，在 `agy` 原生状态栏下方追加展示。

相比原版新增的改进（`statushow.py`）：
- **Git 当前分支展示**：优先读取 payload 中的 `worktree.branch` / `git_branch`，兜底从工作目录向上查找 `.git/HEAD`（兼容 worktree / submodule 的 `.git` 文件），无需拉起 `git` 子进程，超长分支名自动截断至 28 字符。
- **实时生成速度（TPS）监控**：增量扫描本地会话库 `steps` 表中已完成的 `PLANNER_RESPONSE`（`step_type = 15, status = 3`），解析 Protobuf 起止时间戳与输出 token 数，展示最新一轮 TPS（`>= 60` 绿、`>= 25` 青、`< 25` 黄）；累计 `>= 2` 轮且非紧凑模式时同时显示会话均值 `TPS XX.X(均XX.X)`。
- **宽字符感知的多级自适应排版**：精确计算含中文在内的终端显示宽度，依据 `terminal_width` 自动在“完整信息 → 紧凑模式 → 隐藏模型名 → 隐藏输出/费用”四级间降级，并支持最多两行平滑折行。

---

## 显示效果 (Preview)

**日常活跃会话：**
```text
◈ Gemini 4 Hydrogen (High) · (main) · 上下文 32.5% (166.4K/512K) · 缓存 94% (152.1K) · 输出 18.2K · TPS 68.5(均61.2)
```

**经历过后台自动压缩的长会话：**
```text
◈ Gemini 4 Hydrogen (High) · (feat/auth) · 上下文 43.4% (222.3K/512K) · 压缩×4(峰511.8K) · 缓存 98% · 输出 420.6K · TPS 54.0(均58.3)
```

**临近服务端自动压缩红线（`>= 85%` 红色预警）：**
```text
◈ Claude Opus 4.5 (High) · (main) · 上下文 88.2% (451.6K/512K) · 缓存 95% (420.1K) · 输出 38.4K · TPS 42.1 · 费用 $1.42 · 即将触发压缩
```

---

## 快速安装 (Quick Start)

### Windows (PowerShell)

克隆本仓库后在项目目录运行：

```powershell
git clone <your-repo-url>
cd agycli_statushow
.\install.ps1
```

安装脚本会自动：
1. 将 `statushow.py` 复制到 `%USERPROFILE%\.gemini\antigravity-cli\statushow.py`
2. 备份现有 `settings.json` 为 `settings.json.bak_statusline`
3. 写入 `statusLine` 配置并启用 `stack_with_default: true`

### macOS / Linux

```bash
git clone <your-repo-url>
cd agycli_statushow
chmod +x install.sh uninstall.sh
./install.sh
```

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

## 致谢与许可 (Credits & License)

- 参考项目：[zzusec/agy-statusline](https://github.com/zzusec/agy-statusline)
- 开源协议：[MIT License](LICENSE)
