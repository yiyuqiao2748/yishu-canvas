# Cloudflare Access 自动登录

目标：同事先通过 Cloudflare Access 邮箱验证，然后应用自动识别身份，不再要求单独注册 Supabase 账号。

## 原理

Cloudflare Access 会把签名后的 `Cf-Access-Jwt-Assertion` 请求头转发到源站。后端校验 JWT 的签名、签发方和 AUD 后，使用邮箱创建当前应用用户。

不要只信任 `Cf-Access-Authenticated-User-Email` 这类普通邮箱头；如果源站被绕过直连，请求头可以被伪造。

## 需要填写的环境变量

在 NAS 的 `deploy/fnos/.env` 里加入或修改：

```env
TEAM_AUTH_CLOUDFLARE_ACCESS_ENABLED=true
TEAM_AUTH_CLOUDFLARE_ACCESS_TEAM_DOMAIN=https://tight-king-c7fe.cloudflareaccess.com
TEAM_AUTH_CLOUDFLARE_ACCESS_AUD=从 Cloudflare Access 应用页面复制的 Audience / AUD
TEAM_AUTH_CLOUDFLARE_ACCESS_DEFAULT_TEAM_ID=你的默认团队 ID
TEAM_AUTH_CLOUDFLARE_ACCESS_DEFAULT_ROLE=member
```

`TEAM_AUTH_CLOUDFLARE_ACCESS_DEFAULT_TEAM_ID` 可以先留空。留空时，同事能自动登录，但不会自动加入团队；填上后，同事首次访问会自动成为该团队成员。

## 在 Cloudflare 找 AUD

1. 打开 Cloudflare Zero Trust。
2. 进入 `Access` -> `Applications`。
3. 打开 `canvas` / `canvas.yiyuqiaoai.uk` 这个应用。
4. 找到应用详情里的 `Audience`、`AUD` 或 `Application AUD`。
5. 复制完整值到 `.env` 的 `TEAM_AUTH_CLOUDFLARE_ACCESS_AUD`。

## 找默认团队 ID

登录团队画布页面后，在“我的团队”里选择要给同事自动加入的团队。团队卡片或页面里显示的 UUID 就是团队 ID。

如果页面没有明显显示团队 ID，可以暂时留空；同事进入后由你在团队管理里邀请或后续再补配置。

## 启动

改完 `.env` 后，在飞牛 Docker 里重新构建并重启 `yishu-canvas` 项目。

## 行为

- 已有 Supabase 邮箱/密码登录仍可继续使用。
- 没有 Supabase 账号的同事，通过 Cloudflare Access 后会以 `cloudflare-access` 用户身份进入。
- 如果配置了默认团队 ID，后端会自动插入 `team_members` 记录。
