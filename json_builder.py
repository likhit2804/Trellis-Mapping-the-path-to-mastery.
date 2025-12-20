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
# HELPER FUNCTIONS
# ==========================================
def clean_title(title):
    """Removes dot leaders and trailing page numbers."""
    title = re.sub(r'\.{2,}.*', '', title)
    title = re.sub(r'\s+\d+$', '', title)
    return title.strip()

def determine_label(title, level, has_parts_seen):
    """
    Decides if a node is a Part, Chapter, or Topic based on text and context.
    """
    lower = title.lower()
    
    # Explicit detection
    if "part " in lower and len(title) < 50: 
        return "Unit"  # We use 'Unit' for Parts so they aren't confused with Chapters
    if "chapter " in lower:
        return "Chapter"
    
    # Fallback logic if no explicit keywords are found
    if level == 1:
        # If we have seen explicit Parts before, Level 1 items that aren't chapters might be Appendices or Units
        return "Chapter" if not has_parts_seen else "Unit"
    elif level == 2:
        return "Topic" if has_parts_seen else "Subtopic"
    
    return "Topic"

# ==========================================
# MAIN LOGIC
# ==========================================
def build_curriculum_from_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        print(f"❌ Error: File '{pdf_path}' not found.")
        return [], []

    doc = fitz.open(pdf_path)
    toc = doc.get_toc() 
    doc.close()

    if not toc:
        print("❌ Error: No Table of Contents found.")
        return [], []

    print(f"📖 Found {len(toc)} TOC entries. Parsing...")

    nodes = []
    hierarchy_stack = {}
    sibling_tracker = {}
    
    # Pre-scan to see if "Part" exists in the document
    has_parts = any("part " in entry[1].lower() for entry in toc)

    for i, entry in enumerate(toc):
        level, raw_title, page = entry[0], entry[1], entry[2]
        title = clean_title(raw_title)

        if title.lower() in ["contents", "index", "bibliography", "preface"]:
            continue

        # 1. Determine Label (The Fix)
        # We force logic to distinguish Part vs Chapter
        if "part " in title.lower() or "section " in title.lower():
            label = "Unit"  # Use a different label for containers
        elif "chapter" in title.lower():
            label = "Chapter"
        else:
            # If the PDF uses Parts (Level 1), then Chapters are Level 2
            if has_parts:
                if level == 2: label = "Chapter"
                elif level > 2: label = "Topic"
                else: label = "Unit" # Level 1 is Part
            else:
                # Standard Structure
                if level == 1: label = "Chapter"
                elif level == 2: label = "Topic"
                else: label = "Subtopic"

        node_id = f"NODE_{i:04d}"

        new_node = {
            "id": node_id,
            "title": title,
            "label": label, 
            "page": page,
            "children": [],       
            "prerequisites": []   
        }

        # 2. HIERARCHY (Parent -> Child)
        parent_level = level - 1
        if parent_level in hierarchy_stack:
            parent_id = hierarchy_stack[parent_level]
            for n in reversed(nodes):
                if n["id"] == parent_id:
                    n["children"].append(node_id)
                    break
        
        hierarchy_stack[level] = node_id
        # Clear deeper levels
        keys = [k for k in hierarchy_stack if k > level]
        for k in keys: del hierarchy_stack[k]

        # 3. SEQUENCE (Sibling -> Sibling)
        if level in sibling_tracker:
            prev_id = sibling_tracker[level]
            new_node["prerequisites"].append(prev_id)
        
        sibling_tracker[level] = node_id
        keys = [k for k in sibling_tracker if k > level]
        for k in keys: del sibling_tracker[k]

        nodes.append(new_node)

    # ==========================================
    # FLATTEN RELATIONSHIPS
    # ==========================================
    relationships = []

    for node in nodes:
        # Hierarchy
        for child_id in node["children"]:
            relationships.append({
                "source": node["id"],
                "target": child_id,
                "relation": "HAS_PART"
            })
        
        # Sequence
        for prereq_id in node["prerequisites"]:
            relationships.append({
                "source": prereq_id,
                "target": node["id"],
                "relation": "REQUIRES"
            })
            
        del node["children"]
        del node["prerequisites"]

    return nodes, relationships

if __name__ == "__main__":
    nodes, relationships = build_curriculum_from_pdf(INPUT_PDF)

    if nodes:
        output = {
            "nodes": nodes,
            "relationships": relationships
        }
        with open(OUTPUT_JSON, "w") as f:
            json.dump(output, f, indent=2)
        print(f"✅ Success! Saved {len(nodes)} nodes to {OUTPUT_JSON}")