from dataclasses import dataclass

from config import settings


@dataclass(slots=True)
class GraphAgentNode:
    agent_id: int
    user_id: int
    name: str
    status: str
    role_type: str | None
    level_rank: int | None
    manager_agent_id: int | None


class GraphAgentService:
    def __init__(self) -> None:
        """初始化图数据库访问配置。"""
        self._uri = settings.neo4j_uri
        self._username = settings.neo4j_username
        self._password = settings.neo4j_password
        self._database = settings.neo4j_database

    def create_agent_node(self, node: GraphAgentNode) -> None:
        """在图数据库中创建或更新一个 Agent 节点。"""
        driver = self._build_driver()
        query = """
        MERGE (a:Agent {agent_id: $agent_id})
        SET a.user_id = $user_id,
            a.name = $name,
            a.status = $status,
            a.role_type = $role_type,
            a.level_rank = $level_rank,
            a.manager_agent_id = $manager_agent_id
        """
        with driver.session(database=self._database) as session:
            session.run(
                query,
                agent_id=node.agent_id,
                user_id=node.user_id,
                name=node.name,
                status=node.status,
                role_type=node.role_type,
                level_rank=node.level_rank,
                manager_agent_id=node.manager_agent_id,
            )
        driver.close()

    def delete_agent_node(self, agent_id: int) -> None:
        """从图数据库中删除指定 Agent 节点及其关系。"""
        driver = self._build_driver()
        query = "MATCH (a:Agent {agent_id: $agent_id}) DETACH DELETE a"
        with driver.session(database=self._database) as session:
            session.run(query, agent_id=agent_id)
        driver.close()

    def has_friend_relation(self, source_agent_id: int, target_agent_id: int) -> bool:
        """判断两个 Agent 之间是否已经存在好友关系。"""
        driver = self._build_driver()
        query = """
        MATCH (:Agent {agent_id: $source_agent_id})-[:FRIEND]->(:Agent {agent_id: $target_agent_id})
        RETURN count(*) > 0 AS exists
        """
        with driver.session(database=self._database) as session:
            record = session.run(
                query,
                source_agent_id=source_agent_id,
                target_agent_id=target_agent_id,
            ).single()
        driver.close()
        return bool(record["exists"]) if record else False

    def is_manager_of(self, manager_agent_id: int, subordinate_agent_id: int) -> bool:
        """判断一个 Agent 是否是另一个 Agent 的直属上级。"""
        driver = self._build_driver()
        # REPORTS_TO 表示“下级 -> 上级”，因此这里按该方向判断直属上下级关系。
        query = """
        MATCH (:Agent {agent_id: $subordinate_agent_id})-[:REPORTS_TO]->(:Agent {agent_id: $manager_agent_id})
        RETURN count(*) > 0 AS exists
        """
        with driver.session(database=self._database) as session:
            record = session.run(
                query,
                manager_agent_id=manager_agent_id,
                subordinate_agent_id=subordinate_agent_id,
            ).single()
        driver.close()
        return bool(record["exists"]) if record else False

    def _build_driver(self):
        """构造 Neo4j 驱动；配置缺失或依赖未安装时直接报错。"""
        if not self._uri or not self._username or not self._password:
            raise RuntimeError(
                "Neo4j 配置不完整，请设置 NEO4J_URI、NEO4J_USERNAME、NEO4J_PASSWORD"
            )

        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError(
                "缺少 neo4j 依赖，请先安装 requirements.txt 或执行 pip install neo4j"
            ) from exc

        return GraphDatabase.driver(
            self._uri,
            auth=(self._username, self._password),
        )
