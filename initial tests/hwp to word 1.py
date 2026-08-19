import os
import subprocess

def convert_hwp_to_docx_libreoffice(hwp_path, docx_path):
    if not os.path.exists(hwp_path):
        print(f"Error: File '{hwp_path}' not found.")
        return

    # Standard default installation path for LibreOffice on macOS
    libreoffice_path = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    
    if not os.path.exists(libreoffice_path):
        print("Error: LibreOffice is not installed or not in the default Applications folder.")
        print("Please install it via: brew install --cask libreoffice")
        return

    output_dir = os.path.dirname(docx_path)

    # LibreOffice CLI conversion arguments
    cmd = [
        libreoffice_path,
        "--headless",
        "--convert-to", "docx",
        "--outdir", output_dir,
        hwp_path
    ]

    print("Running layout conversion via LibreOffice headless container...")
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print(f"🎉 Success! Converted document structure layout to folder: {output_dir}")
        else:
            print(f"LibreOffice layout failure: {result.stderr}")
    except Exception as e:
        print(f"Failed to execute LibreOffice system wrapper: {e}")

# ==============================================================================
# AUTOMATIC PATH CONFIGURATION
# ==============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))

hwp_filename = "document.hwp" 
docx_filename = hwp_filename.replace(".hwp", ".docx")

hwp_input_path = os.path.join(script_dir, hwp_filename)
docx_output_path = os.path.join(script_dir, docx_filename)

convert_hwp_to_docx_libreoffice(hwp_input_path, docx_output_path)
