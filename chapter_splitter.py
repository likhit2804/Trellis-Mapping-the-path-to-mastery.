import fitz  # PyMuPDF
import os
import re

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def split_pdf_chapters_only(pdf_path, output_folder="Final_Chapters"):
    doc = fitz.open(pdf_path)
    toc = doc.get_toc()  # [[level, title, page_number], ...]
    total_pages = len(doc)
    
    if not toc:
        print("Error: No Table of Contents found.")
        return

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    print(f"Found {len(toc)} ToC entries. Filtering for 'Chapter'...")

    # We will collect valid chapters first to make logic easier
    valid_chapters = []
    
    for i, entry in enumerate(toc):
        level, title, start_page = entry
        
        # --- KEY FIX ---
        # Only accept entries that explicitly say "Chapter" or "Appendix"
        # We ignore "Part", "Index", "Preface" etc unless you add them.
        if "Chapter" in title or "Appendix" in title:
            valid_chapters.append({
                "title": title,
                "start_page": start_page,
                "index": i # Keep track of original index in TOC
            })

    # Now process only the valid chapters
    for i, chapter in enumerate(valid_chapters):
        start_page = chapter["start_page"]
        title = chapter["title"]
        
        # Determine End Page
        # Logic: The end page is (Start of NEXT valid chapter) - 1
        if i + 1 < len(valid_chapters):
            end_page = valid_chapters[i+1]["start_page"] - 1
        else:
            # If it's the last chapter, go to the very end of the book
            end_page = total_pages 
        
        # Handle Edge Case: Sometimes a "Bibliography" or "Index" comes after the last chapter
        # If you want to stop BEFORE the index, you'd need to check the original TOC again.
        # For now, this extends the last chapter to the end of the file.

        # Convert to 0-based for slicing
        p_start = start_page - 1
        p_end = end_page - 1 

        if p_start > p_end: 
            p_end = p_start # Safety fix

        # Create new PDF
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=p_start, to_page=p_end)
        
        clean_title = sanitize_filename(title)
        filename = f"{output_folder}/{i+1:02d}_{clean_title}.pdf"
        
        new_doc.save(filename)
        new_doc.close()
        
        print(f"Saved: {filename} (Pages {start_page}-{end_page})")

    print("\nSplitting complete!")



# --- USAGE ---
if __name__ == "__main__":
    pdf_file = "C:\\Users\\likhi\\OneDrive\\Pictures\\Desktop\\project\\OS_main.pdf"
    split_pdf_chapters_only(pdf_file)