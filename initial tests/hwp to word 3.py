import os
import time
import requests

# ⚠️ PLACE YOUR VALID CLOUDCONVERT API KEY HERE
# Get your token at https://cloudconvert.com
API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIxIiwianRpIjoiZmQ5MTE4MjgxNjllYmRmMTdmNDg5OGQ5YjE4MTA2YjZjZGVjNmU2Y2VhNWNiNzExMmQ3YTljNDRhMGVmN2Y0NDliZTllNGFlNzEyZTkyODEiLCJpYXQiOjE3ODYwNjc5MzQuNjU1MTczLCJuYmYiOjE3ODYwNjc5MzQuNjU1MTc1LCJleHAiOjQ5NDE3NDE1MzQuNjQ4ODk2LCJzdWIiOiI3NjU0NjE2NyIsInNjb3BlcyI6W119.BA45Qgh7Wn4N5MZhWj4GB6kLa7thYVMaKrGha_buvV7oY_Jl1k0LspCAmnZJV26e-Is6BT8Whf7kG_PYi_19lDkH6DpdQ8ZqElvraF9fhsUTR5ZlEms5jolJjDlZGZSxf8FWjZD-9GGlPJGa7WR4F_VKnaUrtGrIw-wbgCtUXjU3n3RIWsizWn-dp_0QTbVYvZNEjnDjW77dGnN8YuuLlXJGWDP3_2r-72gkNfsmIwYSjD_i_oaSSILTwpfo-hPdSK9QBfwh_MLJs5O98_mHwnXG2a4bNXaMM3DAqv4p9_6iYPYhDVAhxmT6ycNY1z9G-NsL3JMKsCFU6PaYHF1HvR_1kbyO3D5MDqJ19K6wGP-VC3c7_sCOAUqXL1nOU8pVCw2v0in-xfwJEpd3miJquAqFfX2Ds-mxfY-w9HfrKuuHIDYFb59lOPD-k3Rj1pBGUfGoVfQevpmz1Xn-u-imzY303gh1b1DPzVwUjPp4fMjX2rKbPCgPKVeHCFJ0_NpjOaE98Slz3NZVbEZnVja4mk19L5EvXMZXrwu2YUpU8y8CMiD_J9E-rfNkKjdphFKuDY25tt5Jj4epsbqx0zhQGc5cYZHbFKLsUq-edgGiu6rn9jcQE_FQSl253fX9UtJ71j2vYl25NtweWzc94VHXXwf9Kn0OdUrbDOuqFPc6jdY"

def cloud_convert_hwp(hwp_path, docx_path):
    if not os.path.exists(hwp_path):
        print(f"Error: File '{hwp_path}' not found.")
        return

    if API_KEY == "YOUR_CLOUDCONVERT_API_KEY" or not API_KEY.strip():
        print("❌ Error: Please provide your CloudConvert API key.")
        return

    headers = {"Authorization": f"Bearer {API_KEY.strip()}"}
    
    payload = {
        "tasks": {
            "import-my-file": {"operation": "import/upload"},
            "convert-my-file": {
                "operation": "convert",
                "input": "import-my-file",
                "input_format": "hwp",
                "output_format": "docx"
            },
            "export-my-file": {"operation": "export/url", "input": "convert-my-file"}
        }
    }
    
    print("Initiating CloudConvert structure processing engine...")
    try:
        # Correct API v2 endpoints used to prevent 405 error
        response = requests.post("https://cloudconvert.com", json=payload, headers=headers)
        
        # FIXED: Completed the syntax comparison expression
        if response.status_code not in (200, 201):
            print(f"\n❌ CloudConvert API returned error status ({response.status_code}):")
            print(response.text)
            return

        res_json = response.json()
        upload_task = next(t for t in res_json['data']['tasks'] if t['name'] == 'import-my-file')
        upload_url = upload_task['result']['form']['url']
        upload_data = upload_task['result']['form']['params']
        
        print("Uploading .hwp document stream...")
        with open(hwp_path, 'rb') as f:
            requests.post(upload_url, data=upload_data, files={'file': f})
            
        job_id = res_json['data']['id']
        job_url = f"https://cloudconvert.com/{job_id}"
        print("Processing layouts and tables remotely...")
        
        while True:
            status_resp = requests.get(job_url, headers=headers).json()
            job_status = status_resp['data']['status']
            
            if job_status == 'finished':
                export_task = next(t for t in status_resp['data']['tasks'] if t['name'] == 'export-my-file')
                file_url = export_task['result']['files']['url']
                
                print("Downloading rendered .docx structure to your Mac...")
                docx_bytes = requests.get(file_url).content
                with open(docx_path, 'wb') as out:
                    out.write(docx_bytes)
                print(f"\n🎉 Success! Saved to: {docx_path}")
                break
            elif job_status in ['error', 'failed']:
                print(f"Cloud engine failed: {status_resp['data'].get('message')}")
                break
            time.sleep(2)
            
    except Exception as e:
        print(f"Pipeline crashed: {e}")

# ==============================================================================
# AUTOMATIC PATH CONFIGURATION FOR MACBOOK PRO
# ==============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))

hwp_filename = "document.hwp" 
docx_filename = hwp_filename.replace(".hwp", ".docx")

hwp_input_path = os.path.join(script_dir, hwp_filename)
docx_output_path = os.path.join(script_dir, docx_filename)

cloud_convert_hwp(hwp_input_path, docx_output_path)
