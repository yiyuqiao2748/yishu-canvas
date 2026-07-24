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

## 3. GitHub Actions

`.github/workflows/ci.yml` 会自动执行：

- 安装 Python 依赖
- 运行后端测试
- 检查关键前端脚本语法
- 构建 Docker 镜像

Render 负责根据 GitHub 分支自动部署。

## 4. 健康检查

服务提供：

`/healthz`

Render 和 Docker 会用它判断服务是否正常。

## 5. 本地开发模式

本地没有 Supabase 时，可以临时启用：

`TEAM_AUTH_DEV_BYPASS=1`

只允许本地开发使用，生产环境必须保持：

`TEAM_AUTH_DEV_BYPASS=0`

## 6. 当前上线前检查

- [x] Dockerfile
- [x] Render Blueprint
- [x] GitHub Actions CI
- [x] 健康检查接口
- [x] Supabase 表结构
- [ ] Cloudflare R2 存储接入
- [ ] 生产域名
- [ ] 首次 Render 部署验证
