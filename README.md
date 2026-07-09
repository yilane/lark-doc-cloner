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
- 依赖本机已登录的 `lark-cli`

## 适合谁

- 想备份共享文档的人
- 想把模板搬到自己空间的人
- 想二开飞书复刻工具的人
- 想研究 Skill 写法的人

## 安装 Skill

把仓库复制到你的 Skill 目录：

```powershell
git clone https://github.com/yilane/lark-doc-cloner.git C:\Users\eryue\.agents\skills\lark-doc-cloner
```

如果你换了用户名，请把路径里的 `eryue` 改成自己的 Windows 用户名。

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

- 扩展更多飞书块类型
- 增加图片和附件搬运
- 增加批量链接处理
- 增加更细的样式映射
- 增加失败块降级策略

先读 [技术实现文档](references/technical-design.md)。
那里写了完整流程。

## 开源说明

目前仓库没有绑定特定许可证。
如果你要公开分发或商用，请先补充许可证。
