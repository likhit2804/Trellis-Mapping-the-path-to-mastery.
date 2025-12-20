import os
import time
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = "curriculum-tracker"

class VectorStore:
    def __init__(self):
        self.pc = Pinecone(api_key=PINECONE_API_KEY)
        
        if INDEX_NAME not in self.pc.list_indexes().names():
            self.pc.create_index(
                name=INDEX_NAME,
                dimension=384,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
        self.index = self.pc.Index(INDEX_NAME)
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')

    def get_embedding(self, text):
        return self.encoder.encode(text).tolist()

    def upsert_textbook_node(self, node_id, text, title, chapter):
        if not text: return
        vector = self.get_embedding(text)
        self.index.upsert(
            vectors=[{
                "id": node_id,
                "values": vector,
                "metadata": {"title": title, "chapter": chapter, "type": "textbook"}
            }],
            namespace="textbook"
        )

    def log_interaction(self, node_id, user_msg, ai_msg):
        vector = self.get_embedding(user_msg)
        interaction_id = f"{node_id}_{int(time.time())}"
        text_payload = f"User: {user_msg}\nAI: {ai_msg}"
        
        print(f"💾 LOGGING MEMORY: {interaction_id}") # Debug Print
        
        self.index.upsert(
            vectors=[{
                "id": interaction_id,
                "values": vector,
                "metadata": {
                    "node_id": node_id, 
                    "text": text_payload, 
                    "type": "chat"
                }
            }],
            namespace="chat_logs"
        )

    def retrieve_context(self, current_node_id, user_query):
        query_vec = self.get_embedding(user_query)
        
        chat_results = self.index.query(
            namespace="chat_logs",
            vector=query_vec,
            top_k=5,                 # Increased to 5
            include_metadata=True
        )
        
        past_chats = []
        for match in chat_results.matches:
            # --- THE FIX: LOWER THRESHOLD ---
            # Changed from 0.7 to 0.0 so we see EVERYTHING
            if match.score > 0.0: 
                print(f"🔍 FOUND MEMORY (Score: {match.score:.2f}): {match.metadata['text'][:50]}...")
                past_chats.append(match.metadata["text"])
                
        return past_chats

vector_db = VectorStore()