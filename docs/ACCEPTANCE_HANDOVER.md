# 0.1 真实验收交接清单

本文件只列“软件已经能接、但必须由你提供真实资产才能通过”的输入。没有提供时，系统会明确返回
`NOT_CONFIGURED`、`INCOMPLETE`、`ERROR` 或 `SKIPPED`，不会用合成结果冒充通过。

## 一、当前可核对的软件基线

- 全量测试：`python -m unittest discover -s geoops\tests -t .`，当前 **377 tests OK**。
- 结构自检：`python -m geoops.smoke`，当前 **SMOKE PASS: 73 assertions**。
- 控制台：`http://127.0.0.1:8790/ui/`；健康接口 `/api/v1/health`。
- 等级：核心工程（CORE），登记在 `docs/ENGINEERING_TIER.md`。
- 0.1 十五项并未宣称全过；真实影像、真实模型端点、真实外部 GIS 工具、真实精度样本和完整真实验收环仍缺。

## 二、模型运行接入

### 1. 准备三个值

| 变量 | 说明 |
|---|---|
| `GEOOPS_MODEL_BASE_URL` | OpenAI-compatible 根地址，通常以 `/v1` 结尾 |
| `GEOOPS_MODEL_NAME` | 该端点真实接受的模型 id |
| `GEOOPS_MODEL_API_KEY` | 密钥；本地 Ollama/LM Studio 可留空或填占位 |

可选 `GEOOPS_MODEL_TIMEOUT`，默认 60 秒，范围 1–300 秒。

### 2. 写本机配置文件（推荐）

新建 `var\model-runtime.env`：

```text
GEOOPS_MODEL_BASE_URL=http://127.0.0.1:11434/v1
GEOOPS_MODEL_NAME=qwen2.5:7b
GEOOPS_MODEL_API_KEY=ollama
GEOOPS_MODEL_TIMEOUT=60
```

只接受这四个键；未知键会变成 `CONFIG_ERROR`。该文件在 `var\` 下，已被 `.gitignore` 忽略。
真实环境变量优先于文件，便于临时覆盖。

### 3. 验证

```powershell
cd <repo>
python -m geoops.ai status
python -m geoops.ai probe
python -m geoops.ai chat "用一句中文说明你能为测绘成果做什么"
```

`status` 只显示配置状态和 `config_file`，不显示密钥；`probe` 与 `chat` 是真实 HTTP 请求。`chat` 的 `temperature` 必须是 0–2 的有限数，`max_tokens` 必须是 1–8192 的整数，超时 1–300 秒；否则返回 400 `INVALID_OPTION`，不会把 NaN 发给端点。
服务重启后，`GET /api/v1/model-runtime` 应变为 `READY`，并显示真实模型与端点。

### 4. 常见端点

- 本地 Ollama：`http://127.0.0.1:11434/v1`，模型名以 `ollama list` 为准。
- 本地 LM Studio：`http://127.0.0.1:1234/v1`。
- 本地 vLLM：`http://127.0.0.1:8000/v1`。
- 云端：`https://api.openai.com/v1` 或厂商兼容地址。

只支持 `POST /chat/completions` 返回 `choices[0].message.content` 的端点；不兼容的 `generate` 接口不会被猜成可用。

## 三、真实遥感影像

需要你提供：

1. 真实 GeoTIFF/BigTIFF（或带 `.json` sidecar 的 ASCII）绝对路径。GeoTIFF 支持未压缩/LZW/Deflate/PackBits 条带或分块；JPEG/JPEG2000 需要 Pillow。
2. 坐标系：`crs`，以及 `crs_model=geographic|projected`（优先 sidecar，否则从 GeoTIFF 头读取；EPSG:4326/3857 可推断）。注册记录保存该字段，复核时一并比较。GeoTIFF 头读不出像元尺寸/范围时，即使 sidecar 给了 CRS 也只登记为 `INCOMPLETE`，不会 READY 一个无法定位的影像。
3. 如果是多波段，说明用于变化检测的 `band` 序号。
4. 如果有两期影像，需要同一 CRS、同一像元大小、同一原点、同一尺寸；线性单位也必须一致。
5. 变化阈值：正值按 `abs(diff) >= threshold`，`threshold=0` 只标记真实非零差异；`min_area_m2` 按真实面积过滤。

登记后核对：

```powershell
$b = "http://127.0.0.1:8790"
Invoke-RestMethod "$b/api/v1/datasets"
Invoke-RestMethod "$b/api/v1/datasets/<dataset_id>/profile?band=1"
Invoke-RestMethod "$b/api/v1/datasets/<dataset_id>/validate"
```

`profile` 返回真实 `ncols/nrows/bands/cellsize/cellsize_y/cell_area_m2/footprint_area_m2/area_basis/bounds/crs/raster_type/linear_unit/valid_cells/nodata_cells/non_finite_cells/min/max/mean`；GeoTIFF 的 `read_mode=streamed_blocks`，按条带/分块逐块统计，不把整幅影像读成 Python 浮点数组；JPEG/JPEG2000 必须由 Pillow 整幅解码，此时如实返回 `read_mode=pillow_full_image`；ASCII 为 `read_mode=whole_file`。
`validate` 会重算 sha256，并比较注册时的 CRS、CRS 模型、宽、高、波段数、栅格类型与线性单位；sidecar 与 GeoTIFF 头声明不同 CRS/模型时，数据档案记为 `INCOMPLETE` 与 `metadata_conflict`，`DatasetRegistry.register` 直接拒绝注册，变化检测与 profile 也会拒绝这种自相矛盾的输入。地理坐标系面积按逐行 WGS84 椭球计算；投影坐标系按 GeoKey 3076 声明的 metre/foot/yard/US survey foot 换算；未声明 CRS 模型时面积只以 map units 返回，不冒充平方米。没有声明 NODATA 的栅格不会把 -9999 当缺失值；NaN/Inf 单独计数，不进入统计。

## 四、真实外部 GIS 工具

本机当前没有 GDAL/QGIS/Rasterio。安装后，新建 `var\external-tools.json`：

```json
{
  "tools": [
    {
      "tool_id": "external:gdalinfo",
      "command": ["<GDAL_HOME>\\gdalinfo.exe"],
      "args": ["{path}"],
      "timeout": 60
    }
  ]
}
```

规则：

- `command` 是 argv 数组，不经 shell；`command[0]` 必须是绝对可执行路径。
- `{path}` 等占位符必须由调用参数提供，缺失即拒绝；值只接受字符串/数字/布尔，拒绝 None、对象、数组、NaN/Inf 与 NUL。
- 超时必须在 1–3600 秒之间；0 或空值不会再被当成默认 60。
- 非零退出、超时、无法启动都记录为 `ERROR`，并带渲染命令、退出码、stdout/stderr、耗时。
- 重复 `tool_id` 或非有限 `timeout` 在加载时就会被拒绝。

## 五、精度样本与质量报告

需要你提供：

1. 预测掩膜（分类结果或变化掩膜）。
2. 与预测同尺寸、同像元大小、同原点、同 CRS 的真值掩膜。
3. 可接受的阈值，例如 `pixel_accuracy>=0.85`、`precision>=0.80`；不提供就只算指标，不判阈值。
4. 人工抽查说明（专业样本备注）。

质量报告会记录 `TP/FP/FN/TN`、pixel accuracy、precision、recall、F1、IoU；参考/预测 CRS 不一致、
缺 CRS、尺寸/像元/原点不一致都会拒绝，不会出伪造混淆矩阵。两张 GeoTIFF 掩膜按空间行序流式比较，不把两幅整图读成浮点数组。NODATA 与 NaN/Inf 分开计数并从矩阵排除；
没有声明 NODATA 的掩膜不会把 -9999 当缺失值。

## 六、审核、归档与追溯

需要你提供：

1. 真实审核人姓名/角色，以及本机令牌（`var\console-tokens.json` 或新发放的令牌）。
2. 归档目录；控制台默认 `var\archive`，也可用 `GEOOPS_ARCHIVE_DIR` 指向正式归档盘。
3. 最终成果文件必须与登记时 sha256 一致；审核通过后才可归档。

归档会：

- 拒绝未配置归档目录或未填写归档人身份的请求，成果状态保持 accepted，不会出现“只改状态、没有文件”的假归档；
- 重算源文件 sha256，缺失或被改即拒绝；
- 将文件复制到 `var\archive\<成果编号>\files\`；
- 写 `manifest.json`（成果编号、任务、项目、源路径、sha256、大小、归档人、时间、备注）。

反向追溯：

```powershell
Invoke-RestMethod "$b/api/v1/tasks/<task_id>/trace"
Invoke-RestMethod "$b/api/v1/deliverables/<deliverable_id>/trace"
Invoke-RestMethod "$b/api/v1/deliverables/<deliverable_id>/archive-verification"
Invoke-RestMethod "$b/api/v1/audit/verify"
```

`archive-verification` 会重新打开归档清单、逐文件重算 sha256、比对登记值与文件大小，并拒绝归档目录之外的清单路径；任何缺失或被改都会返回 `ok=false` 和具体 `problems`。清单文件或清单条目若通过符号链接指向归档目录之外，即使目标文件哈希相同也会被拒绝。
`audit/verify` 会重新读取审计 JSONL 并校验整条哈希链；文件缺失、断链或某行字段被改都会返回 `ok=false`，不会用内存副本冒充通过。

真实数据环填满后，`complete` 才能由真实记录支撑，而不是靠合成对象凑齐。

## 七、发布环境（尚未提供）

- 事务数据库或外部状态存储；当前是单文件 JSON 快照。
- 对象存储、TLS 终止、代理、备份与恢复策略。
- 统一身份源与令牌轮换责任人。
- 这些未提供前，只能按“本机核心工程”验收，不能按生产发布资格表述。

## 八、逐项验收建议顺序

1. 建真实项目 `POST /api/v1/projects`。
2. 建真实任务 `POST /api/v1/tasks`。
3. 登记真实影像 `POST /api/v1/datasets`，核对 `profile` 与 `validate`。
4. 配模型端点，`probe` 真实返回。
5. 配外部 GIS 工具，跑一次真实 `gdalinfo`。
6. 执行变化检测 workflow，得到真实掩膜与节点日志。
7. 用真值掩膜生成质量报告并声明阈值。
8. 提交人工审核，`APPROVE` 必须引用 `PASS` 报告。
9. 归档，核对归档文件 sha256 与 manifest，再跑一次 `archive-verification`。
10. 从任务和成果两个方向各跑一次 trace。
