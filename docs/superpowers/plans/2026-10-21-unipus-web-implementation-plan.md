# Unipus Helper Python + Web UI Implementation Plan

> 状态：已归档。本计划已实施完成（当前版本 v2.0.0），仅作历史记录保留；现状以 `README.md` 与 `docs/superpowers/specs/2026-10-21-unipus-web-design.md` 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Python 实现 Unipus Helper 的全部业务逻辑，提供 FastAPI + 原生前端的 Web UI。

**Architecture:** 同步 httpx 客户端承载阻塞式登录/答题流程，每个任务一个守护线程；线程通过 EventBus 把状态/日志/网络记录推送到 asyncio WebSocket。核心解析与提交逻辑是纯函数，便于单测。凭据由 DPAPI（Windows）或本地密钥文件加密，密码永不出服务端。

**Tech Stack:** Python 3.12、FastAPI、Uvicorn、httpx、beautifulsoup4、cryptography、pytest。前端为无构建的原生 HTML/CSS/JS。

**Spec:** `docs/superpowers/specs/2026-10-21-unipus-web-design.md`

## Global Constraints

- Python 版本：`>=3.12`。
- 运行时依赖仅限：`fastapi`、`uvicorn[standard]`、`httpx`、`beautifulsoup4`、`cryptography`；开发依赖：`pytest`。
- 服务只绑定 `127.0.0.1`；默认端口 8765，占用时依次尝试到 8799。
- 密码不得出现在：日志、网络记录 API 输出、报告 zip、前端 `localStorage`、任何 HTTP 响应体。
- 所有测试禁止联网；HTTP 相关测试使用 `httpx.MockTransport` 或 fake client。
- 标识符用英文，docstring 与用户可见文案用中文。
- 每个任务结束必须 `pytest` 通过并提交一次。
- 多小题提交是实验性功能：默认开启，`--no-multi-question` 可关闭；日志必须打印 `[experimental] multi-question submit`。
- 不得臆造 U校园接口；所有 URL、header、字段名以设计文档第 7 节的接口契约为准。

## Review Focus

1. **错误密码登录**：必须得到可读的“账号或密码错误”，而不是 500、堆栈或无限 INITIALIZING。
2. **任务运行中网络超时/断网**：任务进入 ERROR 并带可读描述，线程退出，随后可重新启动且不会出现双线程提交。
3. **冷却/等待用户选课时点击停止**：必须立即退出，之后不得再发出提交请求。
4. **后端数据结构缺失**（单元进度缺 node、`bases` 短于 `question_num`、`data` 为字符串）：跳过并告警，不得抛未捕获异常。
5. **服务端返回 HTML/502/非 JSON**：客户端抛 `ApiError`，Web 服务保持存活，前端显示错误 toast。

---

### Task 1: 项目骨架与测试基线

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `requirements.txt`, `unipus_web/__init__.py`, `unipus_web/config.py`, `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `unipus_web.config` 常量：`APP_NAME`、`VERSION`、`DEFAULT_PORT=8765`、`PORT_RANGE=range(8765, 8800)`、`MAIN_HOST="uai.unipus.cn"`、`SSO_HOST="sso.unipus.cn"`、`CONTENT_HOST="ucontent.unipus.cn"`、`USER_AGENT="Unipus Helper/1.0"`、`ANNOTATOR_SECRET`、`ANNOTATOR_ISSUER`、`ANNOTATOR_AUDIENCE`、`MAX_SUBMITS_PER_MINUTE=5`、`SUBMIT_RATE_COOLDOWN_MS=120_000`、`DEFAULT_TASK_END=32503651200`、`LOG_BUFFER_SIZE=5000`、`NETWORK_BUFFER_SIZE=2048`、`RESPONSE_PEEK_LIMIT=10*1024*1024`、`DATA_DIR: Path`、`CREDENTIALS_FILE: Path`。

- [ ] **Step 1: 初始化仓库与目录**

```bash
cd /c/Users/12650/Desktop/git
git init
mkdir -p unipus_web/api unipus_web/core unipus_web/web tests scripts
```

- [ ] **Step 2: 写 `requirements.txt` 与 `pyproject.toml`**

`requirements.txt` 固定五行运行时依赖 + pytest。`pyproject.toml` 的 `[tool.pytest.ini_options]` 设 `testpaths=["tests"]`、`addopts="-q"`，`[project]` 声明 `requires-python=">=3.12"` 与包发现 `include=["unipus_web*"]`，`package-data` 包含 `unipus_web/web/*`。

- [ ] **Step 3: 写失败测试 `tests/test_config.py`**

```python
def test_ports_and_buffer_defaults():
    from unipus_web import config
    assert config.DEFAULT_PORT == 8765
    assert list(config.PORT_RANGE)[0] == 8765 and list(config.PORT_RANGE)[-1] == 8799
    assert config.LOG_BUFFER_SIZE == 5000
    assert config.DATA_DIR.name == ".unipus_helper" or config.DATA_DIR.is_absolute()

def test_annotator_constants_are_stable():
    from unipus_web import config
    assert config.ANNOTATOR_SECRET == "a824b379f126b8b7aa5e33dee83fb0a05aa7462c"
    assert config.ANNOTATOR_ISSUER == "c4f772063dcfa98e9c50"
    assert config.ANNOTATOR_AUDIENCE == "edx.unipus.cn"
```

- [ ] **Step 4: 运行确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'unipus_web'`

- [ ] **Step 5: 实现 `unipus_web/config.py` 与 `__init__.py`**

`DATA_DIR` 取 `os.environ.get("UNIPUS_DATA_DIR")`，否则 `Path.home()/".unipus_helper"`；`CREDENTIALS_FILE = DATA_DIR/"credentials.dat"`。`__init__.py` 暴露 `__version__`。

- [ ] **Step 6: 建 venv、装依赖、跑测试**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest tests/test_config.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add .gitignore pyproject.toml requirements.txt unipus_web/config.py unipus_web/__init__.py tests/
git commit -m "chore: project skeleton and config"
```

---

### Task 2: 加密与文本工具

**Files:**
- Create: `unipus_web/crypto.py`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Produces:
  - `generate_auth_token(open_id: str, *, now_ms: int | None = None) -> str`
  - `decrypt_answer(data_with_prefix: str | None, k: str | None) -> str`
  - `html_to_text(html: str | None) -> str`
  - `sanitize_answer(text: str) -> str`
  - `hex_to_bytes(s: str) -> bytes`
  - `b64url_encode(data: bytes) -> str` / `b64url_decode(s: str) -> bytes`

- [ ] **Step 1: 写失败测试**

```python
import base64, hashlib, hmac, json
from unipus_web import crypto

def test_jwt_header_payload_and_signature():
    token = crypto.generate_auth_token("openid-123", now_ms=1_700_000_000_000)
    h, p, s = token.split(".")
    header = json.loads(crypto.b64url_decode(h))
    payload = json.loads(crypto.b64url_decode(p))
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert payload["open_id"] == "openid-123"
    assert payload["name"] == "" and payload["email"] == ""
    assert payload["administrator"] is False
    assert payload["exp"] == 1_700_000_000_000 + 31_536_000_000  # 毫秒
    assert payload["iss"] == "c4f772063dcfa98e9c50"
    assert payload["aud"] == "edx.unipus.cn"
    expected = hmac.new(b"a824b379f126b8b7aa5e33dee83fb0a05aa7462c",
                        f"{h}.{p}".encode(), hashlib.sha256).digest()
    assert crypto.b64url_decode(s) == expected

def test_decrypt_answer_known_vector():
    # key = b"1a2b3c4d20250627" + zero padding to 16; AES-ECB/NoPadding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    key = b"1a2b3c4d20250627"
    plain = '{"id":1}'.encode()
    padded = plain + b"\x00" * (-len(plain) % 16)
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    cipher_hex = (enc.update(padded) + enc.finalize()).hex()
    assert crypto.decrypt_answer("unipus." + cipher_hex, "20250627") == '{"id":1}'

def test_decrypt_passthrough_and_bad_key():
    assert crypto.decrypt_answer("plain", "x") == "plain"
    assert crypto.decrypt_answer(None, None) == ""

def test_sanitize_keeps_chinese_and_punctuation_replaces_emoji():
    assert crypto.sanitize_answer("你好，world! 123") == "你好，world! 123"
    assert crypto.sanitize_answer("a😀b") == "a b"

def test_html_to_text_handles_br_and_entities():
    assert crypto.html_to_text("<p>Hello&nbsp;<b>world</b></p><p>second</p>").splitlines()[0] == "Hello world"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_crypto.py -v`
Expected: FAIL `AttributeError: module ... has no attribute 'generate_auth_token'`

- [ ] **Step 3: 实现 `crypto.py`**

- JWT：header 固定 `{"alg":"HS256","typ":"JWT"}`；payload 顺序 `open_id,name,email,administrator,exp,iss,aud`；`exp = (now_ms or time.time()*1000) + 31_536_000_000`；签名 `HMAC-SHA256`，`base64url` 去 padding。
- AES：`key_raw = b"1a2b3c4d" + k.encode()`；长度不在 `{16,24,32}` 时，`len>32` 抛 `ValueError("AES key too long")`，否则补 `\0` 到 `16/24/32` 中最小合法值；`AES/ECB/NoPadding` 解密；去掉尾部 `\0`；`utf-8` 解码 `errors="replace"`。
- `sanitize_answer`：把设计文档 11.3 的字符类逐区间翻译为 `re.compile(r"[^...]")`，替换为空格。禁止使用 `unicodedata` 重写语义。
- `html_to_text`：BeautifulSoup 解析；`br` 替换为换行；`p` 前后加换行；文本折叠。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_crypto.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add unipus_web/crypto.py tests/test_crypto.py
git commit -m "feat: crypto and text utilities"
```

---

### Task 3: 异常层级与宽松 JSON 模型

**Files:**
- Create: `unipus_web/api/__init__.py`, `unipus_web/api/errors.py`, `unipus_web/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `class UnipusError(Exception)`；子类 `NetworkError`、`AuthError`、`ApiError(code:int, message:str)`、`UnsupportedError`、`TaskStopped(Exception)`。
  - `unipus_web.models`：`User`、`CourseResource`、`Course`、`TaskSnapshot`、`AnswerRecord`、`SituationNode`、`LogRecord`、`RequestRecord`（均 dataclass）。
  - `lenient_obj(value: Any) -> dict`：`dict` 原样返回；`str` 二次 `json.loads`，失败返回 `{}`；其他返回 `{}`。
  - `as_int(value, default=0)`、`as_float(value, default=0.0)`、`as_bool(value, default=False)`、`as_str(value, default="")`：处理 `None`、空串、非法字符串。

- [ ] **Step 1: 写失败测试 `tests/test_models.py`**

```python
from unipus_web.models import lenient_obj, as_int, as_float, as_bool, CourseResource, Course

def test_lenient_obj_accepts_string_encoded_json():
    assert lenient_obj('{"a": 1}') == {"a": 1}
    assert lenient_obj("not json") == {}
    assert lenient_obj(None) == {}

def test_scalar_coercion_survives_empty_strings():
    assert as_int("", 7) == 7 and as_int("12", 0) == 12 and as_int(None, 0) == 0
    assert as_float("1.5", 0.0) == 1.5 and as_float("abc", 2.0) == 2.0
    assert as_bool("true", False) is True and as_bool("", True) is True

def test_course_resource_from_json_uses_defaults():
    r = CourseResource.from_json({"id": "123", "strategyId": "", "finishPointNum": None})
    assert r.id == 123 and r.strategy_id == 0 and r.finish_point_num == 0

def test_course_from_json_handles_missing_resources():
    c = Course.from_json({"id": 1, "name": "大英", "courseResourceList": None})
    assert c.name == "大英" and c.resources == []
```

- [ ] **Step 2: 运行确认失败**：`python -m pytest tests/test_models.py -v` → FAIL `ImportError`。

- [ ] **Step 3: 实现 `errors.py` 与 `models.py`**

`CourseResource` 字段：`id:int`、`resource_id:str`、`instance_id:str`、`strategy_id:int`、`name:str`、`finish_point_num:int`、`total_point_num:int`。`Course`：`id`、`name`、`start_time`、`end_time`、`resources:list[CourseResource]`。二者都有 `from_json(d) -> Self` 与 `to_dict()`。

`TaskSnapshot` 字段：`id, username, name, status, description, completed, total, progress_percent, user_name, school_name, user_operation, courses, warning, error`，`to_dict()` 返回可 JSON 序列化字典。

`SituationNode` 字段：`node_id, caption, name, path, role, finish_progress, duration, required, score_task_flag, children`。

`LogRecord`：`seq, ts, level, logger, message, task_id, thread`。
`RequestRecord`：`seq, ts, task_id, method, url, status_code, status_text, duration_ms, request_headers, response_headers, request_payload, response_body, error`。

- [ ] **Step 4: 运行确认通过** → PASS（4 passed）。
- [ ] **Step 5: Commit** `git commit -m "feat: error hierarchy and lenient models"`

---

### Task 4: 网络记录器与 HTTP 客户端

**Files:**
- Create: `unipus_web/network_log.py`, `unipus_web/api/client.py`
- Test: `tests/test_client.py`, `tests/test_network_log.py`

**Interfaces:**
- Produces:
  - `class NetworkRecorder(capacity: int = NETWORK_BUFFER_SIZE)`：`add(record: dict) -> None`、`query(after_seq: int = 0, limit: int = 200) -> list[dict]`、`snapshot() -> list[dict]`、`clear() -> None`、`set_listener(fn: Callable[[dict], None]) -> None`。
  - `redact_headers(headers: dict[str, str]) -> dict[str, str]`：把 `authorization`、`cookie`、`set-cookie`、`x-annotator-auth-token` 值替换为 `"<redacted>"`。
  - `redact_record(record: dict) -> dict`：额外把 `request_payload` 中含 `"password"` 的 JSON 值替换为 `"<redacted>"`。
  - `class UnipusClient(task_id: str, *, record: Callable[[dict], None] | None = None, proxy: str | None = None, timeout: float = 30.0)`；`close()`；所有方法返回 `dict`。
  - 方法签名：`login(username, password) -> dict`、`get_user_info() -> dict`、`get_course_list() -> dict`、`get_course_resource_info(resource_id: str) -> dict`、`get_all_tasks(course_instance_id: str) -> dict`、`get_required_part(strategy_id: int, course_resource_id: str) -> dict`、`get_total_and_unit_situation(resource_id: int, app_user_id: str) -> dict`、`get_unit_task_situation(node_id: str, resource_id: int, app_user_id: str, sso_id: str) -> dict`、`get_task_time_info(course_instance_id: str, open_id: str, unit_node_id: str) -> dict`、`get_answer(course_instance_id: str, task_id: str, open_id: str) -> dict`、`submit(body: str, open_id: str) -> dict`、`get_task_info(course_instance_id: str, task_id: str, version: str, open_id: str) -> dict`。

- [ ] **Step 1: 写失败测试（MockTransport，不联网）**

```python
import json, httpx, pytest
from unipus_web.api.client import UnipusClient
from unipus_web.api.errors import ApiError, AuthError
from unipus_web.network_log import NetworkRecorder, redact_headers

def make_client(handler, records=None):
    recorder = records.append if records is not None else None
    c = UnipusClient("task-test", record=recorder)
    c._client = httpx.Client(transport=httpx.MockTransport(handler),
                             follow_redirects=True)
    return c

def test_login_posts_expected_body_and_returns_rs():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "0", "rs": {"openid": "o1", "jwt": "j1", "username": "u1"}})
    c = make_client(handler)
    rs = c.login("u1", "p1")
    assert seen["url"] == "https://sso.unipus.cn/sso/0.1/sso/login"
    assert seen["body"] == {"username": "u1", "password": "p1", "remember": True,
                            "agreement": True, "service": "https://uai.unipus.cn/home"}
    assert rs["openid"] == "o1"

def test_login_without_rs_raises_auth_error():
    c = make_client(lambda r: httpx.Response(200, json={"code": "1", "msg": "密码错误"}))
    with pytest.raises(AuthError, match="密码错误"):
        c.login("u1", "bad")

def test_non_json_response_raises_api_error():
    c = make_client(lambda r: httpx.Response(502, text="<html>bad gateway</html>"))
    with pytest.raises(ApiError):
        c.get_course_list()

def test_transport_error_raises_network_error():
    def handler(request): raise httpx.ConnectTimeout("timeout", request=request)
    c = make_client(handler)
    with pytest.raises(Exception) as ei:
        c.get_course_list()
    assert "网络" in str(ei.value)

def test_record_contains_method_status_and_redaction():
    recs = []
    c = make_client(lambda r: httpx.Response(200, json={"success": True}), recs)
    c.get_course_list()
    assert recs[0]["method"] == "GET" and recs[0]["status_code"] == 200
    assert recs[0]["url"].endswith("/api/cmgt/course/getCourseListByStudent")
    assert redact_headers({"Authorization": "Bearer x", "User-Agent": "ua"})["Authorization"] == "<redacted>"
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。

- [ ] **Step 3: 实现 `network_log.py` 与 `api/client.py`**

- `UnipusClient._request(method, url, *, json_body=None, headers=None) -> httpx.Response` 统一负责：计时、发请求、记录 `NetworkRecorder` 字典（`seq` 由 recorder 生成）、异常转 `NetworkError`。
- `_parse(resp)`：状态码 `>=400` 抛 `ApiError`；`resp.json()` 失败抛 `ApiError(status, "服务端返回了非 JSON 内容")`。
- 所有 URL 按接口契约拼接，`headers` 保持一致（`User-Agent`、`Connection: keep-alive`；需要时 `Authorization: ""` 与 `x-annotator-auth-token`）。
- `login`：`rs` 为空时抛 `AuthError`，消息优先取响应 `msg`。
- cookie：同一个 `httpx.Client` 自动跨主机共享。
- `record` 失败不得影响主流程（`try/except` 包住）。
- `NetworkRecorder.add` 用 `collections.deque(maxlen=capacity)`，`seq` 自增；`query` 过滤 `seq > after_seq`。

- [ ] **Step 4: 运行确认通过** → PASS（5 passed）。
- [ ] **Step 5: Commit** `git commit -m "feat: unipus http client and network recorder"`

---

### Task 5: 课程结构解析

**Files:**
- Create: `unipus_web/core/__init__.py`, `unipus_web/core/course_detail.py`
- Test: `tests/test_course_detail.py`

**Interfaces:**
- Produces:
  - `class QuestionType(str, Enum)`，成员与字符串值见设计文档；`QuestionType.from_raw(s: str) -> QuestionType`（未知返回 `UNKNOWN`）。
  - `class Role(str, Enum)`：`UNIT/SECTION/NODE/LINK/GROUP`。
  - `class Node`：`id, role, caption, name, url, ref_out, children, question_num, bases, tab_type, link_type`。
  - `class CourseDetail`：`from_json(course_json: str | dict) -> CourseDetail`；属性 `name, type, units, node_index`；方法 `get_node(id) -> Node | None`、`get_question_types(id) -> list[QuestionType]`、`get_question_type(id, index=0) -> QuestionType`、`init_task_times(payload) -> bool`、`get_task_start(id) -> int`、`get_task_end(id) -> int`。
  - 常量：`INVALID_TYPES`、`STUDY_MODES`、`PRESET_MODES`（`set[QuestionType]`）。

- [ ] **Step 1: 写失败测试**

```python
import json
from unipus_web.core.course_detail import CourseDetail, QuestionType, Role

COURSE = {"name": "大英", "type": "general", "units": [
  {"id": "u1", "role": "unit", "caption": "Unit 1", "name": "Unit 1", "children": [
    {"id": "t1", "role": "link", "caption": "", "name": "Listening", "url": "x",
     "ref-out": "y", "question_num": 3, "base": "single-choice", "tab_type": "text", "linkType": "task"}]}]}

def test_parses_tree_and_question_types():
    c = CourseDetail.from_json(COURSE)
    assert c.get_node("t1").name == "Listening"
    assert c.get_question_types("t1") == [QuestionType.SINGLE_CHOICE]
    # 索引越界时回落到最后一个已知题型，而不是崩溃
    assert c.get_question_type("t1", 2) == QuestionType.SINGLE_CHOICE

def test_unknown_base_maps_to_unknown():
    data = json.loads(json.dumps(COURSE))
    data["units"][0]["children"][0]["base"] = "brand-new-type"
    assert CourseDetail.from_json(data).get_question_types("t1") == [QuestionType.UNKNOWN]

def test_task_times_read_from_strategies_level():
    c = CourseDetail.from_json(COURSE)
    payload = {"code": 0, "rt": {"leafs": {"t1": {
        "duration": 0, "strategies": {"start_time": 100, "end_time": 200}}}}}
    assert c.init_task_times(payload) is True
    assert c.get_task_start("t1") == 100 and c.get_task_end("t1") == 200

def test_task_times_fallback_to_leaf_level():
    c = CourseDetail.from_json(COURSE)
    c.init_task_times({"rt": {"leafs": {"t1": {"start_time": 5, "end_time": 6}}}})
    assert c.get_task_start("t1") == 5

def test_missing_times_use_defaults():
    c = CourseDetail.from_json(COURSE)
    c.init_task_times({"rt": {"leafs": {}}})
    assert c.get_task_start("nope") == 0 and c.get_task_end("nope") == 32503651200
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。

- [ ] **Step 3: 实现**

- `from_json`：接受 `str` 时 `json.loads`；`units` 缺失视为空；节点 `id` 取 `id` 或 `url`；`role != SECTION` 时读 `url`/`ref-out`；有 `children` 递归，否则读 `question_num`、`base.split(",")`、`tab_type`、`linkType`。
- `get_question_type(id, index)`：节点不存在或 `bases` 含 `UNKNOWN` → 抛 `UnsupportedError`；`role` 不是 `GROUP/LINK` → 抛 `UnsupportedError`；`index >= len(bases)` → 取 `bases[-1]`。
- `init_task_times`：`rt.leafs[node]`，优先 `leaf["strategies"]["start_time"]`，回退 `leaf["start_time"]`；缺失用 `0` / `DEFAULT_TASK_END`。
- 取值一律走安全访问，不做无意义的“先赋值再覆盖”。

- [ ] **Step 4: 运行确认通过** → PASS（5 passed）。
- [ ] **Step 5: Commit** `git commit -m "feat: course detail parser with time-level fix"`

---

### Task 6: 单元进度与答案解析

**Files:**
- Create: `unipus_web/core/unit_situation.py`, `unipus_web/core/answer.py`
- Test: `tests/test_unit_situation.py`, `tests/test_answer.py`

**Interfaces:**
- Produces:
  - `class UnitSituation`：`parse(payload: dict | str) -> UnitSituation`；`get_node_by_node_id(node_id: str) -> SituationNode | None`；`get_node_by_path(path: str) -> SituationNode | None`。
  - `class AnswerRecord`（复用 `models.AnswerRecord`）：`id: int`、`answers: list[str]`、`analysis_items: list[str]`、`analysis: str`。
  - `def parse_answers(answer_json: str) -> list[AnswerRecord]`：非数组/空/单项非法时返回可解析的部分，不抛未捕获异常。
  - `def extract_answers(answer: AnswerRecord, qtype: QuestionType) -> list[str]`：按题型规则抽取；不支持时抛 `UnsupportedError`。

- [ ] **Step 1: 写失败测试**

```python
from unipus_web.core.unit_situation import UnitSituation
from unipus_web.core.answer import parse_answers, extract_answers
from unipus_web.core.course_detail import QuestionType

def test_unit_situation_indexes_nested_nodes():
    payload = {"code": 1, "success": True, "value": {"list": [
      {"nodeId": "u", "role": "unit", "children": [
        {"nodeId": "", "role": "section", "children": [
          {"nodeId": "t", "role": "link", "finishProgress": 50, "path": "u/s/t"}]}]}]}}
    s = UnitSituation.parse(payload)
    assert s.get_node_by_node_id("t").finish_progress == 50
    assert s.get_node_by_node_id("") is None
    assert s.get_node_by_path("u/s/t").node_id == "t"

def test_answer_parsing_and_extraction():
    raw = ('[{"id": 11, "answer": "{\\"children\\":[{\\"answers\\":[\\"A\\"]},{\\"answers\\":[\\"B\\"]}]}",'
           ' "analysis": "{\\"children\\":[{\\"analysis\\":\\"why\\"}]}"}]')
    answers = parse_answers(raw)
    assert answers[0].id == 11
    assert extract_answers(answers[0], QuestionType.SINGLE_CHOICE) == ["A", "B"]
    assert extract_answers(answers[0], QuestionType.SHORT_ANSWER) == ["why"]
    assert extract_answers(answers[0], QuestionType.TEXT_LEARN) == []

def test_answer_parsing_tolerates_short_array():
    assert parse_answers("[]") == []
    assert parse_answers("not json") == []
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。
- [ ] **Step 3: 实现**

- `UnitSituation.parse`：递归 `value.list`；`pathIndex`、`nodeIdIndex`；`nodeId` 为空串不建索引。
- `parse_answers`：`json.loads`；必须为 list；每项 `answer`/`analysis` 是字符串时二次解析，失败则对应字段为 `[]`/`""`。
- `extract_answers`：客观题取 `children[*].answers[0]`；`SHORT_ANSWER` 取 `analysis.children[*].analysis`；`WRITING` 取 `analysis`；预设题型返回 `[]`；其他抛 `UnsupportedError`。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: unit situation and answer parsers"`

---

### Task 7: 提交体构造

**Files:**
- Create: `unipus_web/core/submit.py`
- Test: `tests/test_submit.py`

**Interfaces:**
- Produces:
  - `create_submit_body(instance_ids: list[int], answers: list[list[str]], group_id: str, course_id: str, open_id: str, question_types: list[QuestionType], *, sanitize: bool = True, now_ms: int | None = None) -> str`
  - `map_question_type(t: QuestionType) -> str`、`map_reply_type(t: QuestionType) -> str`

- [ ] **Step 1: 写失败测试（结构锁定提交体契约）**

```python
import json
from unipus_web.core.submit import create_submit_body
from unipus_web.core.course_detail import QuestionType

def test_single_question_body_matches_contract():
    body = json.loads(create_submit_body([11], [["A"]], "g", "c", "o", [QuestionType.SINGLE_CHOICE]))
    q = body["quesDatas"][0]
    assert q["instanceId"] == "11" and q["contextVersion"] == 0
    inner = json.loads(q["answer"])
    assert inner["children"] == [{"value": ["A"], "isDone": True}]
    assert body["submitType"] == 1 and body["thirdPartyJudges"] != "[]"
    assert json.loads(body["thirdPartyJudges"])[0]["payloads"][0]["recordDetail"]["score"] == 100.0

def test_preset_mode_body_has_no_quesdatas():
    body = json.loads(create_submit_body([0], [[]], "g", "c", "o", [QuestionType.TEXT_LEARN]))
    assert body["quesDatas"] == [] and body["submitType"] == 2 and body["hideLoading"] is True

def test_multi_question_body_has_course_answer_map():
    body = json.loads(create_submit_body([1, 2], [["A"], ["B"]], "g", "c", "o",
                                         [QuestionType.SINGLE_CHOICE, QuestionType.MATERIAL_BANKED_CLOZE]))
    assert len(body["quesDatas"]) == 2
    assert set(body["quesDatas"][0]["courseAnswerMap"]) == {"1", "2"}
    assert body["quesDatas"][0]["courseAnswer"]["isRight"] == [True]

def test_multi_question_answers_are_not_shared_or_accumulated():
    body = json.loads(create_submit_body([1, 2], [["A"], ["B", "C"]], "g", "c", "o",
                                         [QuestionType.SINGLE_CHOICE] * 2))
    a1 = json.loads(body["quesDatas"][0]["answer"])
    a2 = json.loads(body["quesDatas"][1]["answer"])
    assert [c["value"] for c in a1["children"]] == [["A"]]
    assert [c["value"] for c in a2["children"]] == [["B"], ["C"]]

def test_length_mismatch_raises():
    import pytest
    with pytest.raises(ValueError):
        create_submit_body([1, 2], [["A"]], "g", "c", "o", [QuestionType.SINGLE_CHOICE] * 2)
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。
- [ ] **Step 3: 实现**

实现 `create_submit_body` 的单题 / 预设 / 多题三条路径。多题路径字段：`courseAnswer`、`courseAnswerMap`、`instanceId`、`answer`、`context`、`contextVersion=1`、`answerVersion=0`；全局 `submitInfo` 的 `state.score` 长度 = 全部空格数；`strategy.endTime = now_sec + 30 天`。`answers` 长度不一致时抛 `ValueError`。`sanitize=True` 时每题答案先 `html_to_text` 再 `sanitize_answer`，单题与多题行为保持一致。

- [ ] **Step 4: 运行确认通过** → PASS（5 passed）。
- [ ] **Step 5: Commit** `git commit -m "feat: submit body builder with multi-question fix"`

---

### Task 8: 凭据加密存储

**Files:**
- Create: `unipus_web/credentials.py`
- Test: `tests/test_credentials.py`

**Interfaces:**
- Produces:
  - `class CredentialStore(path: Path = CREDENTIALS_FILE)`：`list() -> list[dict]`（每项 `{"id","username","label"}`）、`add(username: str, password: str, label: str = "") -> dict`、`get_secret(cred_id: str) -> tuple[str, str] | None`、`delete(cred_id: str) -> bool`。
  - `_protect(data: bytes) -> bytes`、`_unprotect(data: bytes) -> bytes`：Windows 走 DPAPI（ctypes `crypt32.CryptProtectData/CryptUnprotectData`，`CRYPTPROTECT_UI_FORBIDDEN=1`）；其他平台走 `cryptography` AES-GCM，密钥存 `path.with_suffix(".key")` 且 `chmod 0o600`。

- [ ] **Step 1: 写失败测试**

```python
from unipus_web.credentials import CredentialStore

def test_add_list_get_delete_roundtrip(tmp_path):
    store = CredentialStore(tmp_path / "cred.dat")
    item = store.add("13800000000", "secret-pw", "测试账号")
    assert store.list()[0]["username"] == "13800000000"
    assert store.get_secret(item["id"]) == ("13800000000", "secret-pw")
    assert store.delete(item["id"]) is True
    assert store.list() == []

def test_file_does_not_contain_plaintext_password(tmp_path):
    path = tmp_path / "cred.dat"
    CredentialStore(path).add("u", "very-secret-pw")
    assert b"very-secret-pw" not in path.read_bytes()

def test_duplicate_username_updates_existing(tmp_path):
    store = CredentialStore(tmp_path / "cred.dat")
    a = store.add("u", "p1")
    b = store.add("u", "p2")
    assert a["id"] == b["id"] and store.get_secret(b["id"]) == ("u", "p2")
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。
- [ ] **Step 3: 实现**

- 文件格式：整个 JSON `{"version":1,"items":[...]}` 加密后写入；`_protect`/`_unprotect` 负责平台差异。
- 损坏文件：当作空存储，备份为 `credentials.dat.corrupt-<ts>`，不崩溃。
- `list()` 不含密码。
- id 用 `uuid4().hex`。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: encrypted credential store"`

---

### Task 9: 事件总线与日志

**Files:**
- Create: `unipus_web/events.py`, `unipus_web/logging_setup.py`
- Test: `tests/test_events.py`, `tests/test_logging.py`

**Interfaces:**
- Produces:
  - `class EventBus`：`bind_loop(loop)`、`publish(event_type: str, payload: dict) -> None`、`subscribe() -> asyncio.Queue`、`unsubscribe(q)`、`seq` 属性。
  - `class LogStore(capacity=LOG_BUFFER_SIZE)`：`add(level: str, logger: str, message: str, task_id: str | None = None, thread: str | None = None) -> dict`、`query(after_seq=0, limit=1000, min_level=None) -> list[dict]`、`clear()`、`set_listener(fn)`。
  - `class BusLogHandler(logging.Handler)`：把 logging 记录写入 `LogStore`。
  - `setup_logging(log_store, level=logging.DEBUG) -> None`。

- [ ] **Step 1: 写失败测试**

```python
import asyncio, logging
from unipus_web.events import EventBus
from unipus_web.logging_setup import LogStore, BusLogHandler

def test_event_bus_delivers_from_thread_safely():
    async def scenario():
        bus = EventBus(); bus.bind_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        bus.publish("task.updated", {"id": "t1"})
        evt = await asyncio.wait_for(q.get(), timeout=1)
        assert evt["type"] == "task.updated" and evt["data"]["id"] == "t1"
    asyncio.run(scenario())

def test_log_store_filters_and_sequences():
    store = LogStore(capacity=3)
    for i, lvl in enumerate(["INFO", "ERROR", "DEBUG", "WARN"]):
        store.add(lvl, "test", f"m{i}")
    assert [r["message"] for r in store.query()] == ["m2", "m3"]  # 容量 3 保留最后 3 条
    assert [r["level"] for r in store.query(min_level="WARN")] == ["WARN"]
    assert store.query(after_seq=1)[0]["message"] == "m2"

def test_bus_log_handler_captures_message_and_task_id():
    store = LogStore()
    h = BusLogHandler(store)
    lg = logging.getLogger("t"); lg.addHandler(h); lg.setLevel(logging.DEBUG)
    lg.info("hello", extra={"task_id": "t1"})
    assert store.query()[-1]["task_id"] == "t1"
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。
- [ ] **Step 3: 实现**

- `EventBus.publish`：未 bind loop 时直接丢弃并 `logging.debug`；每个订阅者 `loop.call_soon_threadsafe(q.put_nowait, event)`，队列满时丢弃最旧。
- `LogStore`：`deque(maxlen=capacity)` + `itertools.count` 序号；级别过滤用 `logging._nameToLevel`。
- `BusLogHandler.emit` 用 `record.getMessage()`，`task_id` 取 `getattr(record, "task_id", None)`，线程名取 `record.threadName`。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: event bus and in-memory log store"`

---

### Task 10: 任务状态机

**Files:**
- Create: `unipus_web/core/task.py`
- Test: `tests/test_task_state.py`

**Interfaces:**
- Produces:
  - `class Status(str, Enum)`：`INITIALIZING/READY/NEED_OPERATION/WAITING/RUNNING/PAUSED/COMPLETED/ERROR`。
  - `class UserOperation(str, Enum)`：`CHOOSE_COURSE`。
  - `class TaskControl(Protocol)`：`checkpoint() -> None`、`set_description(str)`、`set_progress(completed:int,total:int)`、`set_status(Status)`、`wait_for_cooldown(ms:int, waiting_desc:str, after_desc:str)`、`suspend() -> None`、`warn(str)`、`stop_requested -> bool`、`user -> User | None`。
  - `class Task`：构造 `Task(task_id: str, username: str, password: str | None, *, client_factory: Callable[[str], UnipusClient], on_change: Callable[[dict], None], on_warning: Callable[[str], None], on_error: Callable[[str], None], credential_id: str | None = None)`；方法 `initialize() -> None`、`start() -> bool`、`request_pause()`、`request_resume()`、`request_stop()`、`choose_course(course: Course, resource: CourseResource)`、`checkpoint()`、`wait_for_cooldown(...)`、`suspend()`、`snapshot() -> dict`、`wait_for_user_operation()`。

- [ ] **Step 1: 写失败测试（不联网，用 FakeClient）**

```python
import threading, time
from unipus_web.core.task import Task, Status

class FakeClient:
    def login(self, u, p): return {"openid": "o", "jwt": "j", "username": u}
    def get_user_info(self): return {"success": True, "value": {"userInfo": {
        "name": "张三", "schName": "某大学", "appUserId": "a", "ssoId": "s"}}}
    def close(self): pass

def make_task(**kw):
    events = []
    t = Task("task-u", "u", "p", client_factory=lambda tid: FakeClient(),
             on_change=lambda snap: events.append(snap), on_warning=lambda m: events.append({"warn": m}),
             on_error=lambda m: events.append({"err": m}), **kw)
    t.initialize()
    return t, events

def test_initialize_sets_ready_and_user():
    t, _ = make_task()
    assert t.status == Status.READY
    assert t.user.name == "张三" and t.user.school_name == "某大学"

def test_stop_wakes_cooldown_immediately():
    t, _ = make_task()
    threading.Thread(target=lambda: t.wait_for_cooldown(60_000, "冷却", "继续"), daemon=True).start()
    time.sleep(0.05)
    start = time.monotonic()
    t.request_stop()
    time.sleep(0.15)
    assert time.monotonic() - start < 1.0
    assert t.status == Status.READY

def test_pause_blocks_checkpoint_until_resume():
    t, _ = make_task()
    seen = []
    def worker():
        t.set_status(Status.RUNNING)
        t.request_pause()
        seen.append("before")
        t.checkpoint()
        seen.append("after")
    th = threading.Thread(target=worker, daemon=True); th.start()
    time.sleep(0.1)
    assert seen == ["before"] or seen == []
    t.request_resume()
    th.join(timeout=1)
    assert "after" in seen

def test_generation_prevents_stale_writes():
    t, events = make_task()
    t.start()  # 进入 READY 后启动 → 无 learn 依赖时立即失败为 ERROR 或 COMPLETED
    t.request_stop()
    gen = t.generation
    t._set_status_if_current(gen - 1, Status.RUNNING)
    assert t.status == Status.READY
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。

- [ ] **Step 3: 实现**

- 内部使用 `threading.Condition`（`self._cond`）、`self._stop_event`、`self._generation`。
- `initialize()`：`client = client_factory(task_id)`；`login` → `get_user_info`；成功置 READY；`AuthError` → ERROR + `on_error`；`NetworkError` → ERROR + `on_error`；`close()` 客户端。
- `start()`：仅 READY 可启动；`generation += 1`；新线程跑 `_run(gen)`；立刻返回 `True`。
- `_run(gen)`：`set_status(RUNNING)`；调用 `learn_course(...)`；按结果置 COMPLETED；捕获 `TaskStopped` 静默返回；其他异常置 ERROR + `on_error`；`finally` 不关闭客户端（用于重启）。
- `checkpoint()`：`stop_requested` → `raise TaskStopped`；`status == PAUSED` → `cond.wait()` 直到非 PAUSED 或 stop。
- `wait_for_cooldown`：`monotonic` 截止时间；每 1s `cond.wait(1)`；PAUSED 时继续等待；stop 时退出；结束后恢复 RUNNING。
- `request_stop()`：`stop_event.set()`；`generation += 1`（使旧线程写入失效）；状态 READY；`cond.notify_all()`。
- `request_resume()`：状态 RUNNING；`cond.notify_all()`。
- `_set_status_if_current(gen, status)`：仅当 `gen == self._generation` 时写入并 `on_change`。
- `snapshot()` 返回 `TaskSnapshot.to_dict()`。

> 注：`Task._run` 依赖 Task 11 的 `learn_course`。Task 10 实现时先把 `_run` 写成导入调用；Task 11 完成后跑全量测试。

- [ ] **Step 4: 运行确认通过**（`tests/test_task_state.py` 中不依赖 Learn 的用例）→ PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: task state machine with generation guard"`

---

### Task 11: 学习主流程

**Files:**
- Create: `unipus_web/core/learn.py`
- Modify: `unipus_web/core/task.py: _run`（接入 `learn_course`）
- Test: `tests/test_learn.py`

**Interfaces:**
- Produces:
  - `@dataclass LearnSummary(submitted_tasks: int, skipped_tasks: int, completed_units: int, skipped_reasons: list[str])`。
  - `learn_course(control: TaskControl, client: UnipusClient, resource: CourseResource, *, allow_multi_question: bool = True, sleep: Callable[[float], None] = time.sleep) -> LearnSummary`。
- Consumes：Task 3~7 的模型与解析、`CourseDetail`、`UnitSituation`、`parse_answers`、`extract_answers`、`create_submit_body`。

- [ ] **Step 1: 写失败测试（FakeClient / FakeControl）**

```python
from unipus_web.core.learn import learn_course
from unipus_web.models import CourseResource

class FakeControl:
    stop_requested = False
    def __init__(self): self.descs = []; self.statuses = []; self.progress = []; self.warnings = []
    def checkpoint(self): pass
    def set_description(self, s): self.descs.append(s)
    def set_progress(self, c, t): self.progress.append((c, t))
    def set_status(self, s): self.statuses.append(s)
    def wait_for_cooldown(self, ms, w, a): pass
    def suspend(self): pass
    def warn(self, m): self.warnings.append(m)
    user = type("U", (), {"app_user_id": "a", "sso_id": "s", "open_id": "o"})()

class FakeClient:
    def __init__(self, answers): self.answers = answers
    def get_course_resource_info(self, rid): return {"success": True, "value": {"courseResource": {
        "courseName": "c", "courseResourceId": 1, "resourceId": "r", "courseInstanceId": "ci",
        "strategyId": 7, "tutorial": {"resourceName": "book"}}}}
    def get_all_tasks(self, ci): return {"code": 0, "course": '{"name":"c","units":[]}'}
    def get_required_part(self, sid, rid): return {"success": True, "value": {"courseUnitStrategyList": []}}
    def get_total_and_unit_situation(self, rid, uid): return {"success": True, "value": {
        "totalDetail": {"finishProgress": 100}, "unitList": []}}
    def get_task_time_info(self, *a): return {"rt": {"leafs": {}}}
    def get_answer(self, *a): return {"code": 0, "data": self.answers, "k": ""}
    def submit(self, body, oid): return {"code": 0, "data": {"version": "v", "state": {"score_avg": 100}}}
    def get_task_info(self, *a): return {"code": 0, "data": {"state": {"__EXTEND_DATA__": {"__SUMMARY__": {"answerList": {}}}}}}
    def get_course_list(self): return {"success": True, "value": {"courseList": []}}

def test_returns_completed_when_total_progress_is_100():
    summary = learn_course(FakeControl(), FakeClient("[]"), CourseResource(id=1))
    assert summary.submitted_tasks == 0 and summary.skipped_tasks == 0

def test_skips_unsupported_node_without_crashing():
    # 通过单元进度返回一个不在 required 里的节点，验证缺失节点的容错
    ...
```

> 第二个测试需要把课程树、必修表、单元进度伪装完整；实现时在测试文件内提供 `build_course(...)` 辅助函数，构造：一个单元、一个必修任务、`base="single-choice"`、`question_num=2`、单元进度缺失该 node，断言 `learn_course` 返回 `skipped_tasks >= 1` 且 `control.warnings` 含 "缺失"。

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。
- [ ] **Step 3: 实现**

严格按设计文档 5.3 的顺序实现。关键点：

- `required.get(unit.node_id)` 为空 → 跳过单元。
- `need_learn = [tid for tid in required if (node := situation.get_node_by_node_id(tid)) and node.finish_progress != 100.0]`；`node is None` 时记录 warning `"单元进度缺失节点 {tid}"`。
- `_learn_task`：
  - 时间窗：`checkpoint` 后判断 `start < now < end`，不满足则跳过。
  - `types = course.get_question_types(task_id)`；`len(types) != 1` 且非多小题支持 → 跳过。多小题（同类型、`question_num>1`）在 `allow_multi_question=True` 时继续，并 `logger.warning("[experimental] multi-question submit ...")`。
  - 题型交集 `INVALID_TYPES` → 跳过并记录原因。
  - 取答案：非预设模式才请求；`parse_answers`；每题独立 `answers.append(extract_answers(...))`；答案条数不足 `question_num` → 跳过并 warning。
  - 提交：5 次/分钟限流；`600001/600002` 等 120s 重试；`data` 为 `None` 时按失败处理。
  - 零分检查：`get_task_info` → 客观题 `questionType in (1,3)` 且 `score_avg == 0` → `control.warn(...)` + `control.suspend()`。
  - 刷新课程进度：`get_course_list` 匹配 `resource.id/instance_id`，`control.set_progress`。
- 所有 `except Exception` 只用于"跳过单个任务"，必须 `logger.exception` 且把原因加入 `skipped_reasons`，不得吞掉 `TaskStopped`。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: learning pipeline with node and multi-question fixes"`

---

### Task 12: 任务管理器与报告

**Files:**
- Create: `unipus_web/core/manager.py`, `unipus_web/core/reporter.py`
- Test: `tests/test_manager.py`, `tests/test_reporter.py`

**Interfaces:**
- Produces:
  - `class TaskManager(*, bus: EventBus, log_store: LogStore, network: NetworkRecorder, credentials: CredentialStore, allow_multi_question: bool = True, client_factory: Callable[[str], UnipusClient] | None = None)`；`create_task(username=None, password=None, credential_id=None) -> dict`（返回快照；creds 二选一，重复用户名返回 409 语义的 `ValueError`）、`start(id)`、`pause(id)`、`resume(id)`、`stop(id)`、`remove(id)`、`choose_course(id, course_id, resource_id)`、`get(id)`、`snapshots() -> list[dict]`、`shutdown()`。
  - `build_report(manager, log_store, network) -> bytes`：内存 zip，含 `logs.log`、`networks.jsonl`、`meta.json`。
- Consumes：Task 10 的 `Task`、Task 4 的 `NetworkRecorder`、Task 9 的 `EventBus/LogStore`。

- [ ] **Step 1: 写失败测试**

```python
import io, zipfile, json
from unipus_web.core.manager import TaskManager
from unipus_web.core.reporter import build_report
from unipus_web.credentials import CredentialStore
from unipus_web.events import EventBus
from unipus_web.logging_setup import LogStore
from unipus_web.network_log import NetworkRecorder

class FakeClient:
    def login(self, u, p): return {"openid": "o", "jwt": "j", "username": u}
    def get_user_info(self): return {"success": True, "value": {"userInfo": {"name": "张三", "schName": "学校"}}}
    def close(self): pass

def make_manager(tmp_path):
    return TaskManager(bus=EventBus(), log_store=LogStore(), network=NetworkRecorder(),
                       credentials=CredentialStore(tmp_path / "c.dat"),
                       client_factory=lambda tid: FakeClient())

def test_create_task_from_credentials_then_remove(tmp_path):
    m = make_manager(tmp_path)
    cred = m.credentials.add("u", "p")
    snap = m.create_task(credential_id=cred["id"])
    m._wait_ready(snap["id"], timeout=2)
    assert m.get(snap["id"]).status.value == "READY"
    assert m.remove(snap["id"]) is True
    assert m.snapshots() == []

def test_duplicate_task_raises(tmp_path):
    import pytest
    m = make_manager(tmp_path)
    m.create_task(username="u", password="p")
    with pytest.raises(ValueError):
        m.create_task(username="u", password="p")

def test_report_zip_redacts_password(tmp_path):
    m = make_manager(tmp_path)
    m.log_store.add("INFO", "t", "login u/plain-pw")
    m.network.add({"seq": 1, "method": "POST", "url": "https://sso.unipus.cn/sso/0.1/sso/login",
                   "request_payload": '{"password":"plain-pw"}', "response_body": ""})
    data = build_report(m)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        assert {"logs.log", "networks.jsonl", "meta.json"} <= set(names)
        joined = b"".join(z.read(n) for n in names).decode("utf-8", "replace")
        assert "plain-pw" not in joined
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。
- [ ] **Step 3: 实现**

- `create_task`：优先 `credential_id` 解密；`username` 作为任务 id `task-{username}`；重复抛 `ValueError("任务已存在")`；创建后启后台初始化线程；`_wait_ready` 仅供测试。
- 事件：任何 `Task` 变化 → `bus.publish("task.updated", snap)`；`on_warning` → `bus.publish("task.warning", {...})`；`on_error` → `bus.publish("task.error", {...})`。
- `remove`：先 `request_stop`，从字典删除，`bus.publish("task.removed")`；线程自然退出，不阻塞 HTTP 请求。
- `shutdown()`：停止所有任务。
- `build_report`：Redaction 使用 `redact_record`；剔除登录、用户信息、`totalAndUnitSituation` 三类 URL；日志中的用户名/姓名/手机号做字面替换；输出是 zip 字节。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: task manager and report export"`

---

### Task 13: FastAPI 应用

**Files:**
- Create: `unipus_web/app.py`, `unipus_web/__main__.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces:
  - `create_app(*, allow_multi_question: bool = True, testing: bool = False) -> FastAPI`。
  - `run(host: str = "127.0.0.1", port: int | None = None, open_browser: bool = True) -> None`。
- Consumes：Task 12 的 `TaskManager`、Task 9 的 `EventBus/LogStore`、Task 8 的 `CredentialStore`。

- [ ] **Step 1: 写失败测试（TestClient + fake client factory）**

```python
from fastapi.testclient import TestClient
from unipus_web.app import create_app

def client():
    app = create_app(testing=True)
    app.state.manager.client_factory = lambda tid: FakeClient()  # 同 Task 12
    return TestClient(app)

def test_index_and_snapshot():
    c = client()
    assert c.get("/").status_code == 200
    assert c.get("/api/tasks").json() == []

def test_add_task_and_validation_error():
    c = client()
    r = c.post("/api/tasks", json={"username": "u", "password": "p"})
    assert r.status_code == 202
    assert r.json()["status"] in {"INITIALIZING", "READY", "ERROR"}

def test_bad_host_header_rejected():
    c = client()
    assert c.get("/", headers={"host": "evil.example"}).status_code == 400

def test_credentials_never_return_password():
    c = client()
    c.post("/api/credentials", json={"username": "u", "password": "p"})
    body = c.get("/api/credentials").text
    assert "password" not in body and '"p"' not in body

def test_report_download_headers():
    c = client()
    r = c.post("/api/report")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
```

- [ ] **Step 2: 运行确认失败** → FAIL `ImportError`。
- [ ] **Step 3: 实现**

路由按设计文档第 7 节。要点：

- `Host` 校验中间件：允许 `127.0.0.1`、`localhost`、`::1`（含端口）；`testing=True` 时额外允许 `testserver`；否则 400。
- 生命周期：`startup` 里 `bus.bind_loop(asyncio.get_running_loop())`；`shutdown` 调 `manager.shutdown()`。
- `POST /api/tasks`：接受 `{"username","password"}` 或 `{"credential_id"}`；返回 202 + 快照；缺字段 422。
- `GET /api/tasks/{id}/courses`：从任务已登录客户端拉课程列表；未登录返回 409。
- `POST /api/tasks/{id}/choose`：找到 `Course/CourseResource`，调用 `choose_course`，返回 204。
- `/ws`：`accept` → `subscribe` → 先发 `{"type":"snapshot","data":manager.snapshots()}` → 循环 `await q.get()` 发 JSON；`WebSocketDisconnect` 时退订。
- 静态文件：`/static` 挂 `StaticFiles`；`/` 返回 `FileResponse(index.html)`。
- 全局异常处理：`UnipusError` → 400/502 + `{"error":{"code","message"}}`；未捕获异常 → 500 + 同样结构，并 `logger.exception`。
- `__main__.py`：argparse（`--host` 默认 `127.0.0.1`，`--port`，`--no-browser`，`--no-multi-question`）；端口探测 `socket.bind`；`webbrowser.open` 延迟 0.8s。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: fastapi app, routes and websocket"`

---

### Task 14: Web 前端

**Files:**
- Create: `unipus_web/web/index.html`, `unipus_web/web/style.css`, `unipus_web/web/app.js`
- Test: `tests/test_frontend_contract.py`（静态检查关键选择器与 API 路径）

**Interfaces:**
- Consumes：Task 13 的 HTTP/WS 契约。
- Produces：可直接服务的单页应用。

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path
WEB = Path(__file__).parents[1] / "unipus_web" / "web"

def test_required_elements_and_endpoints_exist():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    for sel in ["task-list", "add-task", "debug-drawer", "report-modal", "theme-toggle"]:
        assert sel in html
    for ep in ["/api/tasks", "/api/logs", "/api/network", "/api/report", "/ws"]:
        assert ep in js
    assert "localStorage" in js
    assert "password" not in js.lower() or "credential_id" in js

def test_no_inline_external_scripts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "<script src=\"http" not in html
```

- [ ] **Step 2: 运行确认失败** → FAIL `FileNotFoundError`。
- [ ] **Step 3: 实现前端**

按设计文档 5.6 的结构实现。具体要求：

- 三栏心智：顶栏（标题/运行数/主题/调试/报告）、任务列表、底部添加按钮。
- 任务卡片：名称、用户名—描述、状态胶囊（含文字，不只颜色）、进度条、按钮（启动/暂停/恢复/停止/管理）。
- 添加任务弹窗：已保存账号下拉（`GET /api/credentials`）+ 新账号输入；"记住我"复选框；提交后按钮 loading；错误显示后端 `error.message`。
- 课程选择弹窗：`GET /api/tasks/{id}/courses`，两列选择，`POST .../choose`。
- 调试抽屉：日志（级别 chips、搜索、自动滚动、导出）与网络（方法/状态过滤、详情六标签）两个 tab。
- 报告：`POST /api/report` → blob 下载 `unipus_report_<ts>.zip`。
- WebSocket：断线指数退避重连，重连后重建任务列表；顶部显示连接状态点。
- 主题：`:root` 与 `[data-theme=dark]` CSS 变量；`localStorage["theme"]`；默认 `prefers-color-scheme`。
- 所有动态文本用 `textContent`，禁止 `innerHTML` 拼接用户数据（XSS 防护）。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: Commit** `git commit -m "feat: web ui"`

---

### Task 15: 打包、文档与冒烟

**Files:**
- Create: `run.bat`, `run.sh`, `README.md`, `scripts/smoke_login.py`, `tests/test_smoke_script.py`
- Modify: `pyproject.toml`（`[project.scripts] unipus-web = "unipus_web.__main__:main"`）

**Interfaces:**
- Produces：可交付目录；`scripts/smoke_login.py` 读取 `UNIPUS_USERNAME` / `UNIPUS_PASSWORD`，只调用 `login` 与 `get_course_list`。

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path
ROOT = Path(__file__).parents[1]

def test_run_bat_creates_venv_and_launches():
    text = (ROOT / "run.bat").read_text(encoding="utf-8")
    assert ".venv" in text and "pip install" in text and "unipus_web" in text

def test_smoke_script_is_read_only():
    text = (ROOT / "scripts" / "smoke_login.py").read_text(encoding="utf-8")
    assert "get_course_list" in text
    assert ".submit(" not in text and "submit(" not in text
    assert "UNIPUS_USERNAME" in text
```

- [ ] **Step 2: 运行确认失败** → FAIL。
- [ ] **Step 3: 实现**

- `run.bat`：检测 `.venv`，不存在则 `python -m venv`；`pip install -r requirements.txt`（带 `.venv\Scripts\python.exe -m pip`）；`start` 浏览器由程序自己开；`python -m unipus_web %*`。
- `README.md`：项目说明、截图占位、启动方式、常见问题、免责声明、已知限制（多小题未实网验证、无验证码处理、不支持的题型）、安全说明（仅本机、密码加密、报告中脱敏）。
- `smoke_login.py`：argparse + `getpass` 回退；打印用户信息与课程数量；异常退出码 1。

- [ ] **Step 4: 运行确认通过** → PASS。
- [ ] **Step 5: 全量验证**

```bash
.venv/Scripts/python -m pytest -v
.venv/Scripts/python -c "from unipus_web.app import create_app; print(create_app(testing=True).title)"
```

- [ ] **Step 6: 启动冒烟（不联网部分）**

```bash
.venv/Scripts/python -m unipus_web --no-browser &
sleep 3
curl -s http://127.0.0.1:8765/api/tasks
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/
```
Expected: `[]`、`200`。然后结束进程。

- [ ] **Step 7: Commit**

```bash
git add run.bat run.sh README.md scripts/ tests/test_smoke_script.py pyproject.toml
git commit -m "chore: packaging, docs and smoke script"
```

---

## Self-Review

**Spec coverage：** 设计文档第 4 节目录结构 → Task 1/2/3/4/5/6/7/8/9/10/11/12/13/14；第 5 节核心设计 → Task 4~14；第 6 节 21 项健壮性约定 → Task 2、4、5、6、7、10、11、12、13、14 均有对应的实现与测试。无遗漏。

**Type consistency：** `UnipusClient` 方法名在 Task 4/11/12/13 一致；`TaskControl` 与 `Task` 的方法名一致；`TaskSnapshot.to_dict()` 的字段在 Task 13/14 的 JS 中一致使用 `snake_case`。

**Review Focus 落点：** 1→Task 4 `test_login_without_rs_raises_auth_error`；2→Task 10 `test_stop_wakes_cooldown_immediately` + Task 11 异常路径；3→Task 10 同测；4→Task 5 `test_questiontype_index` + Task 6 容错 + Task 11 缺失节点；5→Task 4 `test_non_json_response_raises_api_error` + Task 13 全局异常处理。

**比例：** 计划约 600 行，spec 约 280 行；代码块仅保留签名与断言，未转录实现体。
