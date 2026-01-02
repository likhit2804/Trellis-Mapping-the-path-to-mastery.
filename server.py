from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
from vector_store import vector_db
from google import genai 

load_dotenv()
app = Flask(__name__, static_folder='.')
CORS(app)

# ==========================================
# CONFIGURATION
# ==========================================
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
client = genai.Client(api_key=GEMINI_API_KEY)

def get_driver():
    return GraphDatabase.driver(URI, auth=AUTH)

@app.route('/')
def serve_index():
    return send_file('template.html')

# ==========================================
# 1. GRAPH API (Standard)
# ==========================================
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

# ==========================================
# 2. GENERATION API (THE NEW BRAIN)
# ==========================================
@app.route('/api/chat/generate', methods=['POST'])
def generate_response():
    data = request.json
    node_id = data.get("node_id")
    user_query = data.get("query")
    
    driver = get_driver()
    
    # A. Get Active Node Content (Neo4j)
    node_context = ""
    try:
        with driver.session() as session:
            res = session.run(
            """
            MATCH (n:CurriculumNode {id: $id})
            RETURN n.title, n.content, n.definition, n.key_points
            """, 
            id=node_id
        ).single()

        if res:
            # FIX: Fallback to definition + key_points when content is missing
            raw_content = res.get("n.content") or ""

            if not raw_content:
                if res.get("n.definition"):
                    raw_content += f"Definition: {res['n.definition']}\n"
                
                # CRASH FIX: Ensure key_points is a list even if DB returns None
                key_points = res.get("n.key_points") or []
                if key_points:
                    raw_content += "Key Points:\n" + "\n".join(f"- {p}" for p in key_points)

            node_context = f"CURRENT TOPIC: {res['n.title']}\nCONTENT:\n{raw_content}"

    finally:
        driver.close()

    # B. Get Past Memories (Pinecone)
    past_memories = vector_db.retrieve_context(node_id, user_query)
    memory_text = "\n".join(past_memories) if past_memories else "No relevant past discussions."

    # C. Construct System Prompt
    system_prompt = f"""
    You are an AI Tutor called Trellis.
    
    CONTEXT FROM TEXTBOOK:
    {node_context[:15000]} 
    
    RELEVANT PAST CONVERSATIONS:
    {memory_text}
    
    INSTRUCTIONS:
    Answer the user's question based strictly on the textbook context provided. 
    If the past conversations are relevant, refer to them.
    Keep the answer concise and educational.
    """

    # D. Gemini call
    try:
        result = client.models.generate_content(
            model="gemini-flash-latest", # Updated to specific stable model version
            contents=f"{system_prompt}\n\nUser: {user_query}"
        )
        ai_response = result.text
    except Exception as e:
        ai_response = f"Error generating response: {str(e)}"

    # E. Log the interaction
    vector_db.log_interaction(node_id, user_query, ai_response)

    return jsonify({
        "response": ai_response,
        "context_used": node_context[:200] + "..." 
    })

# ==========================================
# 3. OLD ENDPOINTS (PRESERVED)
# ==========================================
@app.route('/api/context/retrieve', methods=['POST'])
def get_smart_context():
    """Legacy: Retrieves context without generating an answer."""
    data = request.json
    node_id = data.get("node_id")
    user_query = data.get("query")
    
    driver = get_driver()
    
    active_content = ""
    node_title = ""
    try:
        with driver.session() as session:
            res = session.run(
                "MATCH (n:CurriculumNode {id: $id}) RETURN n.title, n.content, n.definition, n.key_points", 
                id=node_id
            ).single()
            if res:
                node_title = res["n.title"]
                # FIX: Fallback logic here as well
                active_content = res.get("n.content") or ""
                if not active_content:
                    def_text = res.get("n.definition", "")
                    
                    # CRASH FIX
                    key_points = res.get("n.key_points") or []
                    kp_text = "\n".join(f"- {p}" for p in key_points)
                    
                    active_content = f"{def_text}\n\nKey Points:\n{kp_text}".strip()
    finally:
        driver.close()

    past_memories = vector_db.retrieve_context(node_id, user_query)
    
    context_package = {
        "active_node": {
            "title": node_title,
            "content": active_content
        },
        "memory": past_memories 
    }
    return jsonify(context_package)

@app.route('/api/chat/log', methods=['POST'])
def log_chat():
    """Legacy: Allows manual logging from frontend."""
    data = request.json
    vector_db.log_interaction(
        node_id=data.get("node_id"),
        user_msg=data.get("user_msg"),
        ai_msg=data.get("ai_msg")
    )
    return jsonify({"status": "logged"})

@app.route('/api/node/<node_id>', methods=['GET'])
def get_node_details(node_id):
    """Legacy: Get raw node details."""
    driver = get_driver()
    query = """
    MATCH (n:CurriculumNode {id: $id})
    RETURN n.title, n.definition, n.key_points, n.content, n.file_source, n.page
    """
    try:
        with driver.session() as session:
            result = session.run(query, id=node_id).single()
            if result:
                # FIX: Construct content if missing so the frontend doesn't show Empty/None
                content_display = result.get("n.content")
                if not content_display:
                    def_text = result.get("n.definition", "")
                    
                    # CRASH FIX: Ensure we don't iterate over None
                    key_points = result.get("n.key_points") or []
                    kp_text = "\n".join(f"- {p}" for p in key_points)
                    
                    content_display = f"{def_text}\n\nKey Points:\n{kp_text}".strip()

                return jsonify({
                    "title": result["n.title"],
                    "definition": result.get("n.definition", ""),
                    "key_points": result.get("n.key_points") or [], # Send empty list, not null
                    "content": content_display,
                    "file_source": result.get("n.file_source", ""),
                    "page": result.get("n.page", 1)
                })
            return jsonify({"error": "Node not found"}), 404
    finally:
        driver.close()

if __name__ == '__main__':
    app.run(port=5000, debug=True)