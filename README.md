# Calmanta Personal

Calmanta Personal 是 Calmanta 正式版的本地伴侣，不是另一套重写。它直接复用相邻
`Calmanta-Official/backend` 中的账号材料过滤、风险分类、敏感话题识别和草稿安全校验；新增的只有
本地持久化、ChatGPT 工作流和审批记录。

## 两个版本的分工

- `Calmanta-Official`：正式云端产品，使用 PostgreSQL、S3 兼容对象存储和独立模型提供方。
- `Calmanta-Personal`：个人本地版，使用 ChatGPT/Codex 作为“模型和操作框架”，数据保存在本机。

两个目录应并排放置：

```text
Calmanta/
├── Calmanta-Official/
└── Calmanta-Personal/
```

也可以用环境变量 `CALMANTA_CORE_DIR` 指向 `Calmanta-Official` 目录。

## 本地数据放在哪里

- 评论、私信、草稿、审批和事件：`data/calmanta-personal.db`（SQLite）
- 图片或证据文件：`data/objects/`（按 SHA-256 去重）
- 临时观察和决策文件：`staging/`
- 口吻、平台和审批设置：`config/profile.json`

`data/` 和 `staging/` 默认不会提交到 Git。Personal 不保存账号密码、Cookie、Token、浏览器
会话或 Local Storage；`Calmanta-Official` 的过滤器会拒绝这些字段。

## 快速开始

在本目录运行：

```powershell
python -m calmanta_personal init
python -m unittest discover -s tests -v
```

如果 `python` 不在 PATH，让 ChatGPT/Codex 使用它自带的 Python 运行时即可，不需要安装数据库、
对象存储或模型 SDK。

项目自带的 skill 位于 `.agents/skills/calmanta-personal/`。从本目录打开 ChatGPT/Codex 后，
日常任务只需调用 `$calmanta-personal`；固定规则无需每天重复，从而减少 token 消耗。

## 运行流程

1. 用户本人登录 Instagram 和小红书网页版。
2. ChatGPT 只检查可见的新消息/评论，不接触认证材料。
3. 先执行 `filter-new`，排除 SQLite 中已经见过的条目。
4. ChatGPT 只对新条目判断“回复、不回复、交给本人或阻断”，并生成必要草稿。
5. `ingest` 把结果保存到本机；只把值得回复的草稿和敏感事项展示给用户。
6. `OK <ID>` 记录批准，但命令行本身绝不发送。
7. 只有用户在当前交互任务中明确要求发送/发布，浏览器操作才可继续；确认平台显示成功后，
   才用 `complete <ID> --confirm SENT` 记账。

定时任务永远停在第 5 步，不得发送或发布。

## 常用命令

```powershell
python -m calmanta_personal filter-new --input staging/observed.json --output staging/new.json
python -m calmanta_personal ingest --input staging/decisions.json
python -m calmanta_personal list --state draft_pending_review
python -m calmanta_personal approve <ID> --confirm OK
python -m calmanta_personal reject <ID>
python -m calmanta_personal complete <ID> --confirm SENT
python -m calmanta_personal put-object <文件路径>
```

## 边界

Personal 是低频、本人账号、可见页面范围内的实验性辅助。网站页面变化、掉线、验证码、风控或
平台规则都可能让一次检查失败。不得绕过验证码、风控或访问控制；不得批量爬取；不得把登录
凭证交给项目。需要稳定商业化接入时，仍应使用平台官方 API、OAuth 或合规合作伙伴能力。
