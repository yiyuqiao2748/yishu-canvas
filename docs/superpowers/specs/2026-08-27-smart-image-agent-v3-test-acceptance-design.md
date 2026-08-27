# Smart Image Agent v3 测试环境验收设计

## 目标

在不连接生产 Supabase、不修改 v3 业务代码的前提下，验证 Smart Image Agent v3 的本地自动化测试、测试数据库 migration 和单团队灰度路径。

## 范围与边界

- 仅使用仓库可确认的本地或测试环境配置；不存在时明确记录为无法确认，不创建或猜测配置。
- 仅安装 `requirements.txt` 中已有 Python 依赖；不升级或锁定无关依赖。
- migration 仅执行 `docs/supabase/smart_image_agent_v3.sql`，目标必须是本地或测试 Supabase。
- 灰度只允许一个明确的测试团队 ID 写入 `SMART_IMAGE_AGENT_V3_ENABLED_TEAMS`；禁止设置 `SMART_IMAGE_AGENT_V3_ALLOW_ALL=1`。
- 不提交现有未提交的 v3 实现文件；本规格文档单独提交。

## 验收流程

1. 安装依赖并运行 `py -m unittest tests.test_smart_image_agent`。
2. 运行 `npm run build:scripts` 和 `git diff --check`，确认静态 bundle 可重建且无空白错误。
3. 探测本地 Supabase CLI、配置文件与测试环境变量，过滤任何生产目标。
4. 若存在可确认的非生产目标，执行 v3 migration，并验证表、索引和 `smart_image_agent_v3_approve_execution` RPC。
5. 配置单一测试团队白名单，使用 v3 API 和 `?image_agent=v3` 完成灰度验收。

## 必验行为

- 创建 execution 时不创建 paid run；确认后才入队。
- approval key 的重复提交具有幂等性。
- SSE event sequence 严格递增。
- 取消、反馈、用户与 canvas 作用域隔离正确。
- 四个已定义模型的策略、积分和 provider 路由正确。
- v3 前端模块与 v2 默认加载路径隔离。

## 停止条件与结果分类

- 任一测试失败、migration 失败或目标无法判定为非生产时，不继续后续有状态步骤。
- 结果统一标注为“通过”“失败”或“无法确认”，并附可复现命令与输出摘要。
