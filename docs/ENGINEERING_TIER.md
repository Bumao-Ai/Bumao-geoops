# 工程等级：核心工程（core）

本文件是本工程等级的唯一登记处（2026-11-16 用户指示：将本工程升级为核心工程）。
等级只登记在本仓库，不写入其他工程。

## 一、决定

- 日期：2026-11-16
- 决定人：用户（本工程负责人）
- 原等级：未登记（`geoops/meta.json` 仅有 `name / version / zero_rules`）
- 新等级：核心工程（core）
- 生效范围：`<repo>` 全仓

## 二、核心工程判定标准（本仓库自定义，全部可核）

1. **内核不复制**：只经 `geoops/core_adapter` 调用 `kernel/bumao_core/`，内核文件零写入。
2. **状态与执行分离**：任务状态机独立于流程执行；非法变更拒绝，且拒绝不落半条记录。
3. **失败可恢复**：流程从失败节点恢复，已通过节点带原输出前移，节点身份变化即拒绝。
4. **规则即数据**：规则包声明式定义；五态判定；校验器缺失或异常绝不判 PASS。
5. **状态可持久**：快照原子写，恢复前整包校验，坏包整包拒绝、不半恢复。
6. **变更可追溯**：改前留 `.bak`，单次真实运行写档，git 提交，未做项如实列出。
7. **结果可复现**：`python -m geoops.smoke` 与 `python -m unittest ...` 必须可重复通过。

## 三、当前证据（2026-11-16 实跑）

| 标准 | 证据 |
|---|---|
| 内核不复制 | smoke `core surface complete`、`all host gates pass`；`kernel/bumao_core/` 无改动（git 仅见早先 `.bak_20261109`） |
| 状态与执行分离 | `geoops/domain/tasks.py`；smoke 2b 段 7 条断言；`test_tasks` 12 条 |
| 失败可恢复 | `geoops/workflow/executor.py`；smoke 5b/5c 段；`test_workflow` 11 条 |
| 规则即数据 | `geoops/survey/rules.py` + `packs/p01_dataset.json`；smoke 8 段；`test_rules` 12 条 |
| 规则接入流程 | `geoops/survey/nodes.py`；smoke 8b 段 4 条；`test_rule_nodes` 7 条 |
| 状态可持久 | `geoops/store.py`；smoke 9 段 3 条；`test_store` 8 条 |
| 记录可成文 | `geoops/quality/report.py`；smoke 10 段 2 条；`test_report` 7 条；缺段写 `NOT_RECORDED` |
| 写入口有权限位 | `geoops/api/security.py` + `geoops/api/app.py`；smoke 7b 段 5 条；`test_api_write` 11 条；拒绝入审计 |
| 令牌与审计可落盘 | 哈希-only 令牌文件（明文即拒）、过期/撤销/轮换、JSONL 审计 `fsync`、坏行拒绝；smoke 11 段 3 条 + 13 段 3 条；`test_audit` 10 条、`test_tokens` 10 条 |
| 成果物可登记可复核 | `geoops/artifacts.py`；sha256+size+路径+所属任务+绑定成果，改/删即判失败，未登记成果拒绑；smoke 12 段 8 条；`test_artifacts` 16 条 |
| 规则可核到字段 | 两包 11 条规则（分类/正射/变化检测），每条给证据字段；地理坐标系拒作成果 CRS；smoke 14 段 4 条；`test_rule_packs` 12 条 |
| 判定与登记同一跑 | 规则门 → `artifact_register_node`；CRS 不对即停，登记未发生；smoke 15 段 5 条；`test_delivery` 7 条 |
| 像元级也是真算 | 两期 ASCII 栅格逐格差分 + 4 邻域连通块 + 最小面积过滤，面积按 `cellsize²` 计；smoke 16 段 4 条；`test_change` 20 条 |
| 看得见且不造假 | `/ui/` 六段控制台（概览/任务/流程/规则/成果/审计），书香纸色 + 深空夜纸；流程页接运行日志（节点判定 + 跳过数 + 恢复来源）；缺接口写「未开放」、缺令牌写「需令牌」；smoke 17 段 4 条；`test_ui` 9 条、`test_journal` 11 条；`docs/ui-preview/` 六张真实截图；桌面快捷方式一键起服务 |
| 并发纪律已验 | 唯一临时名 + 进程内锁 + 读占用时读写双侧重试；旧/新版本各自拒绝；`test_concurrency` 8 条（连跑 5 次全绿）；全量连跑 5 次全绿 |
| 变更可追溯 | 提交 `22f3fc4`、`9f80d77`、`43d2c03`、`ef76fab`、`66a86a2`、`8e3d12a`、`4ae7bdc`、`4b6e6e5`、`4790816`、`ac4e9d4`、`785fdb2`、`9a4a187`、`3a611ab`、`7308af0`、`986faf8`、`ed95c9e` 及本轮提交 |
| 结果可复现 | `SMOKE PASS: 73 assertions`；`Ran 320 tests, OK` |

## 四、升级为核心工程后，仍未达成的门槛（不粉饰）

1. 持久化是单文件 JSON 快照，不是事务数据库；同进程并发已测，跨进程并发无文件锁、不在保证范围内。
2. OpenAI-compatible 模型运行时已实现，但当前没有指向任何真实模型端点；真实 GIS 工具只接了内置 ASCII profile，GDAL/QGIS/Rasterio 适配器未接（0.1 验收第 5 项部分、第 7 项内置工具通过）。
3. 令牌已有过期、撤销与轮换；仍无统一身份源，轮换靠人工改文件。
4. 成果物可登记与哈希复核；变化检测已产出真实计算出的掩膜文件，但正射等成果仍是占位字节，真实生产数据链路未建。
5. 变化检测已支持 ASCII/GeoTIFF 栅格读取，并可写出 ASCII 或单波段 float32 GeoTIFF 掩膜（带源 CRS、像元尺度、Tiepoint、NODATA）；重投影、配准误差与真实精度评定未做。
6. 未发布（0.1.0，探索阶段产物；等级≠发布资格）。

## 五、结论

本工程**登记为核心工程**；发布资格仍未达成。上述第 1–4 项未清之前，
不得以「核心工程已完备」对外表述；每次发布前须重新过第二节清单。

## 六、0.1 十五项验收对照（2026-11-18，逐项如实）

| # | 验收项 | 状态 | 依据 / 缺口 |
|---|---|---|---|
| 1 | 建真实项目 | 通过（软件路径） | `ProjectRegistry` 六字段必填、编号唯一；`POST /api/v1/projects`；数据页表单 |
| 2 | 建真实任务 | 通过（软件路径） | `TaskEngine.create` 要求项目已登记；七态状态机；写操作页与 API |
| 3 | 导入真实遥感影像 | 部分 | 数据集登记读真实文件算 sha256；GeoTIFF（classic/BigTIFF）已支持未压缩/LZW/Deflate、条带/分块、chunky/分开波段像素解码，JPEG/JPEG2000 可选 Pillow 解码；尚无用户提供的真实遥感影像入库 |
| 4 | 识别必要空间元信息 | 部分 | classic GeoTIFF 与 BigTIFF 读 EPSG/宽高/波段/范围/像元大小；ASCII + sidecar；投影变换未做 |
| 5 | 登记并调用真实 AI 模型或算法 | 部分 | 目录登记 + `builtin:change_detection` 真跑逐格差分；OpenAI-compatible 模型运行时与 workflow `model_call` / `agent_execute` 已实现，但当前未配置真实端点 |
| 6 | 用 Agent 组织执行过程 | 部分 | Agent 目录、依赖校验、JSON 计划循环、声明工具白名单、内置工具真实执行与 `tool_calls` 记录已做；外部工具可经 `external:<id>` 配置执行，真实模型端点仍缺 |
| 7 | 调用至少一种真实地理空间处理工具 | 通过（内置工具） | `gis_tool_call` 真实调用 `builtin:ascii_grid_profile`（读 ASCII/GeoTIFF 栅格、校验像元、算有效格数/最值/均值）；`external:<id>` 可按 `var/external-tools.json` 调用真实可执行程序，未配置或退出非零即 `ERROR`；GDAL/QGIS/Rasterio 本体未安装 |
| 8 | 执行测绘专业规则 | 通过 | 规则包 11 条、五态结果、闸门节点；异常不判 PASS |
| 9 | 记录整个 AI 作业过程 | 部分 | 工作流定义、节点输出、运行日志、审计、任务历史、结构化追溯均有；Agent `tool_calls` 现记录成功与失败调用，外部工具调用带渲染命令、退出码、stdout/stderr、超时与耗时；仍无真实外部 GIS 工具在用户环境执行 |
| 10 | 对成果自动质量检查 | 部分 | 三层检查已实现；混淆矩阵（TP/FP/FN/TN、pixel_accuracy、precision、recall、F1、IoU）支持 ASCII 与 GeoTIFF 掩膜，并校验尺寸、像元大小、原点与 CRS；调用方可声明最低精度阈值，低于阈值即 FAIL，不预设默认阈值；真实影像分类/几何精度样本仍缺 |
| 11 | 输出质检报告 | 通过（软件路径） | `QualityService` 原子写 `var/quality/QR-*.json` 并登记 `QualityReport`；报告含 `basis`/`method`/`data`/`evidence`/`program`；审核引用报告时 `APPROVE` 必须是 `PASS` |
| 12 | 人工审核 | 通过 | `ReviewEngine` + `POST /api/v1/reviews` + 审核页；通过才 accepted，驳回/返工必须写意见；`review` 流程节点只查真实 APPROVE，不自动批准；合成成果禁止最终验收 |
| 13 | 归档最终成果 | 通过（软件路径） | `DeliverableRegistry` 真文件登记 sha256/大小/版本；归档前重算哈希，缺文件或被改即拒；控制台归档到 `var/archive/<成果编号>/` 并写 `manifest.json`；accepted 后 `POST /api/v1/deliverables/{id}/archive` 归档并留人/时间 |
| 14 | 从成果反向追溯 | 部分 | `/api/v1/tasks/{id}/trace` 与 `/api/v1/deliverables/{id}/trace` 出结构化链；已用合成数据集、成果文件、artifacts、审核记录跑出 `complete=True`，真实数据环仍需填满 |
| 15 | 证明正确调用 Core 不复制内核 | 通过 | vendored kernel 只读导入，CoreAdapter 调真实注册/闸门；smoke 1 段 |

结论：**十五项未全过，0.1 不能宣称正式完成。** 软件层（1/2/4/7/8/11/12/13/15）已可跑；
3/5/6/9/10/14 的代码执行路径已实现（GeoTIFF 条带像素、Agent 工具循环与 `tool_calls`、节点策略、外部工具配置、GeoTIFF 掩膜精度入口），但真实影像、真实模型端点、真实审核样本和完整真实验收环仍未提供，因此这些项仍按“部分”记录，缺口已写进 README 与 CHANGELOG。

真实验收所需的外部输入与逐步核对方法见 `docs/ACCEPTANCE_HANDOVER.md`。









































