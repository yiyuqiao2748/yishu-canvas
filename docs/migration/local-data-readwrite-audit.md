# 本地数据读写入口迁移审计

更新时间：2026-07-25

## 目标

梳理当前仍依赖本地磁盘的数据和文件读写入口，标记后续团队在线版必须迁移到 Supabase Postgres 或 Cloudflare R2 的部分。公司电脑暂时不能操作飞牛 NAS 时，可以先按这份清单继续改造代码和测试。

## 本地根目录

| 根目录或文件 | 当前用途 | 当前代码入口 | 迁移目标 | 优先级 |
| --- | --- | --- | --- | --- |
| `data/canvases/*.json` | 普通画布/智能画布本地数据、回收站状态、画布元信息 | `main.py` 的 `canvas_path`、`save_canvas`、`load_canvas`、`iter_canvas_records` | Supabase `canvases`、`canvas_versions` | P0 |
| `data/projects.json` | 单机项目分类 | `main.py` 的 `load_projects`、`save_projects` | Supabase `projects` | P0 |
| `data/team_cloud.json` | 无 Supabase 时的团队云本地开发存储 | `team_cloud.py` 的 `LocalTeamStore` | 已有 Supabase Store，保留为开发 fallback | P0 |
| `data/asset_library.json` | 本地素材库元数据、分组、工作流素材索引 | `main.py` 的 `load_asset_library`、`save_asset_library` | Supabase `assets` / `asset_collections`，文件进 R2 | P1 |
| `assets/library/` | 素材库文件副本 | `main.py` 的 `make_asset_library_item`、工作流导入逻辑 | Cloudflare R2 | P1 |
| `assets/uploads/` | 本地上传素材、用户整理的本地素材文件夹 | `main.py` 的 `/api/local-assets/*` 系列逻辑 | Cloudflare R2，元数据进 Supabase | P1 |
| `assets/input/` | 上传给生成流程的输入文件 | `main.py` 的 `OUTPUT_INPUT_DIR`、`output_url_for`、上传/导入逻辑 | Cloudflare R2 | P1 |
| `assets/output/` | 生成结果文件 | `main.py` 的 `OUTPUT_OUTPUT_DIR`、模型生成和下载逻辑 | Cloudflare R2 | P1 |
| `assets/team-assets/` | 团队素材本地 fallback | `team_storage.py` 的 `save_team_asset_local` | 已支持 R2，线上应配置 R2 | P1 |
| `output/` | 旧版输出静态目录兼容 | `main.py` 的 `/output` 静态挂载和旧 URL 解析 | 逐步兼容读取，新增文件不再写入 | P2 |
| `data/media_previews/` | 图片/视频预览缓存、JPEG 转换缓存 | `main.py` 的 `/api/media-preview`、`/api/image-jpeg` | 可保留本地缓存，也可后续迁 R2/CDN | P2 |
| `history.json` | 生成历史卡片索引 | `main.py` 的 `save_to_history`、`prune_generation_history_for_media` | Supabase `generation_logs` | P2 |
| `data/conversations/` | 聊天/对话历史 | `main.py` 的 `save_conversation`、`load_conversation`、`list_conversations` | Supabase `conversations` / `messages` | P2 |
| `data/api_providers.json` | API 平台和模型配置 | `main.py` 的 API provider 读写逻辑 | 团队级配置表 + 加密密钥 | P2 |
| `API/.env` | 本地 API Key 和生产环境变量 | `main.py` 的 env 读写逻辑 | Render/NAS 环境变量 + 后端加密配置 | P2 |
| `data/prompt_libraries.json` | 提示词模板库 | `main.py` / 前端模板库逻辑 | Supabase `prompt_libraries` | P3 |
| `data/runninghub_workflows.json` | RunningHub 工作流参数缓存 | `main.py` 的 RunningHub 工作流管理 | Supabase 或团队配置表 | P3 |
| `data/storage_settings.json` | 本地上传/输出目录设置 | `main.py` 的 `load_storage_settings`、`save_storage_settings` | 线上禁用或仅管理员可见 | P3 |
| `data/shared_folders.json` | 本地共享文件夹索引 | `main.py` 的共享文件夹逻辑 | 线上版不建议保留本地路径能力 | P3 |

## 必须迁移的文件存储逻辑

| 类型 | 当前行为 | 风险 | 迁移建议 |
| --- | --- | --- | --- |
| 画布 JSON | 每个画布写入 `data/canvases/{id}.json` | 多人在线时本地文件不适合跨机器共享，版本和权限难管 | 线上团队画布只走 `team_cloud.py` 的 Supabase `canvases` |
| 项目 JSON | `data/projects.json` 管单机项目 | 团队项目权限无法表达 | 团队项目已走 Supabase，后续单机项目仅保留本地模式 |
| 生成输入/输出文件 | 写入 `assets/input`、`assets/output`，URL 为 `/assets/...` 或 `/api/storage-files/...`；已新增 `save_generated_file_from_path` 作为生成结果统一保存入口 | 容器重启或多机部署时文件不可共享 | 新生成结果统一上传 R2，画布只保存公网 URL 和 storage key |
| 本地素材库 | 元数据在 `data/asset_library.json`，文件在 `assets/library` | 素材库无法跨成员同步，删除引用检查复杂 | 元数据进 Supabase，文件进 R2，删除前查画布引用 |
| 团队素材 fallback | 未配置 R2 时写 `assets/team-assets`；图片素材会同步生成 JPEG 缩略图；删除前会检查云端画布引用 | 线上部署如果继续用本地盘，素材可能丢失或只在 NAS 单机可见 | 阶段 5 验收时必须配置 R2 环境变量 |
| 预览缓存 | `data/media_previews` 生成 WebP/PNG/JPEG | 缓存可丢，但可能占空间 | 保留为可重建缓存，后续再考虑 CDN/R2 |
| 历史和对话 | `history.json`、`data/conversations` | 包含提示词、媒体引用和用户内容，团队权限缺失 | 迁到 Supabase 并按用户/团队隔离 |
| API Key | `API/.env` 直接存密钥 | 团队成员权限和审计不足 | 阶段 4 做团队级加密存储，模型调用统一走后端 |

## 建议迁移顺序

1. 固化团队云路径：线上画布只通过 `/api/team-cloud/*`，避免团队项目继续落到 `data/canvases`。
2. 团队素材强制 R2：配置 R2 后，让 `team_storage.py` 在线上缺少 R2 时返回明确错误，而不是静默写本地。
3. AI 生成结果入 R2：已新增统一保存入口并接入主要生成/导出路径，下一步在 NAS/R2 配置完成后验收。
4. 本地素材库云端化：把 `asset_library.json` 拆成素材库、分组、素材条目表。
5. 日志和对话入库：把 `history.json` 和 `data/conversations` 迁到 Supabase，补团队/用户权限。
6. API Key 团队化：替换 `API/.env` 写入流程，改成管理员配置、后端解密调用。

## 当前结论

- 阶段 0 的本地数据读写入口已完成初步梳理。
- 必须迁移的文件存储逻辑已标记，优先级最高的是团队画布、团队素材、生成输入/输出和本地素材库。
- NAS 不可操作时，阶段 3 代码侧已基本收口；下一步可进入团队级 API Key 加密存储和统一后端调用。
