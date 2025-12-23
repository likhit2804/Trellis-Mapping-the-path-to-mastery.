import fitz  # PyMuPDF
import json
import re
import os

# ==========================================
# CONFIGURATION
# ==========================================
INPUT_PDF = "C:\\Users\\likhi\\OneDrive\\Pictures\\Desktop\\project\\OS_main.pdf"
OUTPUT_JSON = "curriculum1.json"

# ==========================================
# 1. HELPERS: TEXT & BUCKETS
# ==========================================
def clean_text(text):
    if not text: return ""
    text = re.sub(r'\n\d+\s', ' ', text)
    text = re.sub(r'Page\s+\d+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_5_bucket_context(text):
    """Parses text into the 5-Bucket Schema (Anchor, Mechanics, etc.)"""
    if not text or len(text) < 50:
        return {"anchor": "Content not available.", "mechanics": [], "contrast": "", "limitations": "", "instance": ""}

    sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', text)
    sentences = [s.strip() for s in sentences if len(s) > 20]
    
    data = {"anchor": "", "mechanics": [], "contrast": "", "limitations": "", "instance": ""}
    
    # Simple regex for the buckets
    patterns = {
        "anchor": re.compile(r'\b(is a|refers to|defined as|means|function is)\b', re.IGNORECASE),
        "mechanics": re.compile(r'\b(step|process|first|second|then|algorithm)\b', re.IGNORECASE),
        "contrast": re.compile(r'\b(unlike|whereas|difference|versus)\b', re.IGNORECASE),
        "limitations": re.compile(r'\b(limitation|disadvantage|problem|requires)\b', re.IGNORECASE),
        "instance": re.compile(r'\b(example|instance|scenario|suppose)\b', re.IGNORECASE)
    }

    for i, s in enumerate(sentences):
        if not data["anchor"] and patterns["anchor"].search(s): data["anchor"] = s; continue
        if not data["instance"] and patterns["instance"].search(s): 
            data["instance"] = s + (" " + sentences[i+1] if i+1 < len(sentences) else ""); continue
        if not data["contrast"] and patterns["contrast"].search(s): data["contrast"] = s; continue
        if not data["limitations"] and patterns["limitations"].search(s): data["limitations"] = s; continue
        if patterns["mechanics"].search(s): data["mechanics"].append(s)

    if not data["anchor"] and sentences: data["anchor"] = sentences[0]
    return data

# ==========================================
# 2. MAIN BUILDER
# ==========================================
def build_curriculum_from_pdf(pdf_path):
    if not os.path.exists(pdf_path): return [], []

    doc = fitz.open(pdf_path)
    toc = doc.get_toc() 
    
    if not toc:
        doc.close(); return [], []

    print(f"📖 Found {len(toc)} TOC entries. Parsing...")

    nodes = []
    hierarchy_stack = {}
    sibling_tracker = {}

    for i, entry in enumerate(toc):
        level, title, start_page = entry[0], entry[1].strip(), entry[2]
        
        # --- GRANULARITY RULE 1: DEPTH CAP ---
        # Ignore deep hierarchies (Level 4+) to prevent fragmentation
        if level > 3: 
            continue

        # --- TEXT EXTRACTION ---
        # Determine end page based on next TOC entry
        if i + 1 < len(toc):
            end_page = toc[i+1][2]
        else:
            end_page = start_page + 2 # Default for last entry

        # Extract text from the page range
        raw_text = ""
        try:
            # PyMuPDF uses 0-based indexing, TOC is 1-based
            for p_num in range(start_page - 1, min(end_page - 1, doc.page_count)):
                raw_text += doc.load_page(p_num).get_text()
        except: pass
        
        content = clean_text(raw_text)

        # --- GRANULARITY RULE 2: CONTENT THRESHOLD ---
        # If content is tiny (< 300 chars), it's just a Container (Structural Node)
        # If content is large (> 300 chars), it's a Learnable Topic (Meso Node)
        is_structural = len(content) < 300
        
        if is_structural:
            label = "Unit" if level == 1 else "Container"
            node_data = { "anchor": title, "note": "Structural Container - No direct content." }
        else:
            label = "Topic" if level > 1 else "Chapter"
            node_data = extract_5_bucket_context(content)

        node_id = f"NODE_{i:04d}"
        
        new_node = {
            "id": node_id,
            "title": title,
            "label": label, 
            "page": start_page,
            "data": node_data, # <--- NEW: Stores the 5 buckets
            "children": [],       
            "prerequisites": []   
        }

        # --- HIERARCHY & SEQUENCE LINKS ---
        parent_level = level - 1
        if parent_level in hierarchy_stack:
            parent_id = hierarchy_stack[parent_level]
            # Find parent in nodes list to append child
            # (Simple linear search is fine for typical book size)
            for n in reversed(nodes):
                if n["id"] == parent_id:
                    n["children"].append(node_id)
                    break
        
        hierarchy_stack[level] = node_id
        # Clear deeper levels from stack
        keys = [k for k in hierarchy_stack if k > level]
        for k in keys: del hierarchy_stack[k]

        if level in sibling_tracker:
            new_node["prerequisites"].append(sibling_tracker[level])
        
        sibling_tracker[level] = node_id
        keys = [k for k in sibling_tracker if k > level]
        for k in keys: del sibling_tracker[k]

        nodes.append(new_node)

    doc.close()

    # --- FLATTEN RELATIONSHIPS ---
    relationships = []
    for node in nodes:
        for child_id in node["children"]:
            relationships.append({ "source": node["id"], "target": child_id, "relation": "HAS_PART" })
        for prereq_id in node["prerequisites"]:
            relationships.append({ "source": prereq_id, "target": node["id"], "relation": "REQUIRES" })
        del node["children"]; del node["prerequisites"]

    return nodes, relationships

if __name__ == "__main__":
    nodes, relationships = build_curriculum_from_pdf(INPUT_PDF)
    if nodes:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump({"nodes": nodes, "relationships": relationships}, f, indent=2)
        print(f"✅ Success! Saved {len(nodes)} nodes to {OUTPUT_JSON}")