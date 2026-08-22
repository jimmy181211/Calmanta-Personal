# 给朋友 ChatGPT 的配置与自动任务指令

这份文件与 `Calmanta-Personal` 本地版配套。把 `Calmanta-Official` 和 `Calmanta-Personal` 两个目录一起
交给对方，并让她从 `Calmanta-Personal` 目录打开 ChatGPT/Codex 桌面应用。然后把下面整段原样
发给她自己的 ChatGPT。

## 可直接复制的指令

```text
请帮我配置这个工作区里的 Calmanta Personal。不要重新开发，也不要复制正式版代码；必须复用
旁边 `Calmanta-Official/backend` 的现有安全、分类和草稿校验逻辑。

请按以下顺序自动完成：

1. 完整读取并使用项目内的 $calmanta-personal skill；如果技能选择器暂时没显示，就直接读取
   .agents/skills/calmanta-personal/SKILL.md，并告诉我重启应用后会自动发现。
2. 确认 Calmanta-Official 和 Calmanta-Personal 两个目录并排存在。不要配置 PostgreSQL、S3、云端对象
   存储或模型 API；Personal 使用本地 SQLite、data/objects 和当前 ChatGPT 作为 AI 大脑。
3. 找到可用的 Python（优先系统 Python；没有就使用 ChatGPT/Codex 自带运行时），运行：
   python -m calmanta_personal init
   python -m unittest discover -s tests -v
4. 检查 config/profile.json。先使用默认口吻，不要因为缺少口吻样本阻塞安装；以后根据我批准、
   修改过的回复逐步更新 examples。任何时候都不要编造我的事实、价格、承诺或处理结果。
5. 请我本人分别登录 Instagram 和小红书网页版。只让我在浏览器里自行登录或扫码；绝不向我
   索取账号、密码、验证码、Cookie、Token、Local Storage 或浏览器会话文件。
6. 登录完成后做一次只读试运行：只检查页面上可见的新私信/评论，最多处理 profile.json 规定
   的数量；先用本地 filter-new 去重，再只为新且值得回复的内容生成草稿。投诉、退款、价格、
   合作、合同、威胁和隐私事项只交给我，不替我承诺。简单感谢、表情、垃圾消息可记录为不回复，
   不要逐条展示给我。
7. 把新草稿按以下格式发给我：
   [ID] 平台 / 私信或评论 / 对方名字
   原文：……
   建议：回复 / 不回复 / 交给本人
   草稿：……
   我可以回复“OK ID”、“修改 ID：新文字”或“跳过 ID”。
8. 定时任务本身绝不发送或发布。只有我在当前交互任务中明确写“OK ID”并要求发送时，才可
   在已登录网页中核对对象和最终文字后执行；平台显示成功后再在本地标记完成。验证码、风控、
   页面不确定或对象不确定时立即停止并告诉我。
9. 为这个项目创建一个每天本地时间上午 9:00 运行的定时任务，任务提示只使用下面这一句，
   不要每天重复长规则：
   Use $calmanta-personal to check Instagram and Xiaohongshu once, save only new actionable drafts for
   my approval, and never send or publish automatically.
10. 最后只向我报告：初始化和测试是否成功、数据保存路径、两个平台是否已登录、定时任务的
    时间，以及仍需我本人完成的事项。保持简短，节省 token。

限制：只操作我本人授权并已登录的账号；只看可见收件箱/评论页面；不使用开发者工具抓接口，
不读取认证材料，不绕过验证码或风控，不批量爬取，不关注、私信或骚扰无关对象。
```

## 她本人只需完成的事情

1. 在浏览器里亲自登录 Instagram 和小红书。
2. 让电脑和 ChatGPT/Codex 桌面应用在定时任务运行时保持可用；掉线或验证码出现时重新登录。
3. 对草稿回复 `OK <ID>`、`修改 <ID>：……` 或 `跳过 <ID>`。
4. 对投诉、退款、价格、合作、合同、威胁和隐私事项亲自决定。

## 低 token 设计

- 长规则只保存在 skill 中；每日任务只有一句话。
- 先用 SQLite 指纹去重，再让模型处理，避免为旧消息重复生成草稿。
- 默认只展示新草稿和需要本人处理的事项；“不回复”条目只报数量。
- 口吻配置和已处理状态保存在本机，不要求每次对话重新解释。
