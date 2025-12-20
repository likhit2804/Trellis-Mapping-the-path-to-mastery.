import os
import logging
from neo4j import GraphDatabase
from dotenv import load_dotenv
from collections import defaultdict

# -----------------------------------------------------
# Logging
# -----------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_RELATIONS = {"HAS_PART", "REQUIRES", "RELATED_TO"}

# =====================================================
# Validation
# =====================================================
def validate_no_cycles(edges):
    """
    Detect cycles ONLY in REQUIRES edges
    Direction:
        PREREQUISITE --> DEPENDENT
    """
    graph = defaultdict(list)

    for e in edges:
        if e["relation"] == "REQUIRES":
            graph[e["source"]].append(e["target"])

    visited, stack = set(), set()

    def dfs(node):
        if node in stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        stack.add(node)
        for nei in graph.get(node, []):
            if dfs(nei):
                return True
        stack.remove(node)
        return False

    all_nodes = set(graph.keys())
    for targets in graph.values():
        all_nodes.update(targets)

    for n in all_nodes:
        if dfs(n):
            raise ValueError(f"❌ Cycle detected involving '{n}'")


def validate_edges(nodes, edges):
    node_ids = {n["id"] for n in nodes}

    for e in edges:
        if e["relation"] not in ALLOWED_RELATIONS:
            raise ValueError(f"❌ Invalid relation type: {e['relation']}")
        if e["source"] not in node_ids:
            raise ValueError(f"❌ Edge source missing: {e['source']}")
        if e["target"] not in node_ids:
            raise ValueError(f"❌ Edge target missing: {e['target']}")

# =====================================================
# CurriculumGraphBuilder
# =====================================================
class CurriculumGraphBuilder:
    def __init__(self, uri, auth):
        self.driver = GraphDatabase.driver(uri, auth=auth)

    def close(self):
        self.driver.close()

    # -------------------------
    # Schema
    # -------------------------
    def setup_schema(self):
        queries = [
            """
            CREATE CONSTRAINT curriculum_node_id_unique IF NOT EXISTS
            FOR (n:CurriculumNode) REQUIRE n.id IS UNIQUE
            """,
            """
            CREATE INDEX curriculum_node_title_index IF NOT EXISTS
            FOR (n:CurriculumNode) ON (n.title)
            """
        ]
        with self.driver.session() as session:
            for q in queries:
                session.run(q)
        logger.info("✅ Schema ready")

    # -------------------------
    # Nodes
    # -------------------------
    def ingest_nodes(self, nodes):
        query = """
        UNWIND $nodes AS node
        MERGE (n:CurriculumNode {id: node.id})
        SET n.title = node.title,
            n.name = node.title

        FOREACH (_ IN CASE WHEN node.label = 'Chapter' THEN [1] ELSE [] END |
            SET n:Chapter
        )
        FOREACH (_ IN CASE WHEN node.label = 'Topic' THEN [1] ELSE [] END |
            SET n:Topic
        )
        FOREACH (_ IN CASE WHEN node.label = 'Subtopic' THEN [1] ELSE [] END |
            SET n:Subtopic
        )
        """
        with self.driver.session() as session:
            session.run(query, nodes=nodes)

        logger.info(f"✅ Inserted {len(nodes)} nodes")

    # -------------------------
    # Relationships
    # -------------------------
    def ingest_relationships(self, edges):
        query = """
        UNWIND $edges AS e
        MATCH (s:CurriculumNode {id: e.source})
        MATCH (t:CurriculumNode {id: e.target})
        MERGE (s)-[r:`%s`]->(t)
        SET r += e.props
        """

        with self.driver.session() as session:
            for rel in ALLOWED_RELATIONS:
                rel_edges = [
                    {
                        "source": e["source"],
                        "target": e["target"],
                        "props": {k: e[k] for k in e if k not in {"source", "target", "relation"}}
                    }
                    for e in edges if e["relation"] == rel
                ]

                if rel_edges:
                    session.run(
                        query % rel,
                        edges=rel_edges
                    )

        logger.info(f"✅ Inserted {len(edges)} relationships")

# =====================================================
# Curriculum Data (FIXED)
# =====================================================
import json

with open("curriculum1.json", "r", encoding="utf-8") as f:
    curriculum_data = json.load(f)
# =====================================================
# Run
# =====================================================
load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

if __name__ == "__main__":
    builder = CurriculumGraphBuilder(
        NEO4J_URI,
        (NEO4J_USERNAME, NEO4J_PASSWORD)
    )

    try:
        validate_edges(curriculum_data["nodes"], curriculum_data["relationships"])
        validate_no_cycles(curriculum_data["relationships"])

        builder.setup_schema()
        builder.ingest_nodes(curriculum_data["nodes"])
        builder.ingest_relationships(curriculum_data["relationships"])

        logger.info("🎉 Curriculum graph built successfully")

    finally:
        builder.close()
