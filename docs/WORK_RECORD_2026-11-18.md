# 2026-11-18 工作记录：流程定义与执行

## 本日完成

- 流程定义从“只能内存调用”升级为可校验、可持久化的记录：
  - `WorkflowDefinitionRegistry`：节点 1–50 个，`node_id` / `name` 唯一，类型白名单，类型专属字段校验；原子写 `var/workflows.json`，坏文件整份拒绝。
  - 定义登记后执行时按记录建节点，不执行另一套隐藏闭包。
- 节点类型覆盖 0.1 规格：`data_input`、`data_check`、`model_call`、`agent_execute`、`gis_tool_call`、`rule_check`、`change_detection`、`artifact_register`、`review`、`output`、`model_chat`。
- 新增真实节点：
  - `data_input` / `data_check`：读 `DatasetRegistry` 真实记录，校验项目归属、sha256 与 CRS；缺记录 `FAIL`，探针异常 `ERROR`。
  - `agent_execute`：解析目录 Agent，校验依赖可用性；模型返回 JSON 计划后，只执行 Agent 声明的内置工具，记录 `tool_calls`、参数和结果，循环到 final 或步数上限；不伪造工具执行。
  - `review`：只查真实 `APPROVE` 或最终验收成果；缺失审核 `FAIL`，不自动批准。
  - `gis_tool_call`：内置 `builtin:ascii_grid_profile` 真读 ASCII 栅格、算有效格数/最值/均值；其他 tool id 明确 `ERROR`。
- 执行器写入 `context["node_outputs"][node_id]`，下游节点可读；`resume` 复用已通过节点输出，从失败节点重启；节点数量/身份变化拒绝。
- API：
  - `GET/POST /api/v1/workflows`、`GET/POST /api/v1/workflows/<id>`、`POST .../execute`。
  - `GET /api/v1/workflow-runs`、`GET .../<run_id>`、`POST .../<run_id>/resume`。
  - `GET /api/v1/quality-checks` 与 `/quality-reports` 同义。
  - `POST /api/v1/tasks/<id>/start|pause|resume|cancel` 作为状态机薄别名。
  - `GET /api/v1/deliverables/<id>/trace` 从成果反查任务/运行/审核。
  - `POST /api/v1/deliverables/<id>/artifacts` 把真实文件 sha256 绑定到成果，写入 artifact 索引。
- 权限新增 `workflow:write` / `workflow:execute`（共 12 项），角色矩阵同步。
- 审核记录可关联 `quality_report_id`；报告必须针对同一成果，否则拒绝；`APPROVE` 只接受状态为 `PASS` 的质量报告，且合成成果不能最终验收。
- 节点策略：`retry` 真实重试失败/异常节点，`NodeRun.attempts` 记录次数；`failure_action=continue` 允许下游继续，但 run 仍保持失败。`preconditions` 按点路径检查，缺失即 `FAIL`；`outputs` 把节点输出字段映射为上下文别名；`success_condition` 支持 `PASS`、`status` 比较和点路径比较，不满足即 `FAIL`。
- 质量精度：新增 `geoops/quality/metrics.py`，读对齐的 ASCII 栅格，算 TP/FP/FN/TN、pixel_accuracy、precision、recall、F1、IoU；NODATA 单元排除；尺寸/像元不一致拒绝。
- 质检 API 接受 `reference_path`、`predicted_path`、`synthetic_reference`，报告写入 `accuracy`，并加 `professional.accuracy` 检查。
- 质检报告写入 `basis`、`method`、`data`（目标/参考/预测路径）与 `evidence`（目标 id、路径、sha256、检查数、是否算精度），不只给一个 status。
- 合成数据来源标记：数据集与成果登记支持 `synthetic`，质检报告继承该标记；合成数据不会被当成真实资产。

## 验证

```text
python -m unittest discover -s geoops\tests -t .
Ran 264 tests in 26.3s
OK

python -m geoops.smoke
SMOKE PASS: 73 assertions
```

真实服务验证（8795，带 `--artifacts var\artifacts.json --runs var\runs.jsonl`）：

- `POST /api/v1/workflows/WF-CHANGE-001/execute`：规则门 3 条全 PASS，逐格差分写掩膜，成果登记 sha256，run 状态 `PASS`。
- 数据集登记 `DS-f4ca020bf593`；`WF-RESUME-API` 首跑在差分节点 `FAIL`，`POST /api/v1/workflow-runs/RUN-3f7a32b13758/resume` 后首节点 `REUSED`、差分 `PASS`、面积 200.00 m²。
- `GET /api/v1/workflow-runs`、`GET /api/v1/artifacts` 返回真实数量；`/quality-checks` 可用。
- `POST /api/v1/tasks/TSK-8278a9f9d2/start` 把任务推进到 `RUNNING`；随后 `WF-GATE-001` 执行 `PASS`，任务 `workflow_run_ids` 真实追加 `RUN-c8ecd59348a4`。
- 登记真实文件成果 `DLV-60cba22060`；`GET /api/v1/deliverables/DLV-60cba22060/trace` 返回结构化链，并如实列出 `datasets` / `artifacts` / `review` 三项 `NOT_RECORDED`。

合成数据验证（8796，全部标注 `SYNTHETIC`，不是真实遥感成果）：

- 任务 `TSK-8a394e2f32` 由 `start` 推进到 `RUNNING`；数据集 `DS-f4ca020bf593` 绑定该任务。
- `WF-TRACE-CHANGE` 用 `var/demo/baseline.asc` / `comparison.asc` 真算变化，因 `min_area_m2=150` 丢弃 2 个 100 m² 小斑块，输出全零 `trace_mask.asc`，run `PASS`；未伪造 changed 面积。
- 复制真实输出为 `trace_artifact.asc`，登记成果 `DLV-75cf0f3416`；`WF-TRACE-ART` 真算 sha256 并绑定 artifact `ART-f32f823c627c`。
- 质量报告 `QR-40378db122`：对 `change_mask.asc`（合成参考）与 `trace_artifact.asc` 算得 `tp=0, fp=0, fn=2, tn=4`、`pixel_accuracy=0.667`、`recall=0`、`IoU=0`，报告 `PARTIAL`（缺真实空间绑定/真实抽样）。
- 审核 `RV-9959bb50bc` 为 `REJECT`，意见明确标注合成与全零掩膜；没有把合成数据伪装成验收通过。
- `GET /api/v1/deliverables/DLV-75cf0f3416/trace` 返回 `complete=True`、`missing=0`、`links=8`、`artifacts=1`、`datasets=1`、`reviews=1`；证明追溯链结构可闭合，但不能替代真实数据验收。

## 仍未完成（不粉饰）

- 没有用户真实遥感影像；classic GeoTIFF 已支持未压缩/Deflate 条带像素解码，LZW、分块、分开波段仍不支持。
- 模型运行时存在但当前 `NOT_CONFIGURED`；没有真实模型端点。
- Agent 已能执行声明的内置工具；外部工具只能通过显式配置的 `external:<id>` 真实子进程执行，未配置即报错，GDAL/QGIS 本体未安装。
- 真实分类精度/几何精度与真实完整追溯环仍缺；合成 ASCII 掩膜混淆矩阵、合成追溯闭环已跑通，不能替代真实验收。
- 0.1 十五项未全过；软件路径 1/2/4/7/8/11/12/13/15 可跑，3/5/6/9/10/14 仍部分。

## 代码位置

- `geoops/workflow/definitions.py`：定义校验与持久化。
- `geoops/workflow/service.py`：定义 → 节点 → 执行 / 恢复 → journal。
- `geoops/workflow/data_nodes.py`：数据集与审核节点。
- `geoops/workflow/executor.py`：节点重试、失败继续策略与 `attempts` 记录。
- `geoops/quality/metrics.py`：ASCII 掩膜混淆矩阵与精度指标。
- `geoops/tests/test_quality_metrics.py`：精度指标测试。
- `geoops/geotiff.py`：经典 TIFF 头/GeoKey + 未压缩/Deflate 条带像素解码。
- `geoops/workflow/gis_nodes.py`：内置 ASCII/GeoTIFF 栅格剖面工具与 `external:<id>` 外部程序适配。
- `geoops/workflow/external_tools.py`：显式工具配置、参数占位符、无 shell 子进程执行与非零退出报错。
- `geoops/ai/agent_executor.py`：Agent JSON 计划、工具白名单、内置工具执行、步数上限与 `tool_calls`。
- `geoops/ai/agent_node.py`：兼容旧导入路径的 Agent 节点入口。
- `geoops/api/app.py`：API 路由与权限。
- `docs/WORKFLOW_ENGINE.md`：使用说明和边界。

本地提交：`78727fc`、`f72b906`、`314cbee`、`6889ad4`、`3195a3d`、`aadfbed`、`1a8c547`（重试/失败策略、精度指标、审核闸门）、`c833163`（合成数据来源标记）、`66ff316`（成果 artifact 绑定 API）、`cb2cf6f`（拒绝合成成果最终验收）。远程未 push。




