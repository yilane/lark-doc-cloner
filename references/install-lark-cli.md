# 飞书 CLI 安装指引

官方文档：

<https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md>

## 处理策略

当 `lark-doc-cloner` 检测不到 `lark-cli` 时，Agent 不要静默安装。

正确流程：

1. 告诉用户缺少飞书 CLI。
2. 给出官方安装文档链接。
3. 询问用户是否同意自动安装。
4. 用户明确同意后，再执行安装。
5. 安装完成后，让用户登录或刷新授权。
6. 登录成功后继续文档复刻。

## 自动安装命令

用户同意后可执行：

```powershell
npm install -g @larksuite/cli
```

安装后验证：

```powershell
lark-cli --version
lark-cli profile list
```

## 登录

首次使用或 token 过期时执行：

```powershell
lark-cli auth login
```

如果 `profile list` 中看到：

```text
tokenStatus: needs_refresh
```

也应重新运行：

```powershell
lark-cli auth login
```

## 给 Agent 的说明

如果用户说：

```text
帮我安装飞书 CLI：https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md
```

这可以视为明确授权安装。

安装后继续检查：

```powershell
python C:\Users\eryue\.agents\skills\lark-doc-cloner\scripts\clone_lark_doc.py --check
```
