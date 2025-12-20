import fitz  # PyMuPDF
import json
import re
import os

# ==========================================
# CONFIGURATION
# ==========================================
INPUT_FOLDER = "Final_Chapters"
OUTPUT_JSON = "curriculum1.json"

# Triggers that signal the start of the Exercise section
EXERCISE_TRIGGERS = [
    "Practice Exercises", 
    "Bibliographical Notes", 
    "Exercises", 
    "Problems",
    "Review Questions"
]

# ==========================================
# TEXT PROCESSING
# ==========================================
def clean_text(text):
    if not text: return ""
    text = re.sub(r'\n\d+\s', ' ', text)
    text = re.sub(r'Page\s+\d+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_dense_context(text):
    """
    Standard extractor for STUDY TOPICS (looks for definitions)
    """
    if not text or len(text) < 50:
        return {"definition": "Content not available.", "key_points": []}

    sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s', text)
    sentences = [s.strip() for s in sentences if len(s) > 20]

    # 1. Definition
    definition = ""
    def_regex = re.compile(r'\b(is a|refers to|defined as|means|consists of|function is|purpose is)\b', re.IGNORECASE)
    for sent in sentences[:5]: 
        if def_regex.search(sent) and len(sent) < 300:
            definition = sent
            break
    if not definition and sentences: 
        definition = sentences[0]

    # 2. Key Points
    keywords = ["important", "key", "primary", "step", "process", "feature", "advantage", "note"]
    key_points = []
    for sent in sentences:
        if sent == definition: continue
        if re.match(r'^[\u2022\-\d]\.', sent) or any(k in sent.lower() for k in keywords):
            key_points.append(sent)
            if len(key_points) >= 5: break
    
    # Fallback
    if len(key_points) < 3:
        for sent in sentences[1:]:
            if sent != definition and sent not in key_points:
                key_points.append(sent)
                if len(key_points) >= 5: break

    return {"definition": definition[:500], "key_points": key_points}

# ==========================================
# PARSING LOGIC
# ==========================================
def parse_split_files(folder_path):
    if not os.path.exists(folder_path):
        print(f"❌ Error: Folder '{folder_path}' not found.")
        return [], []

    files = sorted([f for f in os.listdir(folder_path) if f.endswith(".pdf")])
    nodes = []
    relationships = []
    
    print(f"📂 Found {len(files)} chapters. Parsing...")
    previous_chapter_id = None

    for i, filename in enumerate(files):
        file_path = os.path.join(folder_path, filename)
        
        # 1. Chapter Info
        title_clean = re.sub(r'^\d+_', '', filename.replace('.pdf', '')).replace('_', ' ')
        chapter_id = f"CHAP_{i:02d}"
        
        print(f"   Processing: {title_clean}...")
        
        doc = fitz.open(file_path)
        
        # Chapter Summary (Page 1)
        intro_text = ""
        if len(doc) > 0:
            intro_text = clean_text(doc[0].get_text())
        
        chapter_context = extract_dense_context(intro_text)
        subtopic_summaries = []

        # 2. Iterate Pages
        header_pattern = re.compile(r'\n(\d+\.\d+(?:\.\d+)?)\s+([A-Z].*)')
        
        # MODE SWITCH: Start as False, flip to True when we hit "Practice Exercises"
        in_exercise_mode = False 

        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            
            # --- DETECT SECTION CHANGE ---
            # If we haven't switched yet, check if this page starts the exercises
            if not in_exercise_mode:
                for trigger in EXERCISE_TRIGGERS:
                    if trigger in page_text:
                        print(f"      📝 Switched to 'Exercise' mode on page {page_num+1} ({trigger})")
                        in_exercise_mode = True
                        break

            # --- PARSE ITEMS ---
            matches = list(header_pattern.finditer(page_text))
            
            for k, match in enumerate(matches):
                sub_id_num = match.group(1)
                sub_title_text = match.group(2).strip()
                full_sub_title = f"{sub_id_num} {sub_title_text}"
                
                # Slicing logic
                start_idx = match.end()
                if k + 1 < len(matches):
                    end_idx = matches[k+1].start()
                else:
                    end_idx = len(page_text)
                
                specific_text = page_text[start_idx:end_idx]
                clean_content = clean_text(specific_text)
                
                # --- NODE CREATION LOGIC ---
                sub_node_id = f"{chapter_id}_SUB_{sub_id_num.replace('.', '_')}"
                
                if in_exercise_mode:
                    # >>> IT IS AN EXERCISE <<<
                    new_node = {
                        "id": sub_node_id,
                        "title": full_sub_title[:100],
                        "label": "Exercise",  # <--- NEW LABEL
                        "file_source": filename,
                        "page": page_num + 1,
                        # For exercises, the 'definition' is just the full question text
                        "definition": clean_content[:500], 
                        "key_points": ["Practice Question"] 
                    }
                else:
                    # >>> IT IS A TOPIC <<<
                    # Filter out obvious questions that appear before the exercise section
                    if "?" in sub_title_text: 
                        continue

                    context = extract_dense_context(clean_content)
                    new_node = {
                        "id": sub_node_id,
                        "title": full_sub_title[:100],
                        "label": "Topic",     # <--- STANDARD LABEL
                        "file_source": filename,
                        "page": page_num + 1,
                        "definition": context["definition"],
                        "key_points": context["key_points"]
                    }
                    
                    # Only add real topics to the Chapter Summary
                    if context["definition"]:
                        subtopic_summaries.append(f"{full_sub_title}: {context['definition'][:80]}...")

                nodes.append(new_node)
                
                # Relationship
                relationships.append({
                    "source": chapter_id,
                    "target": sub_node_id,
                    "relation": "HAS_PART" # or "HAS_EXERCISE" if you want distinctive edges
                })

        doc.close()

        # Update Chapter Key Points with subtopic summaries
        if subtopic_summaries:
            chapter_context["key_points"] = chapter_context["key_points"][:3] + subtopic_summaries[:5]

        # Add Chapter Node
        nodes.append({
            "id": chapter_id,
            "title": title_clean,
            "label": "Chapter",
            "file_source": filename,
            "page": 1,
            "definition": chapter_context["definition"],
            "key_points": chapter_context["key_points"]
        })

        # Sequence Link
        if previous_chapter_id:
            relationships.append({
                "source": previous_chapter_id,
                "target": chapter_id,
                "relation": "REQUIRES"
            })
        previous_chapter_id = chapter_id

    return nodes, relationships

if __name__ == "__main__":
    nodes, edges = parse_split_files(INPUT_FOLDER)
    
    if nodes:
        output = {"nodes": nodes, "relationships": edges}
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"\n✅ Success! Parsed {len(nodes)} nodes.")
        print(f"📄 Saved to {OUTPUT_JSON}")
    else:
        print("⚠️ No data found.")