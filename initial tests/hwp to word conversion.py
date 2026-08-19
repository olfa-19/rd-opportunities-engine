import os
import re
import zlib
import struct
import olefile
from docx import Document

# Safe regex filter to prevent Microsoft Word XML packaging faults
ILLEGAL_XML_CHARS = re.compile(
    r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f\ud800-\udfff\ufeff\ufffe\uffff]'
)

def clean_text_for_xml(text):
    if not text:
        return ""
    return ILLEGAL_XML_CHARS.sub('', text)

def parse_hwp_record_text(data):
    """Parses raw binary HWP records and safely isolates text strings."""
    extracted_paragraphs = []
    size = len(data)
    i = 0
    
    while i < size:
        if i + 4 > size:
            break
            
        # 1. Unpack the 4-byte HWP Record Header
        header = struct.unpack_from("<I", data, i)[0]
        rec_type = header & 0x3FF           # The first 10 bits define the Record Tag ID
        rec_len = (header >> 20) & 0xFFF    # The next 12 bits define the record length
        
        i += 4
        
        # Handle rare extended-length records (where length mask is 4095)
        if rec_len == 0xFFF:
            if i + 4 > size:
                break
            rec_len = struct.unpack_from("<I", data, i)[0]
            i += 4
            
        if i + rec_len > size:
            break
            
        # 2. Extract record body data payload
        record_payload = data[i:i+rec_len]
        i += rec_len
        
        # 3. TAG ID 67 is explicitly HWPTAG_PARA_TEXT (Actual Text Strings)
        if rec_type == 67:
            try:
                # Decode the text chunk as UTF-16
                text_block = record_payload.decode('utf-16le', errors='ignore')
                
                # Filter out HWP inline styling markers (inline codes like bold, sizes, etc.)
                cleaned_line = ""
                for ch in text_block:
                    # Keep valid characters, strip structural control tokens
                    if ord(ch) >= 32 and ord(ch) != 0x3000:  
                        cleaned_line += ch
                        
                if cleaned_line.strip():
                    extracted_paragraphs.append(cleaned_line.strip())
            except Exception:
                continue
                
    return extracted_paragraphs

def extract_hwp_text_to_docx(hwp_path, docx_path):
    if not os.path.exists(hwp_path):
        print(f"Error: File '{hwp_path}' not found.")
        return

    doc = Document()
    
    try:
        # Open HWP binary container
        hwp = olefile.OleFileIO(hwp_path)
        dirs = hwp.listdir()
        
        # Target the core body text segments
        sections = [d for d in dirs if 'BodyText' in d and any('Section' in part for part in d)]
        
        if not sections:
            print("No valid layout sections discovered in this file.")
            return

        print(f"Parsing structural binary code from {len(sections)} text section(s)...")
        
        for section in sections:
            stream_path = "/".join(section)
            stream_data = hwp.openstream(stream_path).read()
            
            # Decompress binary layout
            try:
                decompressed_data = zlib.decompress(stream_data, -15)
            except zlib.error:
                try:
                    decompressed_data = zlib.decompress(stream_data)
                except Exception:
                    decompressed_data = stream_data

            # Use our custom structural parser to isolate the true paragraph text
            paragraphs = parse_hwp_record_text(decompressed_data)
            
            for para in paragraphs:
                xml_safe_line = clean_text_for_xml(para)
                if xml_safe_line.strip():
                    doc.add_paragraph(xml_safe_line)

        doc.save(docx_path)
        print(f"\n🎉 Clean conversion complete! Saved to:\n--> {docx_path}")

    except Exception as e:
        print(f"An unexpected parsing error occurred: {e}")

# ==============================================================================
# AUTOMATIC PATH CONFIGURATION FOR MACBOOK PRO
# ==============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))

hwp_filename = "document.hwp" 
docx_filename = hwp_filename.replace(".hwp", ".docx")

hwp_input_path = os.path.join(script_dir, hwp_filename)
docx_output_path = os.path.join(script_dir, docx_filename)

extract_hwp_text_to_docx(hwp_input_path, docx_output_path)
