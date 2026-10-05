# OpenSpec 工作指南

本项目采用 [OpenSpec](https://github.com/Fission-AI/OpenSpec) 规格驱动开发：**先约定规格，再写代码**。本文件面向在本仓库工作的 AI 助手。

## 目录结构

```
openspec/
├── AGENTS.md          ← 本文件（工作流程）
├── project.md         ← 项目上下文（目的、技术栈、约定）
├── specs/             ← 已达成共识的能力规格（事实之源）
│   └── <capability>/
│       ├── spec.md        # 需求与行为（必含 WHEN/THEN 场景）
│       └── design.md      # 技术设计（可选）
└── changes/           ← 进行中的变更提案
    ├── <change-id>/
    │   ├── proposal.md    # 为什么改、改什么
    │   ├── tasks.md       # 实施任务清单（复选框）
    │   ├── design.md      # 技术方案（可选，复杂变更必写）
    │   └── specs/         # 规格增量（delta），按 capability 分目录
    └── archive/           ← 已完成并合并回 specs/ 的变更
```

## 何时需要走 OpenSpec 流程

需要建变更提案（change）：
- 新增能力（新 MCP 工具、新 Odoo 模型/字段、新鉴权机制等）
- 破坏性行为变更（接口签名、环境变量语义、鉴权方式改变）
- 架构调整（传输方式、部署链路、依赖主版本升级）

可以直接改、不必提案：
- bug 修复、拼写/文案修正、不改行为的重构
- 依赖补丁级升级、注释/文档润色
- 恢复既有行为（让实现重新符合 spec）

## 跨项目变更（与 codebuddyOauth 联动）

本项目与 `codebuddyOauth`（`/Users/ruixin/Desktop/demo演示/codebuddyOauth`）通过 `mcp-oauth.code-workspace` 组成 multi-root 工作区，两侧各有独立 `openspec/`。凡横跨两侧的变更（如 OAuth 鉴权改造）：

- 两侧各建一个 change 提案，`<change-id>` 尽量一致（如都叫 `add-oauth-login`）。
- 本侧 proposal.md 的 `## Impact` 必须引用对侧提案路径。
- 两侧 `tasks.md` 的联调相关任务标注依赖关系（如"依赖对侧任务 2.1 完成"）。
- 归档时机可以不同步，但接口契约类 spec（token 格式、端点约定）两侧必须一致。

## 三阶段流程

### 阶段 1：创建变更提案（Proposal）

1. 先读 `openspec/project.md` 和相关 `openspec/specs/*/spec.md`，了解现状。
2. 在 `openspec/changes/<change-id>/` 下建提案，`<change-id>` 用动词开头的 kebab-case：`add-oauth-login`、`update-mcp-auth-middleware`、`remove-sse-transport`。
3. 写三个核心文件：
   - **proposal.md**：`## Why`（动机/问题）、`## What Changes`（变更点列表）、`## Impact`（受影响的 specs / 代码 / 配置）。
   - **tasks.md**：可勾选清单 `## 1. xxx` / `- [ ] 1.1 …`，顺序即实施顺序。
   - **specs/<capability>/spec.md**：规格**增量**，用小节标注变更类型：
     - `## ADDED Requirements`（新增需求）
     - `## MODIFIED Requirements`（修改既有需求——必须给出修改后的完整需求文本）
     - `## REMOVED Requirements`（移除，并说明迁移/兼容方案）
4. 复杂变更（跨模块、有替代方案权衡、安全相关）另写 `design.md`：Context / Goals & Non-Goals / Decisions / Risks。
5. 提案需用户确认后再进入实施。

### 规格写法约定

- 每个需求一个小节：`#### Requirement: <名称>`，正文用 **SHALL / MUST** 表述强制行为。
- 每个需求至少一个场景：
  ```
  #### Scenario: <场景名>
  - **WHEN** <触发条件>
  - **THEN** <期望行为>
  - **AND** <附加期望>（可选）
  ```
- 写行为不写实现；一个 spec 文件聚焦一个 capability（如 `mcp-auth`、`mrp-tools`、`odoo-connection`）。

### 阶段 2：实施（Implement）

- 按 `tasks.md` 顺序实施，完成一项勾掉一项（`- [x]`）。
- 实现必须与增量 spec 一致；实施中发现 spec 有误，先改 spec 再改代码。
- 全部任务完成且验证通过后进入归档。

### 阶段 3：归档（Archive）

1. 把 `changes/<id>/specs/` 中的增量**合并进** `openspec/specs/<capability>/spec.md`：
   - ADDED → 追加新需求；MODIFIED → 替换旧需求全文；REMOVED → 删除。
2. 将整个 `changes/<id>/` 移入 `changes/archive/`（可加日期前缀，如 `2026-10-05-add-oauth-login`）。
3. 归档后 `specs/` 即最新事实之源。

## 快速检查清单

- [ ] 改动是否属于"需要提案"的范畴？是 → 先建 change
- [ ] `proposal.md` 是否说清 Why / What / Impact？
- [ ] 每个 Requirement 是否都有 WHEN/THEN 场景？
- [ ] MODIFIED 是否给出了完整的新需求文本（而非片段）？
- [ ] `tasks.md` 是否覆盖 proposal 里的全部变更点？
- [ ] 归档时 specs/ 是否已同步合并？
