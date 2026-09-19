# 阅读工作台

前端沿用 Next.js App Router，采用已确认的 B 风格：象牙白、陶土色与橄榄色，宋体编辑标题、无衬线阅读列表。全站使用 `app/journal/Shell.tsx` 和 `app/styles/journal.css`。

## 页面

| 路径 | 内容 |
| --- | --- |
| `/` | 刊物式首页、跨来源重点文章、最新洞察、政策阅读入口 |
| `/briefing` | 完整趋势、弱信号与建议，以及最近30期历史简报 |
| `/signals` | 搜索、来源/日期/标签/重要性筛选、分页和点击阅读 |
| `/policies` | 政策全文库，按地区、阶段、文件类型和分析状态筛选 |
| `/policies/[id]` | 关键条款、原文引句、适用主体、日期与已抓取全文 |
| `/topics?id=...` | 信号簇文章与关键词匹配的候选政策对读 |
| `/predictions?id=...` | 验证窗口、支持条件、反证条件和实际复盘 |
| `/monitor` | 入库趋势、分析覆盖、科技/政策信源最近一次采集 |
| `/saved` | 当前浏览器收藏，使用 localStorage，不跨设备同步 |

首页与政策、专题、预测、监控在服务端读取 `LOCAL_DB_URL`。`lib/journal-store.ts` 使用共享连接池、连接/语句超时及参数化查询，按模块降级显示不可用状态，不用示例数据补齐。技术信号继续支持 `API_SOURCE` 非 local 时的 IC 读取；政策与监控仍需要本地 PostgreSQL。

列表和详情通过 `/api/reader/[kind]`（signals / article / policies / policy）读取。列表分页每页30条；全文只在详情中读取。搜索和筛选在数据库分页前执行。客户端取消过时请求，避免快速切换时错配文章与标题。旧 `/api/signals` 与 `/api/predictions` 接口保持兼容。

## 数据口径

- 文章总量是已收录总数，不是今日新增；重点文章是 `importance_score >= 4`。
- 文章已有分析：`hidden_signal`、`reason`、`actionable` 至少一个非空，不把 RSS 描述直接视为 AI 分析。
- 政策已分析：`enriched_at IS NOT NULL`。预筛会跳过低相关文件，因此未分析数量不是待处理任务数。
- 专题政策来自实体/关键词检索，明确标记为候选关联，不推断政策适用性。
- 监控图表按北京时间的首次入库日期统计。来源结果取最后一次采集记录，超过24小时显示无更新提示，不能据此断言在线状态。
- 预测没有复盘时不显示命中率。日期缺失时显示未明确；不生成虚构的征集截止提醒。
- 刷新只读取数据库，不调用模型或触发采集。

## 本地验证

```sh
cd web
npm run dev
npm run test:run
npm run build
```

主要组件为 `Reader`（技术/政策列表与阅读）、`Predictions`、`TrendChart`、`Shared` 和 `Actions`。`journal-utils.ts` 中的来源多样性、来源 URL 校验与洞察归一化有单元测试；查询测试覆盖筛选参数化、分页、日期与关键词转义。
