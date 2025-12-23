import fitz  # PyMuPDF
import json
import re
import os

# ==========================================
# CONFIGURATION
# ==========================================
INPUT_FOLDER = "Final_Chapters"
OUTPUT_JSON = "curriculum1.json"

EXERCISE_TRIGGERS = [
    "Practice Exercises", "Bibliographical Notes", "Exercises", "Problems", "Review Questions"
]

# ==========================================
# TEXT PROCESSING & 5-BUCKET EXTRACTION
# ==========================================
def clean_text(text):
    if not text: return ""
    text = re.sub(r'\n\d+\s', ' ', text)
    text = re.sub(r'Page\s+\d+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_5_bucket_context(text):
    """
    Parses text into 5 Buckets: Anchor, Mechanics, Contrast, Limitations, Instance
    """
    if not text or len(text) < 50:
        return {"anchor": "Content not available.", "mechanics": [], "contrast": "", "limitations": "", "instance": ""}

    sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', text)
    sentences = [s.strip() for s in sentences if len(s) > 20]

    data = { "anchor": "", "mechanics": [], "contrast": "", "limitations": "", "instance": "" }

    # Regex Patterns
    def_regex = re.compile(r'\b(is a|refers to|defined as|means|function is|purpose is)\b', re.IGNORECASE)
    mech_regex = re.compile(r'\b(step|process|first|second|then|finally|algorithm)\b', re.IGNORECASE)
    comp_regex = re.compile(r'\b(unlike|whereas|difference|contrast|versus|similar to)\b', re.IGNORECASE)
    limit_regex = re.compile(r'\b(limitation|disadvantage|problem|overhead|requires|fails when)\b', re.IGNORECASE)
    ex_regex = re.compile(r'\b(for example|for instance|consider a|suppose|assume|scenario)\b', re.IGNORECASE)

    for i, s in enumerate(sentences):
        # Priority 1: Anchor
        if not data["anchor"] and def_regex.search(s):
            data["anchor"] = s
            continue
        # Priority 2: Instance
        if not data["instance"] and ex_regex.search(s):
            next_s = sentences[i+1] if i+1 < len(sentences) else ""
            data["instance"] = f"{s} {next_s}".strip()
            continue
        # Priority 3: Contrast & Limitations
        if not data["contrast"] and comp_regex.search(s):
            data["contrast"] = s
            continue
        if not data["limitations"] and limit_regex.search(s):
            data["limitations"] = s
            continue
        # Priority 4: Mechanics
        if mech_regex.search(s) or re.match(r'^[\u2022\-\d]\.', s):
            data["mechanics"].append(s)

    if not data["anchor"] and sentences: data["anchor"] = sentences[0]
    return data

# ==========================================
# PARSING LOGIC
# ==========================================
def parse_split_files(folder_path):
    if not os.path.exists(folder_path):
        print(f"❌ Error: Folder '{folder_path}' not found.")
        return [], []

    files = sorted([f for f in os.listdir(folder_path) if f.endswith(".pdf")])
    nodes, relationships = [], []
    
    print(f"📂 Found {len(files)} chapters. Parsing...")
    previous_chapter_id = None

    for i, filename in enumerate(files):
        file_path = os.path.join(folder_path, filename)
        title_clean = re.sub(r'^\d+_', '', filename.replace('.pdf', '')).replace('_', ' ')
        chapter_id = f"CHAP_{i:02d}"
        
        print(f"   Processing: {title_clean}...")
        
        doc = fitz.open(file_path)
        intro_text = clean_text(doc[0].get_text()) if len(doc) > 0 else ""
        
        header_pattern = re.compile(r'\n(\d+\.\d+(?:\.\d+)?)\s+([A-Z].*)')
        in_exercise_mode = False 

        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            
            if not in_exercise_mode:
                for trigger in EXERCISE_TRIGGERS:
                    if trigger in page_text:
                        in_exercise_mode = True; break

            matches = list(header_pattern.finditer(page_text))
            
            for k, match in enumerate(matches):
                sub_id = match.group(1)
                full_title = f"{sub_id} {match.group(2).strip()}"
                
                start, end = match.end(), matches[k+1].start() if k+1 < len(matches) else len(page_text)
                clean_content = clean_text(page_text[start:end])
                
                # MERGE STRATEGY: Skip small noise
                if len(clean_content) < 200 and not in_exercise_mode: continue

                sub_node_id = f"{chapter_id}_SUB_{sub_id.replace('.', '_')}"
                
                if in_exercise_mode:
                    new_node = {
                        "id": sub_node_id, "title": full_title[:100], "label": "Exercise",
                        "file_source": filename, "page": page_num + 1,
                        "data": { "anchor": clean_content[:500], "mechanics": [], "contrast": "", "limitations": "", "instance": "" }
                    }
                else:
                    if "?" in full_title: continue
                    # NEW: Use 5-Bucket Extraction
                    buckets = extract_5_bucket_context(clean_content)
                    new_node = {
                        "id": sub_node_id, "title": full_title[:100], "label": "Topic",
                        "file_source": filename, "page": page_num + 1,
                        "data": buckets 
                    }

                nodes.append(new_node)
                relationships.append({ "source": chapter_id, "target": sub_node_id, "relation": "HAS_PART" })

        doc.close()

        # Add Chapter Node (Container)
        nodes.append({
            "id": chapter_id, "title": title_clean, "label": "Chapter",
            "file_source": filename, "page": 1,
            "data": { "anchor": intro_text[:500] + "...", "mechanics": [], "contrast": "", "limitations": "", "instance": "" }
        })

        if previous_chapter_id:
            relationships.append({ "source": previous_chapter_id, "target": chapter_id, "relation": "REQUIRES" })
        previous_chapter_id = chapter_id

    return nodes, relationships

if __name__ == "__main__":
    nodes, edges = parse_split_files(INPUT_FOLDER)
    if nodes:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump({"nodes": nodes, "relationships": edges}, f, indent=2)
        print(f"\n✅ Success! Parsed {len(nodes)} nodes with 5-Bucket Schema.")
    else:
        print("⚠️ No data found.")