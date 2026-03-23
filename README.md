# AgentToAgent 代码逻辑文档

## 整体架构

```
HTTP 请求
  │
  ▼
api/ata.py (FastAPI Router)
  │
  ▼
services/agentManager.py (AgentManager)
  │
  ├─► factory/agentFactory.py (AgentFactory 单例，内存容器)
  │     └─► models/runtimeAgent.py (RuntimeAgent，真正执行推理)
  │               └─► services/skillsManager.py (SkillsManager + DownloadSkillTool)
  │               └─► skillsCenter/skill_center.py (SkillCenter，按任务加载 skill)
  │                         └─► utils/__init__.py (MarkdownSkillUtil)
  │
  └─► models/agentInfo.py + agentStateHistory.py (SQLAlchemy ORM，MySQL)
```

---

## 完整逻辑流程

### Phase 1 — 注册 `POST /agentRegister`

1. 接收 `AgentRequest`（含 user_id、api_key、model_name）
2. `AgentManager.agentRegister()` 向 `agents` 表写入一条记录：
   - `name = req.model_name`
   - `model = "qwen3-max"`（硬编码）
   - `status = "new"`
3. 同时写入一条 `AgentStateHistory`（old=None → new="new"）
4. 返回 `{id, status}`

### Phase 2 — 唤醒 `POST /connect`

1. 接收 `AgentRequest`（含 agent_id、api_key）
2. `AgentManager.connect()` 从 DB 查询 agent，校验 api_key 且 status in ["new","sleep"]
3. 调用 `AgentFactory.create()`，在内存中实例化 `RuntimeAgent`：
   - `SkillsManager().init_base_skills()` 返回 `[DownloadSkillTool()]` 作为基础工具
   - `ChatOpenAI(model=..., api_key=...)` 初始化 LLM
   - `_build_agent_entity()` 构建 AgentExecutor（目前调用 `create_agent`，该函数不存在）
4. DB 状态改为 "wake"，写入 AgentStateHistory
5. 返回 `{id, status}`

### Phase 3 — 使用 `POST /use`

1. 接收 `AgentRequest`（含 user_id、messages）
2. `AgentManager.use()` 通过 `AgentFactory.get(req.user_id)` 取出内存中的 RuntimeAgent
3. 调用 `RuntimeAgent.invoke(user_message)`：
   - **先调用** `load_skills_and_rebuild_Agent(user_message)`：
     - `SkillCenter.load_for_task(agent_entity, task_description)` 用 LLM 分析任务
     - LLM 读取 `allskills.json`，返回所需 skill 的 JSON 列表
     - 对每个 skill：已安装 → 直接 `_load_local(slug)` 读取 SKILL.md 构建 `MarkdownSkillUtil`；未安装 → invoke agent 触发 `DownloadSkillTool` 下载，再 `_load_local`
     - 新增 skill 追加到 `_skills`，重建 agent_entity
   - **再调用** `agent_entity.invoke({"input": user_message})` 执行推理
   - 返回 `state["output"]`

---

## 问题清单

### 一、运行时崩溃（Critical）

| # | 文件 | 行 | 问题 | 修复方案 |
|---|------|----|------|----------|
| 1 | `models/runtimeAgent.py` | 8 | `from langchain.agents import create_agent` — 该函数**不存在**，import 时即报错 | 改为 `from langchain.agents import create_openai_tools_agent, AgentExecutor` 并在 `_build_agent_entity` 中正确使用 |
| 2 | `skillsCenter/skill_center.py` | 93 | `agent.invoke([HumanMessage(...)])` — AgentExecutor 不接受消息列表，应传 `{"input": "..."}` | 改为 `agent.invoke({"input": prompt})` |
| 3 | `skillsCenter/skill_center.py` | 97 | `response.content` — AgentExecutor.invoke 返回 dict，不是 AIMessage，`.content` 会 AttributeError | 改为 `response["output"]` |
| 4 | `skillsCenter/skill_center.py` | 67 | `agent.invoke({"messages": [HumanMessage(...)]})` — 同上，AgentExecutor 不接受 `messages` 键 | 改为 `agent.invoke({"input": f"请下载安装 skill: {slug}"})` |

### 二、逻辑不合理（Logic）

| # | 文件 | 行 | 问题 | 修复方案 |
|---|------|----|------|----------|
| 5 | `services/agentManager.py` | 94-98 | `use()` 中 `try: pass` 为空块，异常无法被捕获，`graph = ...` 在 try 外执行 | 将 `get` 和 `invoke` 都放入 try 块 |
| 6 | `services/agentManager.py` | 99 | `req.message` — `AgentRequest` 字段名为 `messages`，不是 `message`，会 AttributeError | 改为 `req.messages` |
| 7 | `api/ata.py` | 11 | `user_id: str` — DB 中 user_id 为 BigInteger（int），类型不一致，`AgentFactory` 容器以 int 为 key | 改为 `user_id: int` |
| 8 | `services/agentManager.py` | 25 | `model = "qwen3-max"` 硬编码写入 DB，但 `ChatOpenAI` 不认识该模型名（应为 OpenAI 模型名如 `gpt-4o`，或切换为通义 API base_url） | 根据实际使用的 API 提供商调整：若用通义 API，设 `base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"`；若用 OpenAI，改为有效模型名 |
| 9 | `models/runtimeAgent.py` | 46 | `SkillsManager().init_base_skills()` 每次 `__init__` 都新建 SkillsManager 实例，无状态类每次重建无意义 | 可改为 `SkillsManager.init_base_skills()` 静态方法，或保持现状（影响不大） |
| 10 | `skillsCenter/skill_center.py` | 86 | `allskills.json` 约 6MB，每次 invoke 都全量传入 LLM prompt，token 消耗极大且可能超上下文限制 | 考虑预处理：只传 id/name/slug/description 精简字段，过滤掉 downloads 等无关字段 |

### 三、注释与文档不同步（Minor）

| 文件 | 问题 |
|------|------|
| `models/runtimeAgent.py` L35 | docstring 提到 `skills` 参数"保留参数、传入值将被忽略"，但构造函数签名中根本没有 `skills` 参数 |
| `skillsCenter/skill_center.py` L45 | 参数注释写 `graph: RuntimeAgent 内部的 LangGraph 编译图`，实际已换为 AgentExecutor，且参数名是 `agent` |
| `api/ata.py` L44 | `use` 接口注释写"激活 agent，进入工作状态。-> wake -> active"，但代码中状态从未变为 active |

---

## 依赖完整性

`requirements.txt` 所列依赖均已覆盖运行时需求：

| 包 | 用途 |
|----|------|
| `fastapi[standard]` | HTTP 框架 |
| `uvicorn[standard]` | ASGI 服务器 |
| `sqlalchemy` + `pymysql` | ORM + MySQL 驱动 |
| `alembic` | DB 迁移 |
| `langchain` + `langchain-core` + `langchain-openai` | Agent 构建 |
| `langgraph` | 已引入但当前实际未使用（已换为 AgentExecutor） |
| `requests` | DownloadSkillTool 下载 zip |
| `python-dotenv` + `pydantic-settings` | 配置加载 |

> `dashscope` 包已在 requirements.txt 中保留，但代码已切换为 `langchain-openai`，如不再使用通义原生 SDK 可移除。

---

## 运行模式声明

当前系统明确采用`单实例内存态`运行模型。

含义如下：

1. `AgentFactory` 将运行时 Agent 存储在当前 Python 进程内存中。
2. 心跳监控器在 FastAPI 应用启动时初始化，并只管理当前进程可见的内存 Agent。
3. 数据库中的 agent 状态会被多个实例共享，但运行时 Agent 实体不会跨实例共享。

因此，当前实现不适合直接水平扩容为多实例部署。若未来需要支持多实例运行，必须至少完成以下改造：

1. 将运行时 Agent 会话与状态从进程内内存迁移到集中式存储或集中式调度层。
2. 让心跳、回收和任务路由基于共享状态工作，而不是依赖本地 `AgentFactory`。
3. 为实例间任务归属、锁竞争和恢复策略建立明确机制。
