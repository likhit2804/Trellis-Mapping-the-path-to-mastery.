import os
import logging
import json
from neo4j import GraphDatabase
from dotenv import load_dotenv
from vector_store import vector_db  # <--- IMPORT YOUR NEW MODULE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
JSON_FILE = "curriculum1.json"

class GraphBuilder:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

    def close(self):
        self.driver.close()

    def build(self, data):
        with self.driver.session() as session:
            # 1. Neo4j Upload (Standard)
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:CurriculumNode) REQUIRE n.id IS UNIQUE")
            
            logger.info(f"📤 Uploading {len(data['nodes'])} nodes to Neo4j...")
            node_query = """
            UNWIND $nodes AS node
            MERGE (n:CurriculumNode {id: node.id})
            SET n.title = node.title,
                n.definition = node.definition,   
                n.key_points = node.key_points,
                n.content = node.content,         
                n.file_source = node.file_source,
                n.page = node.page,
                n.status = 'locked'
            
            FOREACH (_ IN CASE WHEN node.label = 'Chapter' THEN [1] ELSE [] END | SET n:Chapter)
            FOREACH (_ IN CASE WHEN node.label = 'Topic' THEN [1] ELSE [] END | SET n:Topic)
            FOREACH (_ IN CASE WHEN node.label = 'Exercise' THEN [1] ELSE [] END | SET n:Exercise)
            """
            session.run(node_query, nodes=data["nodes"])

            # 2. Pinecone Upload (New)
            logger.info(f"🧠 Embedding {len(data['nodes'])} nodes into Pinecone...")
            for node in data["nodes"]:
                # Only embed if there is real content (skip empty containers)
                if node.get("content") and len(node["content"]) > 50:
                    vector_db.upsert_textbook_node(
                        node_id=node["id"],
                        text=node["content"],
                        title=node["title"],
                        chapter=node.get("file_source", "Unknown")
                    )

            # 3. Relationships (Standard)
            logger.info(f"🔗 Linking {len(data['relationships'])} relationships...")
            edge_query = """
            UNWIND $edges AS e
            MATCH (s:CurriculumNode {id: e.source})
            MATCH (t:CurriculumNode {id: e.target})
            MERGE (s)-[r:`%s`]->(t)
            """
            for r_type in ["HAS_PART", "REQUIRES"]:
                batch = [e for e in data["relationships"] if e["relation"] == r_type]
                if batch:
                    session.run(edge_query % r_type, edges=batch)
            
            logger.info("🎉 Graph & Vector Databases successfully synced!")

if __name__ == "__main__":
    if not os.path.exists(JSON_FILE):
        print(f"❌ Error: {JSON_FILE} not found.")
    else:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        builder = GraphBuilder()
        builder.build(data)
        builder.close()