# 接入真实模型运行时

GeoOps 现在有一个真实的 OpenAI-compatible 模型运行时，不是页面上的假回复。

- 端点：任意兼容 `POST /chat/completions` 的服务。
- 配置：服务进程的环境变量，或本机 `var/model-runtime.env`（环境变量优先）。
- 密钥：不下发浏览器、不写进仓库、不在日志中打印。
- 未配置：`NOT_CONFIGURED`，直接失败；不会生成占位文本。
- 调用记录：通过 API 调用会写入 audit trail。

## 1. 你需要准备的三个值

| 变量 | 含义 | 例子 |
|---|---|---|
| `GEOOPS_MODEL_BASE_URL` | 兼容 OpenAI 的 API 根地址 | `http://127.0.0.1:11434/v1` |
| `GEOOPS_MODEL_API_KEY` | 服务密钥；本地 Ollama 可留空 | `sk-...` |
| `GEOOPS_MODEL_NAME` | 端点接受的模型 id | `qwen2.5:7b` |

可选：`GEOOPS_MODEL_TIMEOUT`，默认 60 秒，范围 1–300 秒。

## 2. 在 Windows 上启动

在当前 PowerShell 进程中设置变量，再从同一进程启动服务（推荐，密钥不落盘）：

```powershell
cd <repo>
$env:GEOOPS_MODEL_BASE_URL = "http://127.0.0.1:11434/v1"
$env:GEOOPS_MODEL_API_KEY  = "ollama"
$env:GEOOPS_MODEL_NAME     = "qwen2.5:7b"
python -m geoops.api --demo --tokens var\console-tokens.json --port 8790
```

启动时控制台会打印：

```text
model runtime: READY (qwen2.5:7b @ http://127.0.0.1:11434/v1)
```

如果仍是 `NOT_CONFIGURED`，检查变量是否设在启动服务的那一个进程里；`setx` 只影响新开的进程。

### 2.1 用本机配置文件（适合桌面快捷方式）

在 `var\model-runtime.env` 写四行 `KEY=VALUE`，然后直接启动服务；服务会读取它：

```text
GEOOPS_MODEL_BASE_URL=http://127.0.0.1:11434/v1
GEOOPS_MODEL_NAME=qwen2.5:7b
GEOOPS_MODEL_API_KEY=ollama
GEOOPS_MODEL_TIMEOUT=60
```

规则：

- 只需要 `BASE_URL` 和 `NAME`；`API_KEY` 本地服务可留空，`TIMEOUT` 可省略。
- 只接受上表四个键，未知键或没有 `=` 的行会让状态变成 `CONFIG_ERROR`，不会被猜成别的配置。
- 同名的真实环境变量优先于文件，便于临时覆盖。
- 该文件在 `var\` 下，已被 `.gitignore` 忽略；不要把密钥提交到 Git。
- 状态接口返回 `config_file`，表示当前读到的文件路径；密钥值永远不会返回。

## 3. 四种常见的兼容端点

### 本地 Ollama

```powershell
$env:GEOOPS_MODEL_BASE_URL = "http://127.0.0.1:11434/v1"
$env:GEOOPS_MODEL_API_KEY  = "ollama"
$env:GEOOPS_MODEL_NAME     = "qwen2.5:7b"
```

Ollama 的 OpenAI 兼容层不校验密钥；上面的值只是占位鉴权，服务端不会把它显示出来。模型名称以 `ollama list` 为准。

### 本地 LM Studio

```powershell
$env:GEOOPS_MODEL_BASE_URL = "http://127.0.0.1:1234/v1"
$env:GEOOPS_MODEL_API_KEY  = "lm-studio"
$env:GEOOPS_MODEL_NAME     = "本地模型名称"
```

### 本地 vLLM

```powershell
$env:GEOOPS_MODEL_BASE_URL = "http://127.0.0.1:8000/v1"
$env:GEOOPS_MODEL_API_KEY  = "EMPTY"
$env:GEOOPS_MODEL_NAME     = "你的模型 id"
```

### 云端 OpenAI-compatible

```powershell
$env:GEOOPS_MODEL_BASE_URL = "https://api.openai.com/v1"
$env:GEOOPS_MODEL_API_KEY  = "sk-..."
$env:GEOOPS_MODEL_NAME     = "gpt-4o-mini"
```

任何提供 `POST /chat/completions`、返回 `choices[0].message.content` 的服务都可以；不要填只有 `generate` 接口、并不兼容 OpenAI 的地址。

## 4. 三种验证方式

### 4.1 不启动服务，直接命令行探测

```powershell
python -m geoops.ai status
python -m geoops.ai probe
python -m geoops.ai chat "用一句中文说明你能为测绘成果做什么"
```

`status` 只读环境变量并打印配置状态，不打印密钥；`probe` 和 `chat` 是真实 HTTP 请求。`chat` 的 `temperature` 取 0–2 的有限数，`max_tokens` 取 1–8192 的整数，超时 1–300 秒；非法值在发请求前以 `INVALID_OPTION` 拒绝。

### 4.2 HTTP API

```powershell
$h = @{ "X-GeoOps-Token" = "<本机令牌，见 var\console-token.txt>" }
Invoke-RestMethod -Uri "http://127.0.0.1:8790/api/v1/model-runtime" | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8790/api/v1/model-runtime/probe" -Headers $h
```

需要 `model:invoke` 权限；本机 `var\console-tokens.json` 的 `local-console` 授权包含该权限。

### 4.3 控制台

打开 `http://127.0.0.1:8790/ui/#resources`：

1. 右上角填入本机令牌（明文在 `var\console-token.txt`）。
2. “模型运行时”卡片显示 `READY`、模型、端点、认证方式。
3. 点“测试连接”发一次真实探针；点“运行模型”把输入框的提示词发过去。
4. 返回值、模型名、耗时和 token 用量显示在下方；失败会显示稳定错误码。

## 5. 错误码

| 错误码 | 含义 | 处理 |
|---|---|---|
| `NOT_CONFIGURED` | 缺少 `GEOOPS_MODEL_BASE_URL` 或 `GEOOPS_MODEL_NAME`，或地址不是 http(s) | 补变量并重启服务 |
| `CONFIG_ERROR` | `var/model-runtime.env` 有未知键或不是 `KEY=VALUE` | 按 2.1 节修正文件，或删除该文件 |
| `PROVIDER_HTTP_ERROR` | 上游返回非 2xx | 看 HTTP 状态和上游 message；401 多为密钥 |
| `PROVIDER_UNREACHABLE` | DNS、端口、TLS、超时 | 先确认 curl 能到端点；本地服务是否启动 |
| `PROVIDER_BAD_RESPONSE` | 不是 JSON、没有 choices、content 为空 | 端点不是 OpenAI 兼容格式，或模型拒答 |
| `EMPTY_PROMPT` | 提示词为空 | 填写 prompt |

## 6. 边界：这还不是“模型直接判读遥感影像”

当前运行时是文本/JSON 对话模型，适合：

- 生成作业说明、检查清单、报告草稿；
- 解释规则判定与质量报告；
- 后续 Agent 决策链的语言层。

它不会自动读取 GeoTIFF 像元。要让模型直接判读影像，还需要另外实现：

1. 栅格切片 / 重采样为 PNG 或瓦片；
2. 视觉模型适配（OpenAI `image_url` 或厂商视觉接口）；
3. 模型输出与测绘坐标、图斑、精度指标的对齐。

这部分尚未实现；不要把文本模型回复当成影像分类结果。

## 7. 安全约束

- `GEOOPS_MODEL_API_KEY` 只在服务端环境里；前端只知道“有没有配置”，不知道值。
- 不要把密钥写进 `var\console-tokens.json`、前端 localStorage、URL 或 Git。
- `var/` 与 `*.bak*` 已在 `.gitignore` 中忽略；本地令牌文件不会提交。
- 模型调用需要 `model:invoke`；审计记录保存调用方指纹、路径、结果，不保存密钥。
