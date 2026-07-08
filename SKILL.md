---
name: lark-doc-cloner
description: 用于复刻飞书/飞书 Wiki 文档到用户自己的飞书账号。只要用户给出 feishu.cn、larksuite.com、doubao.com 的 /docx/ 或 /wiki/ 文档链接，并表达复制、克隆、复刻、另存一份、没有编辑权限也想复制、把文档搬到自己的飞书等意图，就必须使用本 Skill。默认依赖本机 lark-cli 已登录并有 active profile；通过读取用户可见内容并重新创建新文档实现，不绕过飞书访问权限。
---

# Lark Doc Cloner

这个 Skill 把一个用户可访问的飞书 Docx / Wiki 文档复刻成用户自己账号下的新文档。

核心原则：

- 只需要原文档“可查看”权限，不要求编辑权限。
- 不绕过飞书权限。打不开的文档不能复刻。
- 默认走“读取 XML → 清洗 → 新建文档”的重建链路。
- 复刻目标是尽量保留标题、段落、列表、表格、图片、附件、代码块、引用等结构。
- 保真失败时要给出 warning，而不是假装完整。

## 什么时候使用

用户出现这些意图时使用：

- “帮我复刻这个飞书文档”
- “克隆这个飞书文档到我的飞书”
- “没有编辑权限，帮我复制一份”
- “把这个 wiki 文档搬到我的账号”
- “这个文档只能看，能不能弄一份我自己的”
- 用户直接给出 `/docx/` 或 `/wiki/` 链接，并要求复制、另存、导出重建

不要用于：

- 用户只想总结文档内容。
- 用户想申请权限。
- 用户要操作表格、Base 内部数据。
- 用户没有原文档查看权限。

## 安全边界

向用户说明：

> 我可以复刻你能查看的内容，但不能绕过飞书权限。没有查看权限的内容拿不到。

“没有编辑权限也能复刻”的意思是：

- 用户可以打开并查看原文档。
- 工具读取可见内容。
- 工具在用户自己的飞书空间新建一份。

不是：

- 破解私有文档。
- 绕过组织安全策略。
- 复制用户无权查看的内容。

## 前置检查

执行前先确认：

1. 本机有 `lark-cli`。
2. 用户已登录：`lark-cli auth login`。
3. 有 active profile：`lark-cli profile list`。
4. token 状态可用；如果是 `needs_refresh`，提示用户刷新登录。
5. 原文档链接可访问。

建议先运行：

```bash
python C:/Users/eryue/.agents/skills/lark-doc-cloner/scripts/clone_lark_doc.py --check
```

如果没有安装 `lark-cli`：

1. 先告诉用户缺少飞书 CLI。
2. 给出官方安装文档：<https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md>
3. 询问用户是否同意由 Agent 自动安装。
4. 用户同意后，Agent 可以执行安装命令。
5. 安装后继续执行 `lark-cli auth login`，再回到复刻流程。

不要在用户未同意时静默安装全局工具。

安装细节见：

- `references/install-lark-cli.md`

## 默认执行方式

使用 bundled script：

```bash
python C:/Users/eryue/.agents/skills/lark-doc-cloner/scripts/clone_lark_doc.py \
  --doc "飞书文档链接"
```

常用参数：

```bash
# 指定 profile
python C:/Users/eryue/.agents/skills/lark-doc-cloner/scripts/clone_lark_doc.py \
  --doc "飞书文档链接" \
  --profile "cli_xxx"

# 创建到“我的空间”
python C:/Users/eryue/.agents/skills/lark-doc-cloner/scripts/clone_lark_doc.py \
  --doc "飞书文档链接" \
  --parent-position my_library

# 创建到指定文件夹或 Wiki 节点
python C:/Users/eryue/.agents/skills/lark-doc-cloner/scripts/clone_lark_doc.py \
  --doc "飞书文档链接" \
  --parent-token "folder_or_wiki_node_token"

# 只导出和清洗，不创建新文档
python C:/Users/eryue/.agents/skills/lark-doc-cloner/scripts/clone_lark_doc.py \
  --doc "飞书文档链接" \
  --fetch-only
```

## 工作流

1. 检查 `lark-cli`。
2. 读取 profile 和身份。
3. 用 `drive +inspect` 获取文档类型、标题和 token。
4. 用 `docs +fetch --detail full --doc-format xml` 读取完整 XML。
5. 保存原始 JSON 和 XML。
6. 清洗 XML：
   - 移除旧 block id。
   - 尽量把图片 URL 转成可新建的 `href`。
   - 保留正文结构。
   - 保留 reference_map。
7. 用 `docs +create --content @file` 新建文档。
8. 输出新文档 URL。
9. 输出 warning 和中间产物路径。

## 成功输出

最终回复用户时包含：

- 新文档链接。
- 输出目录。
- 是否有 warning。
- 没有复制到的内容类型。

示例：

```text
复刻完成：
新文档：https://xxx.feishu.cn/docx/xxx
中间产物：C:\Users\...\Temp\LarkDocCloner\...
提示：有 2 个附件块需要人工检查。
```

## 失败处理

常见失败：

- `lark-cli` 不存在：提示安装或检查 PATH。
- `tokenStatus = needs_refresh`：提示运行 `lark-cli auth login`。
- 文档无查看权限：说明不能绕过权限。
- `docs +fetch` 失败：展示简短错误，保存 debug 日志。
- `docs +create` 失败：保留清洗后的 XML，让用户或开发者检查。

## 保真策略

优先保留：

- 标题
- 段落
- 粗体/斜体/删除线/下划线
- 链接
- 列表
- 待办
- 引用
- 代码块
- 表格
- 图片

可能降级：

- 嵌入表格、Base、画板、同步块、任务、OKR 等资源块。
- 原文档中的权限、评论、历史版本。
- 某些附件或外部资源。

看到 `<sheet>`、`<bitable>`、`<whiteboard>`、`<synced_reference>` 等标签时，要提醒用户人工检查。

## 可二开说明

详细实现设计读：

- `references/technical-design.md`

脚本入口：

- `scripts/clone_lark_doc.py`

后续增强方向：

- 先尝试 Drive 直接 copy，失败再重建。
- 对图片和附件做显式下载再上传。
- 对 Wiki 树做递归复刻。
- 增加本地 FastAPI helper 和进度接口。
- 把任务状态持久化到 SQLite。
