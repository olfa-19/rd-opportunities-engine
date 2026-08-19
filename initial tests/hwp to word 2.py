import os
import re
import zlib
import struct
import olefile
from docx import Document

ILLEGAL_XML_CHARS = re.compile(
    r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f\ud800-\udfff\ufeff\ufffe\uffff]'
)

def clean_text_for_xml(text):
    if not text:
        return ""
    return ILLEGAL_XML_CHARS.sub('', text)

def parse_hwp_record_text(data):
    """Parses raw binary HWP records and isolates text strings."""
    extracted_paragraphs = []
    size = len(data)
    i = 0
    while i < size:
        if i + 4 > size:
            break
        header = struct.unpack_from("<I", data, i)[0]
        rec_type = header & 0x3FF           
        rec_len = (header >> 20) & 0xFFF    
        i += 4
        if rec_len == 0xFFF:
            if i + 4 > size:
                break
            rec_len = struct.unpack_from("<I", data, i)[0]
            i += 4
        if i + rec_len > size:
            break
        record_payload = data[i:i+rec_len]
        i += rec_len
        if rec_type == 67: # HWPTAG_PARA_TEXT
            try:
                text_block = record_payload.decode('utf-16le', errors='ignore')
                cleaned_line = "".join(ch for ch in text_block if ord(ch) >= 32 and ord(ch) != 0x3000)
                if cleaned_line.strip():
                    extracted_paragraphs.append(cleaned_line.strip())
            except Exception:
                continue
    return extracted_paragraphs

def extract_hwp_content_and_images(hwp_path, docx_path, images_dir):
    if not os.path.exists(hwp_path):
        print(f"Error: File '{hwp_path}' not found.")
        return

    doc = Document()
    os.makedirs(images_dir, exist_ok=True)
    
    try:
        hwp = olefile.OleFileIO(hwp_path)
        dirs = hwp.listdir()
        
        # --- 1. EXTRACT TEXT LAYOUT ---
        sections = [d for d in dirs if 'BodyText' in d and any('Section' in part for part in d)]
        print(f"Parsing {len(sections)} text section(s)...")
        
        for section in sections:
            stream_path = "/".join(section)
            stream_data = hwp.openstream(stream_path).read()
            try:
                decompressed_data = zlib.decompress(stream_data, -15)
            except zlib.error:
                try:
                    decompressed_data = zlib.decompress(stream_data)
                except Exception:
                    decompressed_data = stream_data

            paragraphs = parse_hwp_record_text(decompressed_data)
            for para in paragraphs:
                xml_safe_line = clean_text_for_xml(para)
                if xml_safe_line.strip():
                    doc.add_paragraph(xml_safe_line)
                    
        doc.save(docx_path)
        print(f"🎉 Text compiled successfully: {docx_path}")

        # --- 2. EXTRACT GRAPHICS & IMAGES ---
        # Look inside BinData directory where HWP stores all illustrations/graphs
        bindata_streams = [d for d in dirs if 'BinData' in d]
        if bindata_streams:
            print(f"Found {len(bindata_streams)} media/graph objects embedded. Extracting files...")
            for b_stream in bindata_streams:
                stream_path = "/".join(b_stream)
                raw_media_data = hwp.openstream(stream_path).read()
                
                # Check for extensions based on the hex signature of the files
                file_ext = ".bin"
                if raw_media_data.startswith(b'\x89PNG\r\n\x1a\n'):
                    file_ext = ".png"
                elif raw_media_data.startswith(b'\xff\xd8\xff'):
                    file_ext = ".jpg"
                elif raw_media_data.startswith(b'GIF89a') or raw_media_data.startswith(b'GIF87a'):
                    file_ext = ".gif"
                
                filename = b_stream[-1] + file_ext
                save_path = os.path.join(images_dir, filename)
                
                with open(save_path, 'wb') as img_out:
                    img_out.write(raw_media_data)
            print(f"📸 Visual elements extracted successfully to folder:\n--> {images_dir}")
        else:
            print("No embedded graphics folder found inside this HWP file structural layout.")

    except Exception as e:
        print(f"An unexpected parsing error occurred: {e}")

# ==============================================================================
# AUTOMATIC PATH CONFIGURATION FOR MACBOOK PRO
# ==============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))

# ⚠️ CHANGE 'document.hwp' to your exact filename if it is named something else
hwp_filename = "document.hwp" 
docx_filename = hwp_filename.replace(".hwp", ".docx")
images_folder_name = "extracted_images"

hwp_input_path = os.path.join(script_dir, hwp_filename)
docx_output_path = os.path.join(script_dir, docx_filename)
images_output_dir = os.path.join(script_dir, images_folder_name)

# Run the complete parser loop
extract_hwp_content_and_images(hwp_input_path, docx_output_path, images_output_dir)
