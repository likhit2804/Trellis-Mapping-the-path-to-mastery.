import os
import logging
import json
from neo4j import GraphDatabase
from dotenv import load_dotenv
from collections import defaultdict

# -----------------------------------------------------
# Logging
# -----------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_RELATIONS = {"HAS_PART", "REQUIRES", "RELATED_TO", "HAS_EXERCISE"}

# =====================================================
# Validation
# =====================================================
def validate_no_cycles(edges):
    """
    Detect cycles ONLY in REQUIRES edges.
    """
    graph = defaultdict(list)
    for e in edges:
        if e["relation"] == "REQUIRES":
            graph[e["source"]].append(e["target"])

    visited, stack = set(), set()

    def dfs(node):
        if node in stack: return True
        if node in visited: return False
        visited.add(node)
        stack.add(node)
        for nei in graph.get(node, []):
            if dfs(nei): return True
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
    valid_edges = []
    
    for e in edges:
        if e["relation"] not in ALLOWED_RELATIONS:
            raise ValueError(f"❌ Invalid relation type: {e['relation']}")
        
        # Check Source
        if e["source"] not in node_ids:
            logger.warning(f"⚠️ Edge source missing: {e['source']} -> {e['target']} (Skipping)")
            continue 
        
        # Check Target
        if e["target"] not in node_ids:
            logger.warning(f"⚠️ Edge target missing: {e['source']} -> {e['target']} (Skipping)")
            continue

        valid_edges.append(e)
        
    return valid_edges

# =====================================================
# Helper: Auto-Generate Hierarchy
# =====================================================
def generate_implicit_relationships(nodes):
    """
    Automatically creates hierarchy relationships.
    - Subtopics -> HAS_PART -> Parent Topic
    - Exercises -> HAS_EXERCISE -> Parent Topic
    """
    implicit_edges = []
    node_ids = {n["id"] for n in nodes}
    node_labels = {n["id"]: n.get("label", "Topic") for n in nodes}
    
    for node in nodes:
        curr_id = node["id"]
        if "_" in curr_id:
            parts = curr_id.rsplit('_', 1)
            parent_id = parts[0]
            
            if parent_id in node_ids:
                is_exercise = node_labels.get(curr_id) == "Exercise"
                rel_type = "HAS_EXERCISE" if is_exercise else "HAS_PART"
                
                implicit_edges.append({
                    "source": parent_id,
                    "target": curr_id,
                    "relation": rel_type,
                    "generated": True
                })
                
    logger.info(f"⚡ Generated {len(implicit_edges)} implicit hierarchical edges.")
    return implicit_edges

# =====================================================
# Helper: Prune Redundant Edges (Transitive Reduction)
# =====================================================
def prune_redundant_hierarchy(edges):
    """
    Removes 'shortcut' edges. 
    If A -> B and B -> C exist, remove A -> C.
    This ensures the graph is a clean tree, not a mesh.
    """
    logger.info("✂️ Pruning redundant hierarchical edges...")
    
    # 1. Separate hierarchy edges from others (like REQUIRES)
    hierarchy_types = {"HAS_PART", "HAS_EXERCISE"}
    hierarchy_edges = []
    other_edges = []
    
    # Build adjacency list for reachability check
    adj = defaultdict(set)
    
    for e in edges:
        if e["relation"] in hierarchy_types:
            hierarchy_edges.append(e)
            adj[e["source"]].add(e["target"])
        else:
            other_edges.append(e)

    # 2. Check for indirect paths
    def has_indirect_path(start, end):
        # BFS to find if there's a path from start to end WITHOUT using the direct edge
        queue = [start]
        visited = {start}
        
        while queue:
            curr = queue.pop(0)
            
            # Get neighbors
            neighbors = adj[curr]
            for n in neighbors:
                # CRITICAL: If we are at the start node, DO NOT follow the direct edge to 'end'
                if curr == start and n == end:
                    continue
                
                if n == end:
                    return True # Found an indirect path!
                
                if n not in visited:
                    visited.add(n)
                    queue.append(n)
        return False

    # 3. Filter
    final_hierarchy = []
    removed_count = 0
    
    for e in hierarchy_edges:
        u, v = e["source"], e["target"]
        if has_indirect_path(u, v):
            # If a path u -> ... -> v exists, the direct edge u -> v is redundant.
            removed_count += 1
            # logger.info(f"   - Removing: {u} -> {v}") # Uncomment to see details
        else:
            final_hierarchy.append(e)

    logger.info(f"✂️ Removed {removed_count} redundant edges.")
    return other_edges + final_hierarchy

# =====================================================
# CurriculumGraphBuilder
# =====================================================
class CurriculumGraphBuilder:
    def __init__(self, uri, auth):
        self.driver = GraphDatabase.driver(uri, auth=auth)

    def close(self):
        self.driver.close()

    def setup_schema(self):
        queries = [
            "CREATE CONSTRAINT curriculum_node_id_unique IF NOT EXISTS FOR (n:CurriculumNode) REQUIRE n.id IS UNIQUE",
            "CREATE INDEX curriculum_node_title_index IF NOT EXISTS FOR (n:CurriculumNode) ON (n.title)"
        ]
        with self.driver.session() as session:
            for q in queries:
                session.run(q)
        logger.info("✅ Schema ready")

    def ingest_nodes(self, nodes):
        query = """
        UNWIND $nodes AS node
        MERGE (n:CurriculumNode {id: node.id})
        SET n.title = node.title,
            n.name = node.title,
            n.definition = node.definition,
            n.key_points = node.key_points,
            n.file_source = node.file_source,
            n.page = node.page

        FOREACH (_ IN CASE WHEN node.label = 'Chapter' THEN [1] ELSE [] END | SET n:Chapter)
        FOREACH (_ IN CASE WHEN node.label = 'Topic' THEN [1] ELSE [] END | SET n:Topic)
        FOREACH (_ IN CASE WHEN node.label = 'Subtopic' THEN [1] ELSE [] END | SET n:Subtopic)
        FOREACH (_ IN CASE WHEN node.label = 'Exercise' THEN [1] ELSE [] END | SET n:Exercise)
        """
        with self.driver.session() as session:
            session.run(query, nodes=nodes)
        logger.info(f"✅ Inserted {len(nodes)} nodes")

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
                        "props": {k: e[k] for k in e if k not in {"source", "target", "relation", "generated"}}
                    }
                    for e in edges if e["relation"] == rel
                ]
                if rel_edges:
                    session.run(query % rel, edges=rel_edges)
        logger.info(f"✅ Inserted {len(edges)} relationships")

# =====================================================
# Main Execution
# =====================================================
if __name__ == "__main__":
    load_dotenv()
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

    try:
        with open("curriculum1.json", "r", encoding="utf-8") as f:
            curriculum_data = json.load(f)
    except FileNotFoundError:
        logger.error("❌ curriculum1.json not found.")
        exit(1)

    builder = CurriculumGraphBuilder(NEO4J_URI, (NEO4J_USERNAME, NEO4J_PASSWORD))

    try:
        nodes = curriculum_data.get("nodes", [])
        explicit_edges = curriculum_data.get("relationships", [])

        # 1. Pre-Processing: Separate Exercises
        for n in nodes:
            if n.get("label") == "Exercise":
                if not n["id"].endswith("_EX"):
                    n["id"] = n["id"] + "_EX"

        # 2. Generate Implicit Relationships
        implicit_edges = generate_implicit_relationships(nodes)
        
        # 3. Combine Edges
        combined_edges = []
        seen = set()
        
        for e in explicit_edges + implicit_edges:
            key = (e["source"], e["target"], e["relation"])
            if key not in seen:
                seen.add(key)
                combined_edges.append(e)

        # 4. Prune Redundancy (NEW STEP)
        # This removes "Grandparent -> Child" edges if "Grandparent -> Parent -> Child" exists
        pruned_edges = prune_redundant_hierarchy(combined_edges)

        # 5. Validate (Graceful Mode)
        final_edges = validate_edges(nodes, pruned_edges)

        # 6. Ingest
        builder.setup_schema()
        builder.ingest_nodes(nodes)
        builder.ingest_relationships(final_edges)

        logger.info("🎉 Curriculum graph built successfully")

    except Exception as e:
        logger.error(f"❌ Error: {e}")
    finally:
        builder.close()