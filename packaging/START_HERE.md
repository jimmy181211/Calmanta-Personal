# Calmanta Personal：从这里开始

这个压缩包已经包含 `Calmanta-Personal` 和 `Calmanta-Core`，不需要 Calmanta Official、
PostgreSQL、云服务器、对象存储或模型 API。

## 最简单的使用方式

1. 把整个 ZIP 交给支持本地文件与浏览器工具的 ChatGPT/Codex 桌面应用，并发送：

   ```text
   请解压这个 Calmanta Personal 压缩包，完整读取 START_HERE.md 和
   Calmanta-Personal/.agents/skills/calmanta-personal/SKILL.md，完成本地初始化和测试。
   需要登录 Instagram 或小红书时停下来让我本人操作。不要读取、保存或询问我的密码、
   验证码、Cookie 或 Token；不要自动发送或发布任何内容。
   ```

2. 如果当前桌面应用不能直接解压附件，先在电脑上解压，再从解压后的
   `Calmanta-Personal` 文件夹打开 ChatGPT/Codex，发送同一句话。
3. ChatGPT 会检查相邻的 `Calmanta-Core`，找到可用 Python，运行初始化和测试。
4. 由用户本人在浏览器中登录 Instagram 和小红书；登录材料始终留在浏览器里。
5. Calmanta 只读取可见的新内容、分类、记录并生成待审核草稿。每条回复仍须用户明确批准；定时任务永远不会发送或发布。
6. 需要修改处理方式时，可以直接说“打开设置”。需要让草稿更像本人时，可以说“添加口吻模板”；ChatGPT 会展示七项固定评论类别和可选的预览、保存草稿、保存并启用、取消操作。

## 用户需要知道的边界

- 定时检查只读并起草，绝不自动发送或发布。
- Personal 的本地浏览器协作不等于 Calmanta Official 的官方 API 授权；浏览器密码、Cookie、Token 和会话资料始终留在浏览器里。
- 投诉、退款、价格、合作、合同、威胁和隐私事项交给用户本人处理。
- 页面变化、验证码、掉线或平台风控出现时，Calmanta 会停止并要求用户介入。
- 本地数据只保存在解压后的 `Calmanta-Personal/data`，不要把使用后的文件夹再次分享给别人。

更完整的安装提示位于 `Calmanta-Personal/ChatGPT的配置与自动任务指令.md`。
