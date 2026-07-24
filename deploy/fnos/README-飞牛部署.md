# 飞牛 NAS 部署说明

目标：把一术画布部署到飞牛 NAS，并通过 Cloudflare Tunnel 暴露为 `https://canvas.yiyuqiaoai.uk`。不要把飞牛管理地址 `http://192.168.1.3:5666` 直接暴露到公网。

## 方案

- `yishu-canvas` 容器运行 FastAPI 服务。
- `cloudflared` 容器负责把公网 HTTPS 域名转发到 NAS 内部服务。
- 团队素材写入 NAS 本地目录 `deploy/fnos/team-assets`。
- 团队数据写入 NAS 本地目录 `deploy/fnos/data`。
- 生成输出写入 NAS 本地目录 `deploy/fnos/output`。
- 第一版容器使用 root 运行，目的是避免 NAS 绑定目录权限导致上传失败。服务只通过 Cloudflare Tunnel 暴露应用，不暴露 NAS 管理后台。

## 第一步：Cloudflare 创建 Tunnel

1. 打开 Cloudflare Dashboard。
2. 进入 Zero Trust。
3. 进入 Networks -> Tunnels。
4. Create tunnel。
5. 选择 Cloudflared。
6. 名称填写 `yishu-canvas`。
7. 复制 Cloudflare 给出的 tunnel token。
8. Public Hostname 添加：
   - Subdomain: `canvas`
   - Domain: `yiyuqiaoai.uk`
   - Type: `HTTP`
   - URL: `127.0.0.1:3000`

## 第二步：配置 Access 白名单

1. 进入 Zero Trust -> Access -> Applications。
2. Add an application。
3. 选择 Self-hosted。
4. Application domain 填 `canvas.yiyuqiaoai.uk`。
5. Policy 只允许团队成员邮箱。
6. 登录方式建议先用 One-time PIN。

这样即使应用登录页有 bug，外层也有 Cloudflare Access 保护。

## 第三步：在 NAS 上准备文件

在飞牛 NAS 上准备一个目录，例如：

```bash
/vol1/docker/yishu-canvas
```

把项目代码放进去后，进入：

```bash
cd /vol1/docker/yishu-canvas/deploy/fnos
cp .env.example .env
```

编辑 `.env`，至少填写：

```bash
CLOUDFLARE_TUNNEL_TOKEN=Cloudflare复制给你的token
PUBLIC_BASE_URL=https://canvas.yiyuqiaoai.uk
SUPABASE_URL=你的Supabase地址
SUPABASE_ANON_KEY=你的Supabase anon key
SUPABASE_SERVICE_ROLE_KEY=你的Supabase service role key
SUPABASE_JWT_SECRET=你的Supabase JWT secret
```

不要把 `.env` 发给别人，也不要提交到 Git。

## 第四步：启动

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f yishu-canvas
docker compose logs -f cloudflared
```

局域网测试：

```text
http://192.168.1.3:3000
```

公网团队访问：

```text
https://canvas.yiyuqiaoai.uk
```

## 第五步：确认素材真正落到 NAS

上传团队素材后检查：

```bash
ls -la ./team-assets
```

如果这里出现团队素材文件，说明 160G NAS 空间已经被用起来了。

## 常见问题

### 访问 `canvas.yiyuqiaoai.uk` 显示 Cloudflare 登录

这是正常的。Cloudflare Access 会先验证团队成员邮箱。

### Cloudflare 502

通常是 `cloudflared` 找不到 `yishu-canvas:3000`，检查：

```bash
docker compose ps
docker compose logs cloudflared
docker compose logs yishu-canvas
```

### 局域网能打开，公网打不开

重点检查 Cloudflare Tunnel 的 Public Hostname：

```text
canvas.yiyuqiaoai.uk -> http://127.0.0.1:3000
```

### 不要做的事

- 不要开放路由器端口到 `5666`。
- 不要把 NAS 管理后台放进 Cloudflare Tunnel 给团队使用。
- 不要把 `.env`、Supabase service role key、Cloudflare tunnel token 发到聊天里。
