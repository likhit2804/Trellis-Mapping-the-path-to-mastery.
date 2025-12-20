from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
from vector_store import vector_db  # <--- ENSURE THIS IMPORT WORKS

load_dotenv()
app = Flask(__name__, static_folder='.')
CORS(app)

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

def get_driver():
    return GraphDatabase.driver(URI, auth=AUTH)

@app.route('/')
def serve_index():
    return send_file('template.html')

# --- 1. GRAPH API (Standard) ---
@app.route('/api/graph', methods=['GET'])
def get_graph():
    driver = get_driver()
    cypher_query = """
    MATCH (n:CurriculumNode)-[r:REQUIRES|HAS_PART]->(m:CurriculumNode)
    RETURN n.id, n.title, labels(n) as n_labels, type(r) as rel, m.id, m.title, labels(m) as m_labels
    """
    nodes = {}
    edges = []
    try:
        with driver.session() as session:
            result = session.run(cypher_query)
            for record in result:
                def get_type(labels):
                    if "Chapter" in labels: return "Chapter"
                    if "Exercise" in labels: return "Exercise"
                    return "Topic"

                n_type = get_type(record["n_labels"])
                m_type = get_type(record["m_labels"])

                s_id = record["n.id"]
                if s_id not in nodes:
                    nodes[s_id] = { "data": { "id": s_id, "label": record["n.title"], "type": n_type, "status": "completed" } }
                
                t_id = record["m.id"]
                if t_id not in nodes:
                    nodes[t_id] = { "data": { "id": t_id, "label": record["m.title"], "type": m_type, "status": "locked" } }

                edges.append({ "data": { "source": s_id, "target": t_id, "type": record["rel"] } })
        return jsonify(list(nodes.values()) + edges)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        driver.close()

# --- 2. INTELLIGENT CONTEXT RETRIEVAL (MISSING IN YOUR FILE) ---
@app.route('/api/context/retrieve', methods=['POST'])
def get_smart_context():
    data = request.json
    node_id = data.get("node_id")
    user_query = data.get("query")
    
    driver = get_driver()
    
    # A. Get Active Node Content (Neo4j)
    active_content = ""
    node_title = ""
    try:
        with driver.session() as session:
            # We explicitly fetch n.content here
            res = session.run(
                "MATCH (n:CurriculumNode {id: $id}) RETURN n.title, n.content", 
                id=node_id
            ).single()
            if res:
                node_title = res["n.title"]
                # Default to empty string if content is missing
                active_content = res.get("n.content") or ""
    finally:
        driver.close()

    # B. Get Past Memories (Pinecone)
    # This requires vector_store.py to be in the same folder
    past_memories = vector_db.retrieve_context(node_id, user_query)
    
    # C. Construct the "Perfect Prompt"
    context_package = {
        "active_node": {
            "title": node_title,
            "content": active_content
        },
        "memory": past_memories  # List of past chats
    }
    
    return jsonify(context_package)

# --- 3. CHAT LOGGING (MISSING IN YOUR FILE) ---
@app.route('/api/chat/log', methods=['POST'])
def log_chat():
    data = request.json
    vector_db.log_interaction(
        node_id=data.get("node_id"),
        user_msg=data.get("user_msg"),
        ai_msg=data.get("ai_msg")
    )
    return jsonify({"status": "logged"})

# --- 4. NODE DETAILS (Legacy Support) ---
@app.route('/api/node/<node_id>', methods=['GET'])
def get_node_details(node_id):
    driver = get_driver()
    query = """
    MATCH (n:CurriculumNode {id: $id})
    RETURN n.title, n.definition, n.key_points, n.content, n.file_source, n.page
    """
    try:
        with driver.session() as session:
            result = session.run(query, id=node_id).single()
            if result:
                return jsonify({
                    "title": result["n.title"],
                    "definition": result["n.definition"],
                    "key_points": result["n.key_points"], 
                    "content": result.get("n.content", ""),
                    "file_source": result["n.file_source"],
                    "page": result.get("n.page", 1)
                })
            return jsonify({"error": "Node not found"}), 404
    finally:
        driver.close()

if __name__ == '__main__':
    app.run(port=5000, debug=True)