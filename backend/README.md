# 视觉工坊：咨询后端源码

本目录提供最小的客户咨询 API、SQLite 数据库和单管理员管理页面。代码使用 Python 3.11+ 标准库，无 Python 包依赖。**提交到 GitHub 只保存源码，不会运行或发布后端。** GitHub Pages 只能托管前端静态文件；请将本目录部署到单独的、支持 Python WSGI 和持久化磁盘的 HTTPS 主机。

## 功能与路径

| 路径 | 用途 |
| --- | --- |
| `POST /api/inquiries` | GitHub Pages 前台提交咨询 |
| `GET /admin/` | 管理员登录与咨询管理页面 |
| `POST /api/admin/login`、`POST /api/admin/logout` | 登录、退出 |
| `GET /api/admin/me` | 当前管理员及 CSRF token |
| `GET /api/admin/summary` | 全部、新提交、已联系、已结束数量 |
| `GET /api/admin/inquiries?status=&type=` | 最近 200 条咨询，可筛选 |
| `GET /api/admin/inquiries/{id}` | 咨询详情 |
| `PATCH /api/admin/inquiries/{id}` | 更新状态及内部备注 |

咨询类型只能为 `vision`（视觉项目）或 `sop`（边缘端 SOP）。后台状态为 `new`、`contacted`、`closed`。前台提交 JSON 例子：

```json
{"name":"张先生","contact":"微信或手机号","company":"某设备公司","type":"vision","description":"需要为金属件做视觉定位和现场联机调试","consent":true,"website":""}
```

`website` 是隐藏的防机器提交字段，正常用户保持空值。`consent` 必须为 `true`。客户提交成功返回 HTTP 201；失败返回非 2xx 和 `{"error":"..."}`。前端只有在 API 已部署、配置为 HTTPS 地址后才应启用表单提交。

## 首次部署配置

请在后端主机的环境变量中设置：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_PATH` | SQLite 文件的绝对路径，所在目录需要持久化并仅允许后端进程访问；默认 `backend/data/site.db` 只适合本地测试 |
| `APP_ORIGIN` | 后端自己的 HTTPS origin，例如 `https://api.example.cn`；后台登录和修改请求必须来自该 origin |
| `PUBLIC_ORIGINS` | 可提交咨询的前台 origin，用逗号分隔；默认 `https://zqz365001.github.io` |
| `RATE_LIMIT_SECRET` | 至少 32 字符的随机私密字符串，供来源地址哈希与限流使用 |

在目标主机上用 `python app.py init-db` 初始化 SQLite。首次建立管理员时，临时提供 `ADMIN_USERNAME` 和长度至少 14 字符的 `ADMIN_PASSWORD` 环境变量，再执行 `python app.py create-admin`；完成后立即从环境中移除 `ADMIN_PASSWORD`。命令不会输出密码。不要将环境变量、数据库、备份或客户信息提交到仓库。数据库初始为空；管理员命令只创建账号，不会覆盖已有账号。

WSGI 入口是 `app:application`。部署平台须使用适合生产的 WSGI 服务进程、HTTPS 反向代理、持久化磁盘和数据库备份；不要把 `wsgiref.simple_server` 当生产服务器。代理应正确提供 `REMOTE_ADDR`，不要把所有客户都映射到同一个代理地址，也不要直接信任客户端提供的 `X-Forwarded-For`。如需通过代理取得真实来源地址，应由可信代理在服务器层规范化，而不是修改应用去信任任意请求头。

GitHub Pages 前台需要把实际后端 HTTPS 地址写入前端配置，浏览器会从 GitHub Pages origin 向该后端发送请求。未部署后端前，前端应保持原有展示内容可用，并明确提示表单暂不可提交。源码中的默认 CORS 只允许上面给出的 GitHub Pages origin；更换前台域名时同步更新 `PUBLIC_ORIGINS`。CORS 限制浏览器来源，不是身份认证；公开提交接口还使用必填同意、隐藏字段、请求大小限制、输入校验和每来源每小时 5 次的基础限流。

## 安全与范围

- 管理员密码使用 PBKDF2-HMAC-SHA256 加盐哈希（600,000 次迭代）；会话为随机 token，数据库只存 token 哈希。
- 会话 Cookie 设置 `HttpOnly`、`Secure`、`SameSite=Strict`，8 小时失效；管理员写入请求还要求同源 `Origin` 和 CSRF token。
- 客户内容在管理页只作为纯文本显示，数据库查询使用参数绑定；后端响应禁止缓存并设置基本安全头。
- 限流基于 WSGI `REMOTE_ADDR` 和 SQLite，适合轻量咨询量。更高流量或复杂代理环境应在反向代理层补充限流与日志保护。
- 当前只有一个管理员角色、咨询列表与跟进备注；没有邮件通知、附件上传、课程订单、支付、自动营销或公开管理员注册。
- 数据库保存客户联系方式，应配置访问权限、备份和必要的留存/删除流程。此版不提供自动删除功能。

此目录只是部署候选源码。本次提交不启动后端、不创建真实客户数据库，也不将后台 URL 作为可用服务公布。
