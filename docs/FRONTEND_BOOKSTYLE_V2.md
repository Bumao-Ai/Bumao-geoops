# 前端书香体系 v2.0 落地记录（2026-11-17）

## 1. 设计令牌

按 `<workspace>\HX\personal\90_lishi\xtgl_frontend_261102_dongjie_261104\20_view\design_tokens.md` 的 v2.0 硬色板重写 `geoops/web/ui.css`，不再沿用旧的低饱和色值。

| 角色 | 亮色值 | 用途 |
|---|---|---|
| 宣纸底 | `#F3EEE3` | 页面底 |
| 宣纸深 | `#EDE6D6` | 页面下部、层叠底 |
| 纸面卡 | `#F7F2E7` | 卡片面 |
| 墨字 | `#2B2620` | 正文 |
| 深墨 | `#1F1B16` | 标题、主数字 |
| 青瓷 | `#6F9C8F` | 主操作、正常、PASS |
| 朱砂 | `#B5495B` | 强调、活动点、FAIL / RUNNING |
| 黛蓝 | `#3C4A5A` | 管理台中枢、左书脊 |
| 赭石 | `#A8642F` | 暖色提示、WARNING |
| 留白金 | `#C9A86A` | 描边、分隔、高光 |

暖暗底：`#211D18` / `#1A1713`；暗文字 `#E9E2D3`。不写纯白 `#FFF`，不写纯黑 `#000`，不做彩虹渐变。渐变只保留：

- 顶栏：宣纸 → 略深宣纸的纵向柔渐变；
- 主按钮：青瓷 → 黛蓝微渐变；
- 左书脊：黛蓝纵向双阶；
- 卡片：留白金低透明高光。

## 2. 版面骨架

- 左侧 `252px` 书脊：黛蓝底、留白金细边、朱砂活动点、宣纸字；品牌为四格测绘标记 +「序」印。
- 顶部粘性栏：当前模块题名 + CORE / 版本 / 内核 / 连接状态 + 令牌与字号。
- 页首题签：kicker、DengXian w600 大标题、朱砂重音线、右侧模块印章。
- 内容区：KPI 四区（青瓷 / 朱砂 / 黛蓝 / 赭石）、纸卡、金线表格、五态胶囊。
- 明度阶梯：`#F8F3E8 → #F3EEE3 → #EDE6D6 → #2B2620 → #1F1B16`，相邻不跳纯白纯黑。

## 3. 十二段导航

01 总览 / 02 项目 / 03 任务 / 04 AI 资源 / 05 数据 / 06 流程 / 07 规则 / 08 质量 / 09 成果 / 10 审核 / 11 追溯（含审计） / 12 设置。

对应 `docs/PRODUCT_SPEC_0.1.md` 的 12 个功能模块与用户交互层；「操作记录与审计」并入追溯页，避免与 12 模块重复计数。

## 4. 新增功能面

- 项目页：六字段登记、项目册、编号唯一校验。
- AI 资源页：模型 / 工具 / Agent 分栏，builtin 真实可用性、external 路径检查、Agent 依赖校验、资源登记表单。
- 质量页：三层质检发起、人工抽样依据、逐层证据、报告落盘路径、报告列表。
- 成果页：成果登记（sha256 / 大小）、文件簿、accepted 后才可归档。
- 设置页：服务端权限矩阵、角色键、调用方令牌授权、存储配置状态。
- AI 资源页：真实模型运行时卡片，显示 `READY / NOT_CONFIGURED`、模型、端点、认证、超时；可发真实探针与提示词，回复、耗时与 token 用量实时回显。接入步骤见 `docs/MODEL_RUNTIME.md`。

## 5. 截图

截图由 Chrome headless 在 `http://127.0.0.1:8792/ui/` 实拍，文件在 `docs/ui-preview/`：

- `v2-overview.png`
- `v2-projects.png`
- `v2-tasks.png`
- `v2-resources.png`
- `v2-data.png`
- `v2-runs.png`
- `v2-rules.png`
- `v2-quality.png`
- `v2-artifacts.png`
- `v2-reviews.png`
- `v2-trace.png`
- `v2-settings.png`
- `v2-model-runtime.png`（AI 资源页；`NOT_CONFIGURED` 的真实状态，没有假回复）

## 6. 验证

- 单元测试：`213 tests OK`（新增 `test_model_runtime.py` 7 条，含真实本地 HTTP 提供方契约测试）。
- 冒烟：`python -m geoops.smoke` 断言导航为十二段。
- 质检真实记录：`QR-f84ef6838a`，对象 `DLV-ac0105fd55`，报告文件
  `<repo>\var\quality\QR-f84ef6838a.json`，状态 `PARTIAL`（空间宽高/范围未登记，专业抽样已记录）。
- 说明：演示数据为 3×2 ASCII 样例，只用于验证控制台质检链路，不作为真实遥感影像验收。
