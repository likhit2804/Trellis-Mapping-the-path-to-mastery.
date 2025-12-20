import json
import statistics
from collections import Counter

# ==========================================
# CONFIGURATION
# ==========================================
JSON_FILE = "curriculum1.json"
MISSING_MARKER = "Content not available"

def analyze_curriculum(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File '{file_path}' not found.")
        return

    nodes = data.get("nodes", [])
    if not nodes:
        print("⚠️ No nodes found in JSON.")
        return

    # --- 1. DATA COLLECTION ---
    total_nodes = len(nodes)
    chapters = [n for n in nodes if n.get("label") == "Chapter"]
    topics = [n for n in nodes if n.get("label") == "Topic"]
    
    # Missing Content Analysis
    missing_def_nodes = [n for n in nodes if MISSING_MARKER in n.get("definition", "")]
    empty_keypoints_nodes = [n for n in nodes if not n.get("key_points")]
    
    # Text Quality Metrics
    def_lengths = [len(n.get("definition", "")) for n in nodes]
    kp_counts = [len(n.get("key_points", [])) for n in nodes]
    title_lengths = [len(n.get("title", "")) for n in nodes]

    # --- 2. DUPLICATE DETECTION ---
    # Detect if multiple nodes have the exact same title (parsing error)
    title_counts = Counter(n["title"] for n in nodes)
    duplicates = {k: v for k, v in title_counts.items() if v > 1}

    # --- 3. PRINT REPORT ---
    print(f"\n📊 PARSER EVALUATION REPORT: {file_path}")
    print("=" * 60)
    
    print(f"\n1️⃣  STRUCTURAL BALANCE")
    print(f"   - Total Nodes:      {total_nodes}")
    print(f"   - Chapters:         {len(chapters)}")
    print(f"   - Topics:           {len(topics)}")
    if chapters:
        print(f"   - Avg Topics/Chap:  {len(topics) / len(chapters):.1f}")

    print(f"\n2️⃣  CONTENT QUALITY (Efficiency Metrics)")
    
    # Metric: Content Availability Rate
    success_rate = ((total_nodes - len(missing_def_nodes)) / total_nodes) * 100
    print(f"   - ✅ Content Success Rate:   {success_rate:.1f}%")
    print(f"   - ❌ Missing Definitions:    {len(missing_def_nodes)} nodes ({len(missing_def_nodes)/total_nodes:.1%} of total)")
    print(f"   - ⚠️ Empty Key Points:       {len(empty_keypoints_nodes)} nodes")

    # Metric: Richness
    avg_def_len = statistics.mean(def_lengths) if def_lengths else 0
    avg_kp = statistics.mean(kp_counts) if kp_counts else 0
    print(f"   - 📏 Avg Definition Length:  {avg_def_len:.0f} chars")
    print(f"   - 📝 Avg Key Points/Node:    {avg_kp:.1f}")

    print(f"\n3️⃣  ANOMALY DETECTION")
    
    # Check for likely regex failures (titles that are whole paragraphs)
    long_titles = [n for n in nodes if len(n["title"]) > 150]
    if long_titles:
        print(f"   - 🚩 Suspiciously Long Titles (>150 chars): {len(long_titles)}")
        print(f"        Example: \"{long_titles[0]['title'][:60]}...\"")
    else:
        print("   - ✅ Titles look normal length.")

    # Check for duplicates
    if duplicates:
        print(f"   - 🚩 Duplicate Titles Found: {len(duplicates)}")
        print(f"        Example: \"{list(duplicates.keys())[0]}\" (x{list(duplicates.values())[0]})")
    else:
        print("   - ✅ No duplicate titles found.")

    print("\n" + "=" * 60)
    
    # --- 4. DETAILED LIST OF FAILURES ---
    if missing_def_nodes:
        print("\n🔍 NODES WITH MISSING CONTENT (First 5):")
        for n in missing_def_nodes[:5]:
            print(f"   • [{n['id']}] {n['title']} (Page {n.get('page', '?')})")
        
        print(f"\n   ... check 'missing_content_log.json' for the full list.")
        
        # Save failure log
        with open("missing_content_log.json", "w", encoding="utf-8") as f:
            json.dump([
                {"id": n["id"], "title": n["title"], "page": n.get("page"), "file": n.get("file_source")} 
                for n in missing_def_nodes
            ], f, indent=2)

if __name__ == "__main__":
    analyze_curriculum(JSON_FILE)