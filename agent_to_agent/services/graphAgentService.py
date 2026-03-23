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
        self._uri = settings.neo4j_uri
        self._username = settings.neo4j_username
        self._password = settings.neo4j_password
        self._database = settings.neo4j_database

    def create_agent_node(self, node: GraphAgentNode) -> None:
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
        driver = self._build_driver()
        query = "MATCH (a:Agent {agent_id: $agent_id}) DETACH DELETE a"
        with driver.session(database=self._database) as session:
            session.run(query, agent_id=agent_id)
        driver.close()

    def _build_driver(self):
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
