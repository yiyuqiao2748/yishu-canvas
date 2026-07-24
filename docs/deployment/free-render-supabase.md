# 免费团队版部署说明

更新时间：2026-07-24

## 目标架构

- GitHub：代码仓库和 CI
- Render Free：运行 FastAPI + 静态页面
- Supabase Free：Auth + Postgres
- Cloudflare R2 Free：后续保存图片、视频和素材

## 1. Supabase

1. 创建 Supabase 项目。
2. 打开 SQL Editor。
3. 执行 `docs/supabase/team_cloud_schema.sql`。
4. 在 Supabase Project Settings 中记录：
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_JWT_SECRET`

## 2. Render

1. 在 Render 新建 Blueprint。
2. 选择 GitHub 仓库 `yiyuqiao2748/yishu-canvas`。
3. Render 会读取根目录的 `render.yaml`。
4. 在 Render 环境变量中填写：
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_JWT_SECRET`
   - `SUPABASE_JWT_AUDIENCE=authenticated`
   - `TEAM_AUTH_COOKIE_SECURE=1`
   - `TEAM_AUTH_COOKIE_NAME=team_cloud_access_token`
   - `TEAM_AUTH_DEV_BYPASS=0`
   - `TEAM_ASSET_MAX_BYTES=52428800`
   - `R2_ENDPOINT_URL`
   - `R2_BUCKET`
   - `R2_ACCESS_KEY_ID`
   - `R2_SECRET_ACCESS_KEY`
   - `R2_PUBLIC_BASE_URL`

## 3. Cloudflare R2

1. 创建 R2 bucket，例如 `yishu-canvas-assets`。
2. 创建 R2 API Token，权限至少包含目标 bucket 的对象读写。
3. 记录 endpoint、access key、secret key。
4. 如果要让浏览器直接访问素材，给 bucket 绑定公开域名，并填写 `R2_PUBLIC_BASE_URL`。
5. 未配置 R2 时，开发环境会退回到本地 `/assets/team-assets/...`。

## 4. GitHub Actions

`.github/workflows/ci.yml` 会自动执行：

- 安装 Python 依赖
- 运行后端测试
- 检查关键前端脚本语法
- 构建 Docker 镜像

Render 负责根据 GitHub 分支自动部署。

## 5. 健康检查

服务提供：

`/healthz`

Render 和 Docker 会用它判断服务是否正常。

## 6. 本地开发模式

本地没有 Supabase 时，可以临时启用：

`TEAM_AUTH_DEV_BYPASS=1`

只允许本地开发使用，生产环境必须保持：

`TEAM_AUTH_DEV_BYPASS=0`

## 7. 当前上线前检查

- [x] Dockerfile
- [x] Render Blueprint
- [x] GitHub Actions CI
- [x] 健康检查接口
- [x] Supabase 表结构
- [x] Cloudflare R2 存储接入
- [ ] 生产域名
- [ ] 首次 Render 部署验证
