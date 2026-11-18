# 2026-11-18 工作记录：流程定义与执行

## 本日完成

- 流程定义从“只能内存调用”升级为可校验、可持久化的记录：
  - `WorkflowDefinitionRegistry`：节点 1–50 个，`node_id` / `name` 唯一，类型白名单，类型专属字段校验；原子写 `var/workflows.json`，坏文件整份拒绝。
  - 定义登记后执行时按记录建节点，不执行另一套隐藏闭包。
- 节点类型覆盖 0.1 规格：`data_input`、`data_check`、`model_call`、`agent_execute`、`gis_tool_call`、`rule_check`、`change_detection`、`artifact_register`、`review`、`output`、`model_chat`。
- 新增真实节点：
  - `data_input` / `data_check`：读 `DatasetRegistry` 真实记录，校验项目归属、sha256 与 CRS；缺记录 `FAIL`，探针异常 `ERROR`。
  - `agent_execute`：解析目录 Agent，校验依赖可用性，再调用真实模型语言层；不冒充执行 GIS 工具。
  - `review`：只查真实 `APPROVE` 或最终验收成果；缺失审核 `FAIL`，不自动批准。
  - `gis_tool_call`：内置 `builtin:ascii_grid_profile` 真读 ASCII 栅格、算有效格数/最值/均值；其他 tool id 明确 `ERROR`。
- 执行器写入 `context["node_outputs"][node_id]`，下游节点可读；`resume` 复用已通过节点输出，从失败节点重启；节点数量/身份变化拒绝。
- API：
  - `GET/POST /api/v1/workflows`、`GET/POST /api/v1/workflows/<id>`、`POST .../execute`。
  - `GET /api/v1/workflow-runs`、`GET .../<run_id>`、`POST .../<run_id>/resume`。
  - `GET /api/v1/quality-checks` 与 `/quality-reports` 同义。
  - `POST /api/v1/tasks/<id>/start|pause|resume|cancel` 作为状态机薄别名。
  - `GET /api/v1/deliverables/<id>/trace` 从成果反查任务/运行/审核。
- 权限新增 `workflow:write` / `workflow:execute`（共 12 项），角色矩阵同步。
- 审核记录可关联 `quality_report_id`；报告必须针对同一成果，否则拒绝。

## 验证

```text
python -m unittest discover -s geoops\tests -t .
Ran 227 tests in 23.5s
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

## 仍未完成（不粉饰）

- 没有用户真实遥感影像；GeoTIFF 仅读头，不解码像元。
- 模型运行时存在但当前 `NOT_CONFIGURED`；没有真实模型端点。
- Agent 仅语言层，不执行其声明的 GIS 工具；GDAL/QGIS/Rasterio 适配器未接。
- 分类精度/几何精度、完整追溯环、统一身份源、发布环境未完成。
- 0.1 十五项未全过；软件路径 1/2/4/7/8/11/12/13/15 可跑，3/5/6/9/10/14 仍部分。

## 代码位置

- `geoops/workflow/definitions.py`：定义校验与持久化。
- `geoops/workflow/service.py`：定义 → 节点 → 执行 / 恢复 → journal。
- `geoops/workflow/data_nodes.py`：数据集与审核节点。
- `geoops/workflow/gis_nodes.py`：内置 ASCII 栅格工具。
- `geoops/ai/agent_node.py`：Agent 语言层节点。
- `geoops/api/app.py`：API 路由与权限。
- `docs/WORKFLOW_ENGINE.md`：使用说明和边界。

本地提交：`78727fc`（工作流定义/节点/执行/恢复）、`f72b906` 与 `314cbee`（验证记录）、`6889ad4`（默认服务接线）。远程未 push。
