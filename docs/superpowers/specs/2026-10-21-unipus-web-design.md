# Unipus Helper · Python + Web UI 设计

日期：2026-10-21
状态：待评审

## 1. 意图与背景

Unipus Helper 是一个 U校园（新视野大学英语）自动学习工具，职责是：

1. 用 U校园账号登录（SSO）。
2. 拉取课程列表、教程结构、必修任务列表、学习进度。
3. 逐单元、逐任务地获取答案（后端加密下发）、构造提交请求并提交。
4. 在本地提供任务管理、日志、网络请求调试、问题报告导出。

本项目采用 **Python + FastAPI + 浏览器 Web UI** 实现全部业务逻辑：同步客户端承载阻塞式登录/答题流程，FastAPI 提供 HTTP 与 WebSocket 接口，前端是无构建步骤的原生页面。

## 2. 目标 / 非目标

### 目标

- 功能完整：登录、多任务并行、课程/教程选择、自动答题、暂停/恢复/停止、日志面板、网络请求面板、报告导出、深/浅色主题。
- 服务只监听 `127.0.0.1:8765`，不对外网开放。
- 账号密码可勾选"记住我"，本地加密保存（Windows 使用 DPAPI）。
- 覆盖第 6 节列出的健壮性与边界场景，并支持多小题任务提交。
- 纯 `pip install -r requirements.txt` 可运行，无需 Node 工具链。
- 有单元测试覆盖纯逻辑（解析、加密、提交体、状态机）。

### 非目标

- 不做多用户、远程访问、账号池。
- 不做验证码识别；遇到验证码直接报错提示手动处理。
- 不臆造未知题型的提交协议。`discussion` / `multiFileUpload` / `exit-ticket` / `multichoice` 仍跳过，但跳过原因会结构化上报。
- 不修改 U校园服务端，不引入代理/抓包。
- 不保存明文密码到磁盘或日志。

### 反目标（即使"能跑"也算失败）

- 密码出现在日志、报告或前端 `localStorage` 里。
- 任何一个任务线程异常导致整个服务崩溃。
- 停止/重启任务后出现两个线程同时提交。
- Web UI 在登录或答题时卡住主线程（所有网络操作必须离开请求处理线程）。

## 3. 已确认的技术决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 后端 | FastAPI + Uvicorn | 异步 WebSocket 推送天然适合任务状态流 |
| 前端 | 原生 HTML/CSS/JS，无构建步骤 | 双击即用；避免 Node 工具链 |
| 监听 | `127.0.0.1:8765` | 无鉴权需求，最小攻击面 |
| HTTP 客户端 | `httpx.Client`（同步） | 业务逻辑是阻塞式流程，放线程里最直接；避免把 460 行流程改写成 async |
| 任务并发 | 每任务一个 `threading.Thread` | 任务间互不阻塞，实现简单 |
| 状态推送 | 线程安全 EventBus + WebSocket | 前端实时更新，无需轮询 |
| 加密（答案解密） | `cryptography` AES-ECB | 与 U校园 下发的密文格式一致 |
| JWT（x-annotator-auth-token） | 标准库 `hmac`+`hashlib`+`base64` 手写 HS256 | 零额外依赖，逻辑只有 15 行 |
| HTML→纯文本 | `beautifulsoup4` | 容错处理不规范 HTML |
| 凭据加密 | Windows DPAPI（ctypes 调 `CryptProtectData`），非 Windows 回退到 0600 权限的随机密钥文件 | 机器+用户绑定，比"硬编码密钥"真实 |
| 测试 | pytest | 纯逻辑单测，不联网 |

## 4. 目录结构

```
git/
├── README.md                     # 使用说明、免责声明、常见问题
├── requirements.txt
├── run.bat                       # Windows：建 venv → 装依赖 → 启动 → 开浏览器
├── run.sh                        # Linux/macOS 同上
├── pyproject.toml                # 项目元数据 + pytest 配置
├── unipus_web/
│   ├── __init__.py
│   ├── __main__.py               # CLI（--host/--port/--no-browser）
│   ├── app.py                    # FastAPI 实例、路由、WebSocket、静态文件
│   ├── config.py                 # 域名、路径、常量
│   ├── events.py                 # EventBus（线程 → asyncio 桥）
│   ├── logging_setup.py          # 环形日志 Handler + 结构化日志事件
│   ├── network_log.py            # 网络请求录制（环形缓冲）
│   ├── crypto.py                 # JWT、答案 AES 解密、HTML→文本、非法字符清洗
│   ├── credentials.py            # DPAPI 加密凭据存取
│   ├── models.py                 # 响应数据模型（dataclass）
│   ├── api/
│   │   ├── __init__.py
│   │   ├── client.py             # UnipusClient：全部 HTTP 端点 + cookie
│   │   └── errors.py             # 异常层级
│   ├── core/
│   │   ├── __init__.py
│   │   ├── course_detail.py      # 课程 JSON 树、题型枚举、时间表
│   │   ├── unit_situation.py     # 单元进度树
│   │   ├── answer.py             # 答案 JSON 解析
│   │   ├── submit.py             # 提交体构造（单题 / 多题）
│   │   ├── task.py               # Task 状态机 + 暂停/恢复/停止
│   │   ├── learn.py              # 学习主流程
│   │   ├── manager.py            # TaskManager 单例
│   │   └── reporter.py           # 报告 zip 生成与脱敏
│   └── web/
│       ├── index.html
│       ├── app.js
│       └── style.css
└── tests/
    ├── test_crypto.py
    ├── test_course_detail.py
    ├── test_unit_situation.py
    ├── test_submit.py
    └── test_task_state.py
```

## 5. 核心设计

### 5.1 任务状态机

状态流转如下：
`INITIALIZING → READY → RUNNING ⇄ PAUSED / WAITING / NEED_OPERATION → COMPLETED | ERROR`

关键实现：

- `Task` 持有 `threading.Condition`，用于暂停/恢复/冷却等待的唤醒。
- `stop_event: threading.Event` 表示协作式停止。
- **generation token**：每次 `start()` 递增 `run_generation`；线程内所有状态写入都校验 `generation == self.run_generation`，否则直接抛出 `TaskStopped` 退出。这保证停止后立刻重启时，旧线程的写入不会落到新任务上。
- `checkpoint()` 在每次网络请求前后调用：
  - 若 `stop_event` 已置位 → 抛 `TaskStopped`；
  - 若状态为 `PAUSED` → 阻塞等待恢复。
- `wait_for_cooldown(ms)`：基于 `time.monotonic()` 截止时间，`Condition.wait(timeout)` 循环；响应暂停、恢复、停止。
- 停止后状态回到 `READY`，可再次启动；线程退出时清理 `run_generation`。

### 5.2 登录与创建任务

`POST /api/tasks` **立即返回**（任务状态 `INITIALIZING`），登录在后台线程完成：

1. 创建 `UnipusClient`（独立 httpx.Client + cookie jar）。
2. `POST sso.unipus.cn/sso/0.1/sso/login`。
3. 解析 `rs.jwt` / `rs.openid`；失败抛 `LoginError`，携带后端 `msg`。
4. `GET /api/account/user/info` 获取姓名、学校、appUserId、ssoId。
5. 状态置 `READY`，广播 `task.updated`。

登录失败时任务保留为 `ERROR` 并附错误描述，前端弹 toast，用户可移除后重试。这样 HTTP 请求不会被网络阻塞。

### 5.3 学习流程

学习流程按以下顺序执行：

1. 教程详情 `getCourseResourceInfoById` → courseInstanceId / resourceId / strategyId。
2. 全量任务树 `getAllTasksofCourse` → `CourseDetail`。
3. 必修任务 `getRequiredPartofCourse` → `{unitId: [taskId]}`。
4. 总进度 `getTotalAndUnitSituation`；若 100% → `COMPLETED`。
5. 单元循环：
   - 任务时间表 `getTaskTimeInfo`。
   - 单元进度 `getUnitTaskSituation`。
   - 必修任务中进度 < 100 的，逐个 `learn_task`。
6. 每个任务：
   - 校验时间窗、题型、多题支持性；
   - 取答案 → 解密 → 按题型抽取；
   - 构造提交体 → 提交（每分钟最多 5 次）；
   - 处理 600001/600002 限流码（等 2 分钟重试）；
   - 提交后查 `getTaskInfo`，若客观题得分为 0 → 自动暂停并广播警告；
   - 刷新课程进度。

### 5.4 答案与提交体

- 解密：`unipus.` + hex → AES-ECB/NoPadding，key = `b"1a2b3c4d" + k`；去尾部 `\0`；UTF-8。密钥长度不足 16 的整数倍时右补 `\0` 到合法长度。
- 单题与多题提交体由 `create_submit_body` 统一构造，字段结构以接口契约为准（JSON 无顺序语义，但测试会锁定结构）。
- **多小题答案隔离**：每题独立的答案列表；长度不一致时明确报错，而不是静默复用。

### 5.5 事件与 WebSocket

- `EventBus` 在启动时捕获 asyncio loop；工作线程调用 `publish(event)` 时用 `loop.call_soon_threadsafe` 投递到订阅队列。
- 事件类型：`snapshot`（连接时全量）、`task.added`、`task.updated`、`task.removed`、`task.warning`、`task.error`、`log.append`、`network.append`。
- `/ws` 断开自动重连（前端指数退避 1→10s），重连后先收 `snapshot`。

### 5.6 Web UI

单页布局：

```
┌──────────────────────────────────────────────┐
│ Unipus Helper   [运行中 2]   ☾  [日志] [网络] [报告] │
├──────────────────────────────────────────────┤
│ ┌ 任务卡片 ─────────────────────────────────┐ │
│ │ 新视野大学英语 读写教程2        RUNNING ●  │ │
│ │ 张三 — 正在学习 Unit 3 ...                │ │
│ │ ████████████░░░░░░  12/20  60%            │ │
│ │              [暂停] [停止] [管理]          │ │
│ └───────────────────────────────────────────┘ │
│                    [+ 添加任务]                │
└──────────────────────────────────────────────┘
```

- 添加任务弹窗：账号、密码、记住我；登录中禁用并显示 spinner；失败显示后端返回的具体信息。
- `NEED_OPERATION` 状态的任务卡片显示"需要操作"链接，点开课程选择弹窗。
- 管理弹窗：任务 ID、名称、用户、状态、进度、描述 + 操作按钮。
- 日志抽屉：级别过滤、自动滚动、清空、复制。
- 网络抽屉：方法/URL/状态码/耗时列表，点开看请求头、请求体、响应体。
- 报告弹窗：POST `/api/report` 触发下载。
- 主题：CSS 变量 + `localStorage` 记忆；默认跟随系统 `prefers-color-scheme`。
- 无障碍：按钮有 aria-label，状态不只靠颜色表达。

### 5.7 安全

- 只绑定回环地址。
- 校验 `Host` 头必须是 `127.0.0.1[:port]` / `localhost[:port]`，防止 DNS rebinding 从浏览器访问本地服务。
- 静态资源只从包内目录读取，路径穿越防护。
- 日志与网络记录在 API 输出前做脱敏：用户名、手机号、姓名、JWT、Cookie。
- 网络面板默认隐藏 `Authorization` / `Cookie` / 请求体中的 password。
- 报告 zip 额外剔除登录与用户信息请求。

## 6. 健壮性与边界约定

以下场景必须在实现与测试中明确覆盖：

| # | 场景 | 约定行为 |
|---|---|---|
| 1 | 单元进度缺少任务节点 | 判空跳过该节点，记录 warning，不中断任务 |
| 2 | 同一任务包含多个小题 | 每题独立答案列表，互不复用或累积 |
| 3 | 课程资源列表为空 | 任务进入 ERROR，并给出可读描述 |
| 4 | 答案条数少于 `question_num` | 跳过该任务，广播结构化警告 |
| 5 | 题型索引越界或题型未知 | 越界回落到最后一个已知题型；未知题型抛可捕获异常 |
| 6 | 报告导出 | 统一使用 `.zip` 扩展名，与实际内容一致 |
| 7 | 用户名含 `-` 等特殊字符 | 由任务显式记录脱敏源，不按分隔符推断 |
| 8 | 网络请求与界面线程 | 所有网络操作在后台线程执行，不阻塞请求处理 |
| 9 | 停止后立即重启 | generation token 保证只有当前线程能写入任务状态 |
| 10 | 提交响应 `data` 缺失 | 按失败处理，不抛未捕获异常 |
| 11 | 课程字段缺失 | 统一安全取值，不使用“先赋值再覆盖”的写法 |
| 12 | 答案字符清洗 | 显式字符白名单 + 单测，避免不可控的巨型正则 |
| 13 | 解密密钥长度非法 | 补齐/截断到合法长度，并给出明确错误 |
| 14 | 登录失败 | 区分网络错误与账号密码错误，返回可读信息 |
| 15 | 重复创建任务 | API 返回 409 / 明确错误码，不静默失败 |
| 16 | 答案 JSON 为空、非数组或单项非法 | 返回可解析的部分或领域异常，不崩溃 |
| 17 | 所有单元都被跳过 | 统计实际提交数；0 提交时标记 `COMPLETED_WITH_SKIPS` 描述 |
| 18 | Cookie 持久化 | 单线程节流器；默认不落盘 |
| 19 | 空串 `nodeId` | 不建索引，由调用方统一处理 |
| 20 | 冷却等待期间停止 | `Condition.wait(timeout)` + 轮询 stop，可立即退出 |
| 21 | 任务时间表字段层级 | 优先读 `strategies` 下的时间，回退到叶子节点；时间窗校验必须实际生效 |

## 7. HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 单页应用 |
| WS | `/ws` | 事件流 |
| GET | `/api/tasks` | 任务快照列表 |
| POST | `/api/tasks` | `{username,password,remember}` → 202 + 任务快照 |
| POST | `/api/tasks/{id}/start` | 启动 |
| POST | `/api/tasks/{id}/pause` | 暂停 |
| POST | `/api/tasks/{id}/resume` | 恢复 |
| POST | `/api/tasks/{id}/stop` | 停止 |
| DELETE | `/api/tasks/{id}` | 移除 |
| GET | `/api/tasks/{id}/courses` | 可选课程/教程树 |
| POST | `/api/tasks/{id}/choose` | `{courseId,resourceId}` |
| GET | `/api/logs?after={seq}` | 增量日志 |
| GET | `/api/network?after={seq}` | 增量请求记录 |
| POST | `/api/report` | 生成并下载 zip |
| POST | `/api/shutdown` | 可选：安全退出 |

所有错误响应统一：`{"error": {"code": "...", "message": "..."}}`。

## 8. 依赖

```
fastapi>=0.115
uvicorn[standard]>=0.30
httpx>=0.27
beautifulsoup4>=4.12
cryptography>=42
pytest>=8          # dev
```

## 9. 测试策略

- `test_crypto.py`：JWT 头/claims/签名可验证；AES 解密用固定向量；非法 key 长度报明确错误；HTML→文本；非法字符清洗。
- `test_course_detail.py`：用内联 JSON 构造课程树，验证 role/base 解析、题型查询、越界/未知类型、时间表。
- `test_unit_situation.py`：节点索引、缺失 nodeId、递归 children。
- `test_submit.py`：单题/多题提交体结构、预设模式（空 quesDatas）、题型映射、多题答案隔离。
- `test_task_state.py`：用假 learn 流程验证 READY→RUNNING→PAUSED→RESUME→STOP；停止后重启 generation 生效；冷却等待可被停止打断。
- 不写联网集成测试；手工冒烟步骤写进 README。

## 10. 交付判定

- `pytest` 全绿。
- `python -m unipus_web` 启动后浏览器可打开、无控制台报错。
- 无账号情况下能走到"登录中→ERROR 提示账号密码错误"而不是 500。
- 代码内无明文账号密码；`grep` 日志目录无密码。
- README 写明免责声明、启动方式、已知限制。

## 11. 评审补充决策（2026-10-21）

独立评审提出 4 个会逼实现者瞎猜的问题，逐条钉死：

### 11.1 多小题提交：实验性特性，默认开启但可关闭

- 多小题提交体的字段结构来自抓包样例，尚未在真实账号上验证；实现按字段契约构造，不额外发明字段。
- 在任务日志中打印 `[experimental] multi-question submit` 警告。
- 增加配置项 `allow_multi_question`（默认 `True`），可通过 CLI `--no-multi-question` 关闭；关闭时跳过多小题任务。
- `test_submit.py` 锁定的是提交体结构契约，测试注释明确标注 **unvalidated against live server**，不把结构当作服务端事实。
- 本次交付没有可用账号，无法做实网验证；这一点写进 README 的“已知限制”。

### 11.2 联网验证手段

- 本机没有可用账号，无法做登录/提交集成测试。
- 实现层固定：httpx `follow_redirects=True`；单个 `httpx.Client` 跨主机共享 cookie jar；`trust_env` 默认关闭（避免系统代理污染），可通过 `--proxy` 显式配置。
- 交付一个**只读**冒烟脚本 `scripts/smoke_login.py`：从环境变量读账号，登录 + 拉课程列表，打印结果，不做任何提交。用户可自行验证。
- 报告/日志中保留完整的请求-响应记录（已脱敏），出问题时可直接定位。

### 11.3 答案字符白名单

- 不重新发明白名单。把 U校园 允许的字符类**逐区间实现**为 Python 正则，保持集合语义一致；重点是"可编译、区间不重叠、有单测"，而不是改变允许集。
- 单题与多题提交体统一走同一套 `toPlainText` + `sanitize_answer`，避免两条路径行为分叉。
- 单测覆盖：中文、英文、数字、常见中英文标点、Emoji/控制字符被替换为空格、换行/制表保留。

### 11.4 "记住我"语义

- 用户已确认要本地加密保存密码。落地为**服务端快捷登录**：
  - 凭据列表接口只返回 `id / username / 显示名`，**永远不返回密码**。
  - 前端"已保存账号"选择后，可直接调用 `POST /api/tasks {credential_id}`，由服务端解密并登录；密码不进入浏览器、不进入 localStorage。
  - 支持删除已保存凭据（`DELETE /api/credentials/{id}`）。
  - 不实现"启动时自动恢复并重启任务"——需要用户显式点击。

### 11.5 其他钉死项

- `x-annotator-auth-token`：HS256；claims `open_id`、`name=""`、`email=""`、`administrator=false`、`exp` 为**毫秒**时间戳、`iss=c4f772063dcfa98e9c50`、`aud=edx.unipus.cn`；header `{"alg":"HS256","typ":"JWT"}`；secret 见 `crypto.py`。
- 提交限流 5 次/分钟是**每任务**（每个 Learn 实例）计数，不是全局。
- 后端 `data` 字段可能是字符串编码的 JSON，解析统一走 `lenient_obj()`：字符串则二次 `json.loads`，失败则视为空。

### 11.6 任务时间表字段层级

任务时间表的实际响应把 `start_time` / `end_time` 放在 `leafs[nodeId].strategies` 下。实现要求：`CourseDetail.init_task_times` 优先读 `leaf.strategies.start_time/end_time`，回退到 `leaf.start_time/end_time`，并确保时间窗校验实际生效。

## 12. 留给实现者的判断

- 前端是否使用 Web Component：不使用，保持单文件 JS。
- 日志持久化：只保留内存环形缓冲（5000 条）+ 可选写文件，默认不写文件。
- 报告生成后是否自动移除：不留临时文件，`StreamingResponse` 内存生成。
- 端口占用：启动时检测，自动尝试 8765→8799。
