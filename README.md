# AgentToAgent

一个面向多系统、多 Agent 协作场景的智能体基础平台。项目当前实现了 Agent 注册、运行时连接、权限治理、图关系维护、任务中心、跨系统回调和 Tool-first 的 Agent 调用模式。

## 项目定位

当前代码更适合被理解为一个“多 Agent 协作底座”，而不是一个面向最终用户的完整产品。它解决的是下面这些基础问题：

- 不同系统如何注册并接入自己的 Agent
- Agent 之间如何建立连接关系
- 连接、发消息、派任务等动作如何做权限判断
- 目标 Agent 不在线时，任务如何入队、补偿和回传
- Agent 如何通过内部 Tool 调用系统能力，而不是直接拼 HTTP 请求

## 当前架构

```text
FastAPI API
  └─ agent_to_agent/api/ata.py
      └─ AgentManager
          ├─ AgentFactory（单例，内存容器）
          │   └─ RuntimeAgent
          │       ├─ SkillsManager（基础 Tool 挂载）
          │       └─ SkillCenter（按任务动态加载 skill）
          ├─ PermissionService（权限决策）
          ├─ PermissionFileService（权限文件）
          ├─ AgentTaskService（任务持久化）
          ├─ AgentTaskDispatchService（按生命周期投递）
          ├─ GraphAgentService（Neo4j 关系）
          └─ AgentCallbackService（跨系统回调）
```

## 运行模式

当前系统明确采用：

- `single-instance in-memory`

含义如下：

- 运行时 `RuntimeAgent` 存在于当前 Python 进程内
- `AgentFactory` 以 `user_id` 为 key 保存在线 Agent
- 心跳监控器只管理当前进程内可见的 Agent
- 数据库和图数据库是持久化层，但运行时会话不是分布式共享的

这意味着当前实现不适合直接水平扩容为多副本协同运行。如果未来要做多实例，需要把内存态 Agent 会话和调度迁移到共享状态层。

## 技术栈

- Python
- FastAPI
- SQLAlchemy
- MySQL
- Neo4j
- LangChain
- Pydantic / pydantic-settings
- Requests

## 目录结构

```text
agent_to_agent/
  api/                    FastAPI 路由
  factory/                RuntimeAgent 内存工厂
  heartbeatmonitor/       心跳监控与超时回收
  models/                 SQLAlchemy ORM 与请求模型
  services/               核心业务服务
  skillsCenter/
    baseskills/           基础 Tool（连接、权限、任务、下载等）
    skills/               已安装 skill
  static/                 skill 元数据、白名单
  agentpermission/        Agent 权限文件目录
config/                   配置加载
tests/                    当前测试占位，覆盖较弱
```

## 环境配置

项目使用 `.env` 读取配置，示例见 [.env.example](/Users/deeplive/PycharmProjects/AgentToAgent/.env.example)。

最小配置：

```env
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/dbname?charset=utf8mb4
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=root1234
NEO4J_DATABASE=neo4j
```

说明：

- `DATABASE_URL` 必填
- Neo4j 配置在注册、关系查询、好友边维护时会使用
- 若 Neo4j 未配置完整，相关图操作会直接报错

## 安装与启动

### 安装依赖

```bash
pip install -r requirements.txt
```

或者：

```bash
pip install -e .
```

### 启动服务

```bash
agent-to-agent
```

等价于：

```bash
python -m agent_to_agent.main
```

默认监听：

- `0.0.0.0:8000`

健康检查：

- `GET /health`

返回示例：

```json
{
  "status": "ok",
  "deployment_mode": "single-instance in-memory"
}
```

## 当前开放的 API

当前 API 比较薄，真正复杂的 Agent 协作逻辑主要通过 Tool 驱动。

### `POST /agentRegister`

注册 Agent。

当前会同时完成三件事：

1. 写 MySQL `agents`
2. 在 Neo4j 中创建 `Agent` 节点
3. 在 `agentpermission/` 下生成 JSON 权限文件

### `POST /connect`

把一个 `new` 或 `sleep` 状态的 Agent 唤醒到 `wake`，并在内存中创建 `RuntimeAgent`。

连接时还会：

- 推进待处理任务到可处理状态
- 重试之前失败的响应回调
- 汇总待处理任务摘要
- 若当前 Agent 在线，向其注入任务摘要系统消息

### `POST /use`

向已连接的 Agent 发送用户消息，触发一次推理和 Tool 调用。

### `POST /destroy/{account_id}`

当前仍是占位方法，未完成实现。

## 核心数据模型

### MySQL `agents`

主要字段包括：

- `id`
- `user_id`
- `name`
- `role_type`
- `level_rank`
- `manager_agent_id`
- `callback_url`
- `callback_enabled`
- `callback_secret`
- `callback_timeout_seconds`
- `model`
- `api_key`
- `status`
- `last_active`

当前 `model` 在注册时固定写为 `qwen3-max`，实际通过 `ChatOpenAI` 兼容接口调用。

### MySQL `agent_tasks`

任务中心主表，当前已支持：

- `task_type`
- `task_group`
- `status`
- `payload`
- `requires_user_action`
- `user_notified`
- `priority`
- `retry_count`
- `max_retries`
- `last_error`
- `read_at`
- `last_delivered_at`
- `user_notified_at`
- `completed_at`
- `cancelled_at`
- `expires_at`

### MySQL `agent_task_events`

记录任务事件流，如：

- `created`
- `delivered`
- `accepted`
- `rejected`
- `push_success`
- `push_failed`
- `done`

### Neo4j

当前使用的节点和边：

- `(:Agent)`
- `[:REPORTS_TO]`
- `[:FRIEND]`
- `[:PENDING_REQUEST]`

### 权限文件

每个 Agent 一份：

- `agent_to_agent/agentpermission/{agent_id}.permission.json`

当前采用 `JSON` 作为静态权限文件格式，便于结构化读取和扩展。

## 核心模块说明

### 1. AgentFactory

[agentFactory.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/factory/agentFactory.py)

职责：

- 单例容器
- 创建和缓存 `RuntimeAgent`
- 根据 `user_id` 获取在线 Agent

当前容器 key 是 `user_id`，不是 `agent_id`。

### 2. RuntimeAgent

[runtimeAgent.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/models/runtimeAgent.py)

职责：

- 持有 LLM
- 挂载基础 Tool
- 根据任务动态加载额外 skill
- 消费内部系统消息
- 执行一次用户推理

当前行为：

- 每次 `invoke()` 前更新 `last_active`
- 先消费系统事件上下文，再处理用户消息
- 根据当前任务描述调用 `SkillCenter` 选 skill
- 如有新 Tool 则重建 Agent 实体

### 3. SkillsManager

[skillsManager.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/services/skillsManager.py)

当前基础 Tool 包括：

- `download_skill`
- `heartbeat`
- `request_connection`
- `respond_connection_request`
- `list_connection_requests`
- `check_agent_permission`
- `read_agent_permission`
- `list_my_tasks`
- `get_task_detail`
- `send_agent_memo`

### 4. SkillCenter

[skill_center.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/skillsCenter/skill_center.py)

当前逻辑：

- 读取 `allskills.json`
- 调用当前 Agent 的 LLM 选择所需 skill
- 未安装时触发 `DownloadSkillTool`
- 从本地 `SKILL.md` 构建 Tool

注意：

- 目前依然会把 `allskills.json` 整体送入模型分析，随着技能库增大，token 成本会显著上升
- 这是当前仍然明显的性能风险点

### 5. AgentManager

[agentManager.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/services/agentManager.py)

业务编排核心，负责串联：

- 注册
- 连接
- 使用
- 权限检查
- 任务中心
- 好友连接流
- 回调补偿
- 在线 Agent 的内部消息注入

### 6. PermissionService

[permissionService.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/services/permissionService.py)

统一权限引擎。

当前支持的动作：

- `add_friend`
- `send_message`
- `assign_task`
- `wake_and_deliver_task`

判定过程：

1. 读取目标 Agent 权限文件
2. 识别双方关系
3. 结合权限策略返回 `allow / deny / request`

### 7. AgentTaskService / AgentTaskDispatchService

[agentTaskService.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/services/agentTaskService.py)  
[agentTaskDispatchService.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/services/agentTaskDispatchService.py)

当前已经不只是简单建任务，而是带有一定产品化能力：

- 任务收件箱视图
- 通知视图
- 历史视图
- 失败视图
- 已读、已通知、重试、错误记录
- 连接后批量推进待处理任务

### 8. GraphAgentService

[graphAgentService.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/services/graphAgentService.py)

负责图数据库中的：

- Agent 节点创建
- 好友关系判断与建立
- 上下级关系判断
- 连接申请边建立与删除

### 9. AgentCallbackService

[agentCallbackService.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/services/agentCallbackService.py)

用于把关键结果回调到外部业务系统。

当前特性：

- `callback_url` 可配置
- 默认可为空
- 支持 HMAC-SHA256 签名
- 支持失败补偿

## 当前主要业务流

### 1. Agent 注册

`/agentRegister` -> `AgentManager.agentRegister()`

流程：

1. 写入 `agents`
2. 创建图节点
3. 创建权限文件
4. 写 `AgentStateHistory`

### 2. Agent 连接

`/connect` -> `AgentManager.connect()`

流程：

1. 校验 `agent_id + api_key`
2. 只允许 `new / sleep`
3. `AgentFactory.create()` 创建内存态 `RuntimeAgent`
4. 更新状态为 `wake`
5. 推进待处理任务
6. 重试回调补偿
7. 注入任务摘要系统消息

### 3. Agent 使用

`/use` -> `AgentManager.use()` -> `RuntimeAgent.invoke()`

流程：

1. 若状态为 `wake`，先切到 `active`
2. 从 `AgentFactory` 取出运行时 Agent
3. 消费系统消息上下文
4. 根据当前任务动态加载 skill
5. 调用 Agent 推理
6. 推理完成后恢复为 `wake`

### 4. 好友连接申请

Tool：

- `request_connection`
- `respond_connection_request`

流程：

1. A 发起请求
2. 系统对 B 做权限判断
3. 若 `deny` 直接拒绝
4. 若 `allow` 直接建 `FRIEND`
5. 若 `request` 创建 `friend_request` 任务并建 `PENDING_REQUEST`
6. B 处理后同步：
   - 图关系
   - 权限文件
   - 响应任务
   - 回调或补偿

### 5. 纪要发送

Tool：

- `send_agent_memo`

当前可用于：

- 已建立可通信关系的 Agent 间发送会议纪要、总结或通知内容

流程：

1. A 调 `send_agent_memo`
2. 系统先校验 `send_message`
3. 允许后创建 `memo_delivery` 任务
4. B 在线则进入收件箱
5. B 不在线则等待其下次 `connect`

## 当前 Tool-first 设计

当前项目刻意把复杂协作能力放在 Tool 层，而不是把 Agent 设计成直接调用 HTTP API。

这是因为当前真实架构是：

- 多个 Agent 运行在同一系统内部
- 由同一个 `AgentFactory` 管理
- 业务能力更适合以内置 Tool 暴露给 Agent

因此：

- API 更适合给外部系统和调试使用
- Tool 更适合给 RuntimeAgent 使用

## 心跳与回收机制

[heartbeatMonitor.py](/Users/deeplive/PycharmProjects/AgentToAgent/agent_to_agent/heartbeatmonitor/heartbeatMonitor.py)

应用启动时初始化 `HeartbeatMonitor`，后台线程定期检查：

- `wake` 超过 600 秒
- `active` 超过 1800 秒

超时后会：

1. 从 `AgentFactory` 容器移除
2. 更新数据库状态为 `sleep`
3. 写状态历史

## 当前项目的主要优点

- 核心模块职责已经比较清晰
- 权限、关系、任务、回调、生命周期基本拆分完毕
- Tool-first 模式与当前内存态 Agent 架构匹配
- 已经具备好友申请、离线补偿、回调通知、任务中心这些主链路

## 当前已知限制

### 1. 仍是单实例内存态

不能直接无脑扩多副本。

### 2. `destroy()` 未实现

销毁 API 还没有闭环。

### 3. 测试覆盖很弱

[tests/test_main.py](/Users/deeplive/PycharmProjects/AgentToAgent/tests/test_main.py) 目前基本是占位文件。

### 4. skill 选择仍然偏重

`SkillCenter` 依然会把整份 `allskills.json` 提交给模型分析，性能和 token 消耗不理想。

### 5. 运行时依赖外部环境

如果以下任一未配置正确，相关功能会失败：

- MySQL
- Neo4j
- 兼容 `ChatOpenAI` 的模型接入
- 外部系统回调地址

### 6. Python 版本边界

项目元数据声明 `>=3.10`，但当前某些依赖链在 Python 3.14 下会出现兼容性警告。更稳妥的运行基线建议使用 Python 3.10 到 3.12。

## 建议的开发顺序

如果继续演进这个项目，优先级建议如下：

1. 补测试
2. 精简 SkillCenter 的技能筛选链路
3. 完成 `destroy()` 和更多生命周期闭环
4. 抽出更明确的任务中心接口或前端展示层
5. 设计多实例共享状态方案

## 快速理解一句话

当前项目已经不是一个“只会对话的单 Agent Demo”，而是一个带有权限治理、图关系、任务中心、回调补偿和 Tool-first 协作能力的多 Agent 基础平台。
