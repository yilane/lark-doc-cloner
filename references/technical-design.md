# 技术实现设计

## 目标

给用户一个可以二开的飞书文档复刻框架。

输入：

```text
飞书 Docx / Wiki 文档链接
```

输出：

```text
用户自己账号下的新飞书文档链接
```

## 权限模型

复刻不需要原文档编辑权限。

它只依赖：

- 用户能查看原文档。
- `lark-cli` 能以用户身份读取文档。
- `lark-cli` 能以用户身份创建新文档。

不能做到：

- 读取无权查看的文档。
- 绕过组织权限。
- 复制评论、历史版本、权限成员。

## 核心链路

```mermaid
flowchart LR
  A["用户文档 URL"] --> B["drive +inspect"]
  B --> C["docs +fetch full XML"]
  C --> D["保存 raw XML"]
  D --> E["清洗 XML"]
  E --> F["docs +create"]
  F --> G["新文档 URL"]
```

## 为什么不用编辑权限

编辑权限用于修改原文档。

复刻只需要读取原文档，然后在用户自己的空间创建新文档。

所以只要 `docs +fetch` 成功，就可以继续。

## 命令选择

检查环境：

```bash
lark-cli --version
lark-cli profile list
lark-cli whoami --json
```

解析 URL：

```bash
lark-cli drive +inspect --url "<doc_url>" --json
```

读取文档：

```bash
lark-cli docs +fetch \
  --doc "<doc_url>" \
  --scope full \
  --detail full \
  --doc-format xml \
  --as user \
  --json
```

创建文档：

```bash
lark-cli docs +create \
  --as user \
  --doc-format xml \
  --title "<title> - clone" \
  --content "@content.clone.xml" \
  --json
```

默认不传 `parent-position`，让飞书创建到云盘根目录。

## 中间产物

脚本会输出：

```text
environment.json
inspect.json
fetch.json
content.raw.xml
content.clone.xml
reference-map.json
block-report.json
media-manifest.json
create.json
result.json
```

这些文件用于：

- 复盘失败。
- 对比保真度。
- 做二次开发。
- 构造测试样本。

### `block-report.json`

记录：

- 所有 XML 标签计数。
- 高风险资源块，例如 Base、画板、同步块、任务、OKR。
- 未登记标签。
- 媒体和附件资源概览。
- 本次 warning。

### `media-manifest.json`

记录 XML 中识别到的图片和附件：

- 标签类型。
- 资源 token。
- URL / href。
- 文件名。
- 是否已下载。
- 下载路径或失败原因。

## XML 清洗策略

`docs +fetch --detail full` 会带出源文档的 block id。

新建文档时不应该复用旧 id。

所以脚本会移除：

```text
id="..."
```

图片处理：

- 如果 `<img>` 有 `url` 但没有 `href`，脚本会补 `href`。
- `docs +create` 可用 `href` 上传网络图片。

风险资源：

- `<sheet>`
- `<bitable>`
- `<base>`
- `<whiteboard>`
- `<mindnote>`
- `<synced_reference>`
- `<synced_source>`
- `<task>`
- `<okr>`
- `<slides>`
- `<wiki>`

这些会写入 warning。

如果用户传 `--degrade-unsupported`，脚本会把已登记的高风险资源块替换成文本占位：

```xml
<p>[未自动复刻：bitable 资源块。多维表格/Base 需要单独接口复制，XML 重建只能降级。]</p>
```

这不是高保真复制。
它的价值是让新文档可创建、可读，并明确标出损失位置。

## 保真边界

高保真：

- 文本
- 标题
- 列表
- 表格
- 代码块
- 引用
- 基础富文本

中等保真：

- 图片
- 附件
- 文档引用

可能降级：

- 嵌入表格
- 多维表格
- 画板
- 同步块
- 权限
- 评论
- 历史版本

## 可扩展点

### 1. Drive 直接复制

飞书 Drive 可能支持文件级复制。

这条链路理论上更保真。

但它可能受原文档权限、组织策略、文件类型影响。

后续可增加：

```text
--mode auto
--mode copy
--mode rebuild
```

默认：

1. 先尝试 copy。
2. copy 失败再 rebuild。

### 2. 图片和附件显式搬运

当前框架已经会扫描 `<img>`、`<image>`、`<file>`、`<attachment>`。

默认行为：

1. 写入 `media-manifest.json`。
2. 如果图片有 `url` 但没有 `href`，补充 `href`，交给 `docs +create` 尝试重建。

用户传 `--download-media` 时：

1. 对有 token 的媒体运行 `docs +media-download`。
2. 保存到输出目录的 `media/`。
3. 在 `media-manifest.json` 里记录下载状态。

仍待二开的更强方案：

1. 扫描 `<img>` 和 `<source>`。
2. 用 `docs +media-download` 下载。
3. 新建文档后用 `docs +media-insert` 插入。
4. 通过文本锚点或 block id 把媒体插回原位置。
5. 对附件使用 `--type file` 和 `--file-view` 选择展示方式。

当前版本不会承诺“附件已完整插回原位”。
它只完成“识别、记录、可选下载”。

### 3. 批量链接处理

使用：

```bash
python scripts/clone_lark_doc.py --docs-file docs.txt --continue-on-error
```

规则：

- `docs.txt` 每行一个链接。
- 空行跳过。
- `#` 开头的行跳过。
- 默认遇到错误停止。
- 加 `--continue-on-error` 后继续处理后续链接。
- 批量结果写入 `batch-result.json`。

### 4. Wiki 树复刻

当前脚本复刻单篇文档。

Wiki 树复刻需要：

1. `wiki +node-get` 解析当前节点。
2. `wiki +node-list` 遍历子节点。
3. 对每个 docx 节点执行单篇复刻。
4. 在目标 wiki 下重建层级。

### 5. 本地 Helper 服务

可加一个 FastAPI 服务：

```text
GET  /status
POST /jobs/clone-from-url
GET  /jobs/{id}
```

前端只轮询任务。

脚本继续作为任务执行器。

## 测试样本

建议准备：

1. 纯文本文档。
2. 图片文档。
3. 表格文档。
4. 代码块文档。
5. Wiki 文档。
6. 只读文档。
7. 含附件文档。
8. 含嵌入表格或 Base 的文档。

## 失败诊断

优先看：

```text
result.json
create.json
fetch.json
content.clone.xml
```

常见原因：

- token 过期。
- 文档无查看权限。
- XML 中有不可创建的资源块。
- 图片 URL 无法访问。
- 目标文件夹没有创建权限。

## 发布建议

这个 Skill 是开源版框架。

建议保留源码。

不要加壳。

如需分发给非技术用户，再在外层包一个桌面 GUI。
