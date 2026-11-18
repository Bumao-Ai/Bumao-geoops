# GeoOps 流程定义与执行（0.1）

流程定义是登记的数据，不是写死的闭包。执行时按定义逐条建节点，节点顺序、类型、参数与记录一致；未知定义、未知任务、任务未 `RUNNING`、上下文缺失都会明确失败，不生成假 `PASS`。

## 定义

`POST /api/v1/workflows` 需要 `workflow:write`。

```json
{
  "workflow_id": "WF-CHANGE-001",
  "name": "变化检测标准流程",
  "task_type": "change_detection",
  "description": "规则门 → 差分 → 登记",
  "nodes": [
    {"node_id": "R1", "name": "规则门", "type": "rule_check", "task_type": "change_detection"},
    {"node_id": "C1", "name": "逐格差分", "type": "change_detection", "threshold": 1.0, "min_area_m2": 150},
    {"node_id": "A1", "name": "登记掩膜", "type": "artifact_register", "path_key": "deliverable_path", "kind": "change_mask"}
  ]
}
```

定义会校验：节点 1–50 个，`node_id` / `name` 唯一，类型在白名单内，类型专属字段合法，未知类型整份拒绝。节点可选声明 `inputs`（上下文别名映射）、`outputs`、`executor`、`preconditions`、`success_condition`、`failure_action`、`retry`，其中 `inputs` 会在执行前由执行器真实映射。定义登记为 `ObjectType.Workflow`，并原子写入 `var/workflows.json`（`fsync` 后 `os.replace`）。

## 节点类型

| 类型 | 真实动作 | 缺依赖时 |
|---|---|---|
| `data_input` | 从 `DatasetRegistry` 读取已登记数据集，检查项目归属 | 拒绝，不伪造数据集 |
| `data_check` | 对已登记数据集做 sha256 / CRS 复核 | 缺记录为 `FAIL`，探针异常为 `ERROR` |
| `rule_check` | 调用 `SurveyRuleEngine`，记录每条规则结果 | 无适用规则记 `SKIP`，不冒充 `PASS` |
| `change_detection` | 读取两期 ASCII 栅格，逐格差分、连通斑块、最小面积，写掩膜 | 路径缺失 `FAIL`，写出失败 `ERROR` |
| `artifact_register` / `output` | 真文件 sha256 后登记成果 | 成果库未配置则拒绝 |
| `model_call` / `model_chat` | OpenAI-compatible 模型真实调用 | 未配置端点 `ERROR` |
| `agent_execute` | 先解析目录中的 Agent，校验依赖可用，再调用模型语言层 | Agent 不存在 `FAIL`，不可用 `ERROR`，不冒充工具执行 |
| `review` | 查真实审核记录；只有 `APPROVE` 或最终验收成果才通过 | 缺失审核 `FAIL`，绝不自动批准 |
| `gis_tool_call` | 内置 `builtin:ascii_grid_profile`：真实读 ASCII 栅格、校验像元、算有效格数/最值/均值；其他 `tool_id` 明确 `ERROR` | GDAL/QGIS 适配器未接入，不冒充调用 |

节点输出写入 `context["node_outputs"][node_id]`，下游节点可读取。`resume` 会把已通过节点的输出带过来，从失败节点重跑。

## 执行与恢复

`POST /api/v1/workflows/<id>/execute`，权限 `workflow:execute`：

```json
{
  "task_id": "TSK-...",
  "context": {
    "baseline_path": "var/demo/baseline.asc",
    "comparison_path": "var/demo/comparison.asc",
    "change_output_path": "var/demo/change_mask.asc",
    "deliverable_path": "var/demo/change_mask.asc",
    "crs_baseline": "EPSG:4547",
    "crs_comparison": "EPSG:4547",
    "min_area_m2": 150
  }
}
```

- `task_id` 可选；填写时任务必须是 `RUNNING`，运行结束会 `attach_run` 并写 journal。
- `outputs`、`executor`、`preconditions`、`success_condition`、`failure_action`、`retry` 当前作为定义记录保留并校验字段形状；执行器只落实 `inputs` 别名映射和节点真实动作，尚未把 `success_condition` / `retry` 变成自动判定。不要把它们当成已执行的策略。
- 运行成功或失败都会记录 `RunJournal`；失败不会自动重跑。
- `POST /api/v1/workflow-runs/<run_id>/resume` 用同一份定义、新 `run_id` 从失败节点恢复；节点数量或身份变化会拒绝，避免用旧记录跑新图。

## 当前边界

- 变化检测只支持 ASCII 栅格；GeoTIFF 像元、GDAL/QGIS/Rasterio 适配器尚未接入。
- `gis_tool_call` 只有内置 `builtin:ascii_grid_profile` 是真实可用链路；其他工具 id 是明确的 `ERROR`，不是通过。
- `agent_execute` 是 Agent 的语言层调用；Agent 声明的 GIS 工具不会被这个适配器执行。
- 模型端点未配置时 `NOT_CONFIGURED`；配置方式见 `docs/MODEL_RUNTIME.md`。
- 本文件描述的是软件路径；0.1 十五项验收中依赖用户真实影像、真实模型端点、GIS 工具、人工审核的项仍按实际状态陈述。
