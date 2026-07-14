# lark-doc-cloner

把一个你能打开的飞书 / Lark 文档，重新创建到自己的飞书账号里。

它不是破解器。
它不绕过权限。
它只读取你能看的内容。
然后生成一份新文档。

## 能做什么

- 支持飞书 Docx 链接
- 支持飞书 Wiki 链接
- 没有编辑权限也能复制
- 保留标题、段落和主要结构
- 默认新标题后缀是 ` - clone`
- 默认创建到云盘根目录 `https://my.feishu.cn/drive/me`
- 生成块类型报告和媒体清单
- 支持批量链接处理
- 支持高风险块降级占位
- 支持 Drive 直接 copy，失败后自动 rebuild
- 支持下载后按锚点插回图片和附件
- 支持 Wiki 树递归复刻
- 依赖本机已登录的 `lark-cli`

## 适合谁

- 想备份共享文档的人
- 想把模板搬到自己空间的人
- 想二开飞书复刻工具的人
- 想研究 Skill 写法的人

## 安装 Skill

### 让 AI 自己装

对**任意 Agent**（Claude Code / Codex / Cursor 等）说一句：

> 请帮我查找并自动安装 [https://github.com/yilane/lark-doc-cloner](https://github.com/yilane/lark-doc-cloner) 这个 Skill。

它会自行 clone 到对应的 skills 目录并接入。

### 手动安装

把仓库复制到你的 Skill 目录：

```powershell
git clone https://github.com/yilane/lark-doc-cloner.git "$HOME\.agents\skills\lark-doc-cloner"
```

`$HOME` 会自动指向当前 Windows 用户的主目录，无需手动替换用户名。

## 前置条件

需要先安装并登录飞书 CLI：

[飞书 CLI 安装文档](https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md)

常见安装方式：

```powershell
npm install -g @larksuite/cli
lark-cli auth login
```

如果用户还没安装，Agent 应先展示安装指引。
用户同意后，再自动执行安装。

## 使用方式

对 Agent 说：

```text
帮我复刻这个飞书文档：
https://example.feishu.cn/docx/xxxx
```

或者：

```text
把这个飞书 Wiki 克隆到我的文档里：
https://example.feishu.cn/wiki/xxxx
```

## 脚本直接运行

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx"
```

等价写法：

```powershell
python scripts\clone_lark_doc.py --doc "https://example.feishu.cn/docx/xxxx"
```

查看安装帮助：

```powershell
python scripts\clone_lark_doc.py --install-help
```

自定义标题后缀：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --title-suffix " - backup"
```

指定固定文件夹：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --parent-token "folder_token"
```

批量复刻：

```powershell
python scripts\clone_lark_doc.py --docs-file docs.txt --continue-on-error
```

`docs.txt` 每行一个飞书文档链接。
空行和 `#` 开头的行会跳过。

输出保真报告但不创建文档：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --fetch-only
```

下载 XML 里能识别到 token 的图片和附件：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --download-media
```

下载后按原位置锚点插回图片和附件：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --reinsert-media
```

这会先把媒体块替换成唯一锚点，创建文档后用 `docs +media-insert` 插到锚点附近，然后尝试删除锚点文字。

把 Base、画板、同步块等高风险块降级成文本占位：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --degrade-unsupported
```

强制只走重建，不尝试 Drive copy：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --mode rebuild
```

只尝试 Drive copy：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/docx/xxxx" --mode copy --parent-token "folder_token"
```

说明：Drive copy 需要目标文件夹 token。默认云盘根目录没有稳定 folder token 时，会自动跳过 copy，继续 rebuild。

递归复刻 Wiki 树：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/wiki/xxxx" --wiki-recursive
```

递归复刻会在目标 Wiki 空间创建节点，再把每个 docx 节点正文写入。
默认目标是 `my_library`。

使用飞书原生 Wiki 节点复制：

```powershell
python scripts\clone_lark_doc.py "https://example.feishu.cn/wiki/xxxx" --wiki-native-copy --yes
```

这是高风险写操作，必须显式传 `--yes`。

也可以写入配置文件：

```json
{
  "parent_token": "folder_token"
}
```

配置文件默认位置：

```text
C:\Users\<你的用户名>\.agents\lark-doc-cloner.config.json
```

## 权限边界

这个工具只处理当前账号可访问的内容。

如果文档本身不能打开，它不会偷取内容。
如果飞书接口拒绝访问，它会停止并提示原因。
如果没有 `lark-cli`，它会先给安装指引。

## 项目结构

```text
.
├── SKILL.md
├── scripts/
│   └── clone_lark_doc.py
├── references/
│   ├── install-lark-cli.md
│   └── technical-design.md
└── evals/
    └── evals.json
```

## 二开建议

这些能力已经有基础框架：

- 块类型扫描：输出 `block-report.json`
- 图片和附件清单：输出 `media-manifest.json`
- 图片和附件下载：`--download-media`
- 图片和附件锚点插回：`--reinsert-media`
- 批量链接处理：`--docs-file`
- 失败块降级：`--degrade-unsupported`
- Drive copy 回退 rebuild：`--mode auto`
- Wiki 树递归复刻：`--wiki-recursive`

仍适合继续二开的方向：

- 为更多飞书块补充精确 XML 映射
- 把表格、Base、画板做成专用复制链路
- 为样式差异增加自动对比报告
- 把批量任务做成可视化进度界面

先读 [技术实现文档](references/technical-design.md)。
那里写了完整流程。

## License

MIT License.
