# 2026-11-16 工作记录 · GeoOps 本轮增量

范围：只在本仓库 `<repo>`（Bumao GeoOps，0.1.0，探索工程，未发布）。
本轮不写、不登记任何其他工程；下列结论都出自本仓库当轮的实跑。

工程等级：**核心工程（core）**，2026-11-16 按用户指示升级，登记在
`docs/ENGINEERING_TIER.md`；等级≠发布资格。

## 一、增量一：测绘任务引擎（任务生命周期）

`geoops/domain/tasks.py`：`DRAFT → READY → RUNNING ⇄ PAUSED → COMPLETED`，
`FAILED` 可重试、非终态可 `CANCELLED`；非法边、原地转换、`COMPLETED`/`CANCELLED` 缺理由、
未知 `task_id`、重复挂 run、非 `RUNNING` 挂 run 全部抛 `TaskError` 且任务状态不变；
每次变更写入 `history` 并镜像到 Domain Registry；`GET /api/v1/tasks` 只读。

## 二、增量二：流程从失败节点恢复

`geoops/workflow/executor.py`：`NodeStatus.REUSED` + `resume(nodes, previous)`，
已通过节点带原输出前移（输出进 `context["node_outputs"]`）；上一轮未失败、节点数/身份变了、
前置节点非 `PASS`、复用旧 `run_id` 全部拒绝；`WorkflowEngine` 存历史、拒绝重复 `run_id`；
`WorkflowRun` 增 `resumed_from`。

## 三、增量三：测绘专业规则引擎（模块 06）

`geoops/survey/rules.py` + `packs/p01_dataset.json`：规则即数据，五态
`PASS / FAIL / WARNING / SKIPPED / ERROR`；条件不满足记 `SKIPPED`，校验器缺失或异常记
`ERROR`，二者绝不升格为 `PASS`；`warning` 失败记 `WARNING`，`error` 记 `FAIL`；
`FAIL` 与 `ERROR` 都阻断；规则包整体先校验，缺字段/severity 非法/id 重复整包拒绝。

## 四、增量四：规则检查做成流程显式节点

`geoops/survey/nodes.py`：阻断规则让节点失败、后续节点自动 `SKIPPED`；
`ERROR` 在节点层保持 `ERROR`，不压平成 `FAIL`；`WARNING`/`SKIPPED` 放行但每条结果写入
`context["rule_results"][node_id]`；无适用规则记 `SKIP`，不记 `PASS`。

## 五、增量五：快照持久化

`geoops/store.py`：`SnapshotStore` 把注册表与任务引擎写成一个 JSON 快照，
**原子写**（写临时文件 → `fsync` → `os.replace`）；恢复前在空对象上整包校验，
坏包/重复 id/与现网冲突一律 `StoreError` 拒绝，**不半恢复**；
`DomainRegistry.restore` 与 `TaskEngine.restore` 保留 version、status、history，
不像 `register` 那样从 version 1 重新开始。

## 六、增量六：成果报告导出

`geoops/quality/report.py`：`build_report` 只复制已记录的 task / runs / 规则结果 /
质量报告 / 成果 / 审核；**没提供的段一律写 `NOT_RECORDED` + 原因**，不猜、不补；
`render_markdown` 出中文/英文对照的 md；`write_report` 原子写 JSON 或 Markdown，
未知格式与外来载荷直接拒绝。

## 七、增量七：带权限位的写入口

`geoops/api/security.py` + `geoops/api/app.py`：

- `PermissionPolicy`：令牌 → `task:create` / `task:transition` / `audit:read`，**API 不自带账号**，授权由调用方给出。
- `POST /api/v1/tasks`、`POST /api/v1/tasks/{id}/transitions`；`GET /api/v1/audit` 自带权限位。
- 先鉴权后读体：缺令牌/未知令牌 401，权限不足 403，体超 64KB 413，JSON 非法 400；
  拒绝与放行全部进审计（只存令牌 sha256 前缀，不存原令牌）。
- 未注入策略时写入口整体关闭（POST 一律 404），不会出现「默认能写」。

## 八、增量八：令牌外置（只存哈希）与审计落盘

`geoops/api/security.py`：

- 授权只存 **sha256 哈希**，不存原令牌；`PermissionPolicy.from_file` 读
  `geoops-tokens` 文件，**文件里出现明文 `token` 字段就拒绝**，重复哈希也拒绝。
- `AuditLog(path=...)`：每行 append + `fsync` 落盘；重新加载得到同样的行；
  坏行/缺字段抛 `AuditError`，**不静默丢弃**（审计里最不能有的就是空洞）。

## 九、增量九：成果物登记（真文件、真哈希）

`geoops/artifacts.py` 的 `ArtifactStore`：

- 登记时读真实文件，记 `sha256`、`size`、相对路径、所属任务、类型；索引原子落盘。
- 拒绝：文件不存在、是目录、是符号链接、同一内容重复登记、同一路径内容已变。
- `verify` 重算哈希；文件被改/被删都判失败，不沿用旧结论。报告新增
  `artifact_files` 段，没登记就写 `NOT_RECORDED`。

## 十、增量十：成果物绑定到已登记的成果对象

`ArtifactStore.register(..., deliverable_id=...)`：

- 绑定前先在 domain registry 里查：没注册、id 不存在、对象类型不是
  `Deliverable`，一律拒绝。**文件不能冒充未登记的成果**。
- 行里记 `deliverable_id`；`for_deliverable(id)` 按成果取文件。
- 同一路径原先没绑定时再要求绑定，也算冲突并拒绝。

## 十一、增量十一：令牌过期与轮换

`geoops/api/security.py`：

- 令牌可带 `issued_at` / `expires_at`（严格 `YYYY-MM-DDTHH:MM:SSZ`）；
  格式不对直接拒绝，不猜时间。
- 过期令牌**单独给出理由** `token expired`（HTTP 401），不混同为“未知令牌”；
  权限不足仍是 403。
- `expires_at` 早于 `issued_at` 拒绝。
- `revoke` 撤销授权；`rotate(old, new)` 换新并撤旧，可同时收窄权限。
- 修掉一个真实 bug：拒绝发生在读体之前时，服务端直接关连接会让内核发 RST，
  Windows 上客户端拿不到 401/403/413，测试三次里失败一次。现改为先有界读完
  请求体再关闭，连续 5 次全量运行均通过。

## 十二、增量十二：正射与变化检测规则包

`geoops/survey/packs/p02_products.json` + 8 个新校验器：

| 任务类型 | 规则 | 判定内容 |
|---|---|---|
| `ortho_generation` | R-OR-001 | CRS 必须是投影 EPSG；4326/4490/4258/4269/4610 与非法字符串一律 FAIL |
| | R-OR-002 | `gsd_m` 必须存在且为正数；缺失/非数字/≤0 FAIL |
| | R-OR-003 | `nodata` 未声明 → WARNING（0 也算已声明），不阻断但留痕 |
| | R-OR-004 | 成果文件必须存在且为常规文件 |
| `change_detection` | R-CD-001 | 两期路径都存在、都是常规文件、且不是同一个文件 |
| | R-CD-002 | 两期 CRS 必须一致，不一致 FAIL |
| | R-CD-003 | `min_area_m2` 未声明 → WARNING |

原来 8 段用 `ortho_generation` 演示“无规则任务”，现在该类型已有规则，
演示类型改为真正无规则的 `map_compilation`，避免结论失真。

## 十三、增量十三：规则门 + 成果登记，一次跑完

`geoops/delivery/nodes.py` 的 `artifact_register_node`：

- 登记变成流程节点，放在规则门之后；一次运行同时产出规则判定与文件哈希。
- 路径为空、登记被拒、哈希复核失败 → 节点 `FAIL`，后续节点自动 SKIPPED，
  不会“没核过就发布”。
- 通过的节点把登记行写进 `context["artifacts"][node_id]`，报告可直接取。

实测同一对节点两次：正射上下文干净 → 两节点 PASS、报告 4 条 PASS + 1 个文件
哈希；`EPSG:4490` → 规则门 FAIL、登记节点 SKIPPED、`artifacts=0`。

## 十四、增量十四：并发写与快照升级路径（先测后改）

先写 `geoops/tests/test_concurrency.py`（8 条），再改代码。测试当场暴露两个真问题：

1. `save` 用固定名 `<state>.tmp`，多线程同时保存会抢同一个临时文件，
   `os.replace` 直接 `WinError 5 拒绝访问`。改为 `tempfile.mkstemp` 每次独立临时名，
   保存段加进程内锁。
2. 读线程持着快照时，Windows 不允许替换目标文件（同样 WinError 5）。
   改为**有界重试替换**（最多约 3 秒），仍被占用则明确报错，不跳过。

同时：`load` 区分“旧版本（无迁移路径）”与“新版本（本构建读不懂）”，
不再是笼统一句 unsupported；成果索引的保存也改成唯一临时名 + 同一重试纪律，
登记/复核加锁；审计并发追加 4×25 行一条不丢。

随后全量连跑时又暴露两个真问题，都已修在代码里：

3. 读线程恰好在替换的瞬间 `open` 快照，`WinError 5` 直接抛出线程异常。
   `load` 改为**有界重试打开**，仍锁死则报 `StoreError`；读线程测试改为
   “任何异常都算失败”，不再只捕获 `StoreError`。
4. POST 到未知路径时服务端先答 404、再带着未读请求体关连接，内核发 RST，
   Windows 客户端偶尔拿不到 404。改为答 404 前先有界读尽请求体，
   并新增回归测试“同一请求连打 20 次都必须拿到 404”。

## 十五、增量十五：变化检测端到端（真栅格、真差分）

`geoops/survey/change.py`：

- `read_ascii_grid`：读 ESRI ASCII 栅格，校验必需头键（ncols / nrows /
  xllcorner / yllcorner / cellsize）、尺寸为整数、`cellsize > 0`、
  单元个数与 `ncols × nrows` 一致、非数字单元拒绝、重复头键拒绝、UTF-8-SIG 读入。
- `detect_changes`：两期原点/格网尺寸/格距必须对齐，否则 `grids are not aligned`；
  逐格比 `|后 - 前| ≥ threshold`，nodata 成对跳过并计数；
  4 邻域连通块分组，面积 = 单元数 × `cellsize²`；
  小于 `min_area_m2` 的斑块整块丢弃，报告 changed / kept / dropped / nodata 与面积。
- `write_change_mask`：以源头写出 0/1 掩膜，nodata 单元写 `-9999`，临时文件 + 原子替换。

`geoops/survey/change_node.py`：`change_detect_node` 把“两期路径 + 输出路径”
读成流程节点；缺路径、输出路径为空、`min_area` 非数字、栅格被拒 → 节点 `FAIL`，
后续节点自动 SKIPPED，**比较没发生就不会有掩膜被登记**；成功把统计写进
`context["change_result"]` 并附 `mask_path`。

冒烟第 16 段用一对可手算的真栅格跑通整链：

```
5 列 × 4 行，cellsize 10（每格 100 m²），右下角 1 个 nodata
comparison 在 row1 col1-2 改 10→20（2 格，200 m²）、row3 col2 改 10→30（1 格，100 m²）
min_area_m2=150 → changed=3、kept=2、dropped=1、dropped_patches=1、面积 200
规则门 → 差分节点 → 登记节点：mask 写出、哈希等于文件真哈希、绑定 DLV-SMOKE-002
把 comparison 的 xllcorner 挪 10 → 节点 FAIL，掩膜文件根本没被创建
```

## 十六、验证（当轮实跑，非计划）

```
python -m geoops.smoke
  → SMOKE PASS: 73 assertions，rc=0

python -m unittest geoops.tests.test_tasks geoops.tests.test_workflow \
                  geoops.tests.test_rules geoops.tests.test_rule_nodes \
                  geoops.tests.test_store geoops.tests.test_report \
                  geoops.tests.test_api_write geoops.tests.test_audit \
                  geoops.tests.test_artifacts geoops.tests.test_tokens \
                  geoops.tests.test_rule_packs geoops.tests.test_delivery \
                  geoops.tests.test_concurrency geoops.tests.test_change \
                  geoops.tests.test_journal geoops.tests.test_ui
  → Ran 166 tests, OK，rc=0
```

`test_concurrency` 连跑 5 次全绿（8 条：并行保存、读写并存、无残留临时文件、
旧/新版本拒绝、并行登记不同文件与同一文件、并行审计追加）；全量再连跑 5 次全绿
（含读线程在替换瞬间被锁、POST 未知路径的 404 两类回归）。
各模块实测条数：`test_tasks` 12、`test_workflow` 11、`test_rules` 12、
`test_rule_nodes` 7、`test_store` 8、`test_report` 7、`test_api_write` 13、
`test_audit` 10、`test_artifacts` 16、`test_tokens` 10、`test_rule_packs` 12、
`test_delivery` 7、`test_concurrency` 8、`test_change` 13、`test_journal` 11、`test_ui` 9。

冒烟关键事实：`RUN-SMOKE-002` 真失败、`RUN-SMOKE-003` 由它恢复；
规则节点真拦住成果节点（`RUN-SMOKE-006`），修好 CRS 后放行（`RUN-SMOKE-007`）；
快照保存后在新对象上恢复，任务状态/版本/两条 run 全部保留，坏 JSON 与旧版本被拒；
`RUN-SMOKE-012` 用一对可手算栅格跑完“变化规则门 → 差分 → 掩膜写出 → 哈希登记”，
`RUN-SMOKE-013` 错位栅格在写掩膜前就失败。
内核 `kernel/bumao_core/` 仍 v0.2.2 原样，只读引用，零写入。

回退凭据：本轮起每个增量都已提交，回退用 `git checkout <commit> -- <file>`；
工作树里的 `*.bak-261116-*` 是更早增量留下的未跟踪备份，不 add、不删。

## 十七、增量十六：前端骨架（书香底，接真数据）

视觉不是另起一套：底色与版式对齐 `HX\personal / community / minimal` 三套前端
（宣纸径向底、字重 300、玻璃卡、等线正文、Bahnschrift 微标签、发丝表格、胶囊徽章、
34/26/18/12 圆角、`cubic-bezier(.16,1,.3,1)` 过渡），默认纸色取书香一套
（宣纸 / 青瓷 / 赭石 / 松烟 / 大山），可切深空夜纸，A−/A+ 调字号。

交付：

- `geoops/web/index.html` + `ui.css` + `ui.js`：左栏（品牌 / 六段导航 / 等级卡）+
  顶栏（等级 / 版本 / 内核 / 连接态 / 令牌 / 字号 / 纸色 / 明暗）+ 正文六段：
  概览（四联 KPI、工程身份、未清门槛、审计摘要、骨架已接未接）、任务（状态筛选 +
  搜索 + 真实表格）、流程（运行历史接口未开放的诚实空态 + 登记链路）、
  规则（规则包元数据 + 按任务类型分组的规则行）、成果（需 `audit:read` 的登记簿）、
  审计（allow/deny 流水）。
- `GET /api/v1/overview`（只给计数，不给记录/路径）、`GET /api/v1/rules`
  （包元数据从磁盘规则包读）、`GET /api/v1/artifacts`（`audit:read`，返回登记行）；
  静态入口只放行 `/ui/`、`/ui/index.html`、`/ui/ui.css`、`/ui/ui.js` 四个白名单。
- `python -m geoops.api [--demo] [--tokens F] [--audit F] [--artifacts F]`：
  一条命令同时起接口与前端；不给 `--tokens` 时是只读服务。

纪律：页面只渲染接口真实返回；缺接口写「未开放」，缺令牌写「需令牌」，
空列表写「未记录」，不填演示数字。规则行显示的是规则自身的「阻断 / 警告」，
不是判定结果。`docs/ui-preview/` 里的五张截图是本地服务真实截屏，不是设计稿。

## 十八、增量十七：运行日志、流程页与桌面快捷方式

「流程」页不再是空态。运行记录有了正式的写入与读取路径：

- `geoops/workflow/journal.py`：`RunJournal` 只记录**已跑完**的运行，一行一条 JSON，
  带 task / project / actor / 时间戳，`fsync` 后才返回；重复 `run_id` 拒绝；
  坏行或截断行让整份日志拒绝装载，不静默丢行。`--runs FILE` 落盘，不给就是内存日志。
- `GET /api/v1/runs`：返回运行、节点判定与 `by_status` 计数。节点只给 `detail`，
  不含节点 `output` 里的文件路径。
- `--demo` 现在真的跑一次工作流（`map_compilation` 在现有规则包里无适用规则，
  节点如实记 `SKIP`，不冒充 `PASS`），再登记任务、写日志；不是空记录。
- 前端「流程」页接这份日志：run id、任务、状态、节点数、跳过数、`resumed_from`、
  时间，逐节点列出判定与说明；没有挂日志写「未配置」，没有记录写「还没有运行记录」。

桌面快捷方式：项目根 `启动布猫测绘智序.cmd` + 桌面与仓库各一个
`布猫·测绘智序.lnk`。双击先探 8790 是否已在监听（`netstat`），没在才起
`python -m geoops.api --demo`，再打开 `http://127.0.0.1:8790/ui/`；
已有人在跑就只开页面，不抢端口。

验证：`test_journal` 11 条（记录、重复拒绝、失败/跳过节点、`resumed_from`、
状态计数、重启装载、坏文件与重复行拒载、目录缺失、limit、8 线程并发）；
`test_ui` 增加 runs 200 与无日志 404 两条；冒烟第 17 段加两条（日志服务真
变化检测运行、重复 run_id 被拒）。全量 166 条、冒烟 73 条。新增截图
`docs/ui-preview/runs.png`，其余截图按 3 任务的新演示数据重截。

## 十九、未做（不写「已完成」）

- 持久化仍是单文件快照，不是事务库；**同一进程内并发已测**，跨进程并发没有文件锁，
  多进程同时写同一份快照不在保证范围内。
- 真实 AI 模型、真实 GIS 工具适配器：0.1 验收第 5、7 项未过。
- 令牌已有过期、撤销、轮换；仍无统一身份源（如 OIDC），轮换靠人工改文件。
- 成果物能登记、能绑成果、能复核，但文件内容是占位字节，真实生产数据链路未建。
- 变化检测做的是**像元级真差分**（ASCII 栅格、连通块、最小面积过滤），但：
  真实 GeoTIFF 读写、坐标重投影、配准误差与精度评定仍未做；
  面积单位只有栅格为米制投影时才等于平方米，由规则门负责把关，程序本身不判断。
- 前端仍是**骨架**：写操作、地图视图、登录页与会话管理没做；页面上的令牌是人工填入；
  未做浏览器端自动化测试，只做了脚本语法检查、接口断言与真机截屏。
- 运行日志只有单进程写入保证（进程内锁 + `O_APPEND`）；多进程同时写同一份日志未做文件锁。
- 未发布：等级为核心工程，但发布资格未达成。

## 二十、下一轮顺序（本工程内）

1. 成果物索引与快照一起存，恢复后仍可复核（当前索引与快照是两份文件）。
2. 跨进程写快照：先测，再决定是否引入文件锁；日志同理。
3. 写操作界面（建任务 / 迁移状态），仍然先权限后接口。
4. 变化检测接真 GeoTIFF 之前，先把 ASCII 链路的“掩膜 + 统计”做成可存档的成果格式。

## 二十一、2026-11-17 增量：0.1 领域层与九段前端

本轮只改 `<repo>`，不写 personal 仓。

### 做了什么

- 项目登记：六字段必填、编号唯一，重复 id / code 拒绝（`geoops/domain/projects.py`）。
- 数据集登记：真读文件算 sha256，CRS 来自 sidecar 或 classic GeoTIFF 头；非 READY 拒绝；
  `validate` 重探测，内容变了即 FAIL（`geoops/domain/datasets_store.py`）。
- GeoTIFF 头解析器：ModelPixelScale / ModelTiepoint / GeoKeyDirectory，读 EPSG、宽高、波段、
  范围、像元大小；BigTIFF 与像元解码明确不做（`geoops/geotiff.py`）。
- 目录：模型 / 工具 / Agent 分开登记；`builtin:` 必须是仓内真实实现，`external:` 路径不存在
  即标不可用并给原因；Agent 引用未知 id 直接拒绝，可用性随依赖（`geoops/catalog.py`）。
- 审核门：只有 APPROVE 置 `accepted`；REJECT / RERUN 必须写意见；已签认拒绝二次审核
  （`geoops/review.py`）。
- 结构化追溯：项目 → 数据集 → 运行 → 规则节点 → 成果 → 文件 → 审核；缺环写
  `NOT_RECORDED` 并给原因，`complete=false`（`geoops/trace.py`）。
- 写权限扩到 `project/dataset/catalog/review:write`；GET/POST 路由、概览计数、审计留痕
  （`geoops/api/app.py`、`security.py`）。
- 前端从六段扩到九段：数据 / 审核 / 追溯三页；项目与数据集登记表单、数据集复核按钮、
  目录可用性、审核提交、任务追溯（`geoops/web/*`）。桌面快捷方式沿用上一轮。
- 测试：`test_release.py` 18 条、`test_api_release.py` 8 条、`test_geotiff.py` 3 条；
  全量 **196 tests OK**；smoke **73 assertions PASS**（导航断言改为九段）。

### 真机证据

- `docs/ui-preview/data.png`：项目 1 个、数据集 1 个（真实 sha256 与 CRS）、目录 3 项。
- `docs/ui-preview/reviews.png`：审核空态 + 提交表单（未填令牌，不伪造记录）。
- `docs/ui-preview/trace.png`：`TSK-4ba294052b` 追溯链，五环命中，缺成果/审核两环写
  NOT_RECORDED，整体 PARTIAL。
- `docs/ui-preview/tasks-write.png`：任务写操作卡（上轮完成）。

### 尚未过（0.1 验收）

第 3/5/6/7/10/11/13/14 项仍未全过：没有用户提供的真实遥感影像；没有真实 AI 模型运行时；
Agent 只有目录与依赖校验，没有执行器；机器未装 GDAL/QGIS/Rasterio，外部 GIS 工具适配器
无法真跑；质检停在文件/CRS/哈希与 ASCII 网格结构；质检报告未接入新审核链；成果对象登记
API 与归档版本链未补齐。逐项对照见 `docs/ENGINEERING_TIER.md` 第六节。

### 下一轮

1. 成果登记 API + 归档版本，把追溯链补到 COMPLETE。
2. 质检执行 API：质检结果写入 QualityReport，审核前要求质检 PASS。
3. Agent 执行器：按目录里的 model_ids/tool_ids 真串一次作业，记录每次调用。
4. 真实 GeoTIFF 读写与外部 GIS 工具适配器（需先确认依赖来源与授权）。

## 二十二、2026-11-17 增量：书香 v2.0、十二段前端、成果/质检/设置

本轮只推 `bumao_geoops`，不写 personal 或其他工程，不 push。

### 前端

- `geoops/web/ui.css` 全量重写，按 HX 书香 v2.0 硬色板落地：宣纸 `#F3EEE3/#EDE6D6`、墨字
  `#2B2620/#1F1B16`、青瓷 `#6F9C8F`、朱砂 `#B5495B`、黛蓝 `#3C4A5A`、赭石 `#A8642F`、
  留白金 `#C9A86A`；暗色暖纸 `#211D18/#1A1713`、暗字 `#E9E2D3`。无纯白、纯黑、彩虹渐变。
- 左书脊改为 252px 黛蓝底、留白金细边、朱砂呼吸点；页首题签 + 模块印章；KPI 四区；
  纸卡金线；主按钮青瓷→黛蓝微渐变。
- 导航扩到十二段：总览 / 项目 / 任务 / AI 资源 / 数据 / 流程 / 规则 / 质量 / 成果 / 审核 /
  追溯（含审计） / 设置。项目页、AI 资源页、质量页、成果页、设置页均为真实接口。
- 桌面快捷方式沿用 `启动布猫测绘智序.cmd`，仍探测 8790 后启动并打开 `/ui/`。

### 功能

- `geoops/domain/deliverables.py`：成果登记（真实文件、sha256、大小、版本、任务绑定），
  只有 `accepted` 后 `archive` 才成功，归档写人/时间/备注。
- `geoops/quality/service.py`：三层质检。文件层查存在/普通文件/大小/sha256；空间层查 CRS、
  宽高、范围（缺则 NOT_RECORDED）；专业层必须有人工抽样与书面依据，否则 PARTIAL。
  报告原子写入 `var/quality/QR-*.json` 并登记 `QualityReport`。
- `geoops/api/app.py`：新增 `GET/POST /api/v1/deliverables`、
  `POST /api/v1/deliverables/<id>/archive`、`GET/POST /api/v1/quality-reports`、
  `GET /api/v1/settings`；权限新增 `deliverable:write` 与 `quality:write`；概览计数新增
  deliverables / quality_reports。
- 设置接口返回真实角色矩阵、权限键、调用方令牌授权、存储配置状态；不在前端伪造角色。

### 验证

- 新增 `geoops/tests/test_quality_deliverable.py` 7 条、`geoops/tests/test_api_quality.py` 3 条。
- 全量 **206 tests OK**。
- 真机质检：`DS-f4ca020bf593`（3×2 ASCII + sidecar，样例数据）与
  `DLV-ac0105fd55` 均生成 `PARTIAL` 报告；`QR-f84ef6838a` 写入
  `var/quality/QR-f84ef6838a.json`。样例只验证质检链路，不作为真实遥感影像验收。
- 实拍十二张 `docs/ui-preview/v2-*.png`，Chrome headless 1500px。

### 仍未过（如实）

第 3/5/6/7/10/14 项：无用户真实遥感影像；无真实 AI 模型运行时；Agent 无执行器；机器无
GDAL/QGIS/Rasterio；质检缺分类/几何精度指标；追溯需运行与文件环填满。0.1 不宣称正式完成。
## 二十三、2026-11-17 增量：真实模型运行时接入

### 代码

- 新增 `geoops/ai/runtime.py`：OpenAI-compatible `POST /chat/completions` 客户端。
  端点/密钥/模型只从 `GEOOPS_MODEL_BASE_URL`、`GEOOPS_MODEL_API_KEY`、`GEOOPS_MODEL_NAME`
  读取；未配置抛 `NOT_CONFIGURED`，不生成占位回复。
- 新增 `geoops/ai/nodes.py`：`model_chat_node` 在 workflow 内发起真实模型调用，记录
  text/model/usage/elapsed_ms；未配置时运行记录为 `ERROR`，不会假装 `PASS`。
- 新增 `geoops/ai/__main__.py`：`python -m geoops.ai status|probe|chat`，不启动服务也能验证。
- API 新增 `GET /api/v1/model-runtime`、`POST /api/v1/model-runtime/probe`、
  `POST /api/v1/model-runtime/chat`；权限新增 `model:invoke`，调用写审计。
- 控制台 AI 资源页新增“模型运行时”卡片：状态、模型、端点、认证、超时；测试连接与
  运行模型均发真实请求，回复/耗时/token 用量回显。未配置显示 NOT_CONFIGURED 并在输出框
  写明缺哪个环境变量。
- `启动布猫测绘智序.cmd` 在 `var\console-tokens.json` 存在时自动带 `--tokens`；
  本机明文令牌放 `var\console-token.txt`，`var/` 已被 .gitignore 忽略。
- 新增 `docs/MODEL_RUNTIME.md`：Ollama / LM Studio / vLLM / 云端 OpenAI-compatible
  的启动命令、三种验证方式、错误码、边界与安全约束。

### 验证

- `test_model_runtime.py` 7 条：未配置拒绝、真实本地 HTTP 提供方请求体与鉴权、上游 401
  不泄露密钥、workflow 节点真实调用、API probe/chat 与令牌权限。
- 全量 **213 tests OK**；smoke **73 assertions PASS**。
- 控制台实拍 `docs/ui-preview/v2-model-runtime.png`：AI 资源页 + 真实 NOT_CONFIGURED 状态。
- 当前机器无模型端点，未虚构任何模型回复；需要用户提供端点/模型/密钥后才会 READY。