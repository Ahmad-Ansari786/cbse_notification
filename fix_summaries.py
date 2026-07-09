import os
import sys
import time
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# =====================================================================
# ⚙️ CONFIGURATION & SECRETS
# =====================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("❌ Error: GEMINI_API_KEY is missing!")
    sys.exit(1)

FIREBASE_SERVICE_ACCOUNT_JSON = "serviceAccountKey.json"

# =====================================================================
# 🚀 INITIALIZATION
# =====================================================================
print("🔄 Initializing Firebase connection for cleanup...")

if not os.path.exists(FIREBASE_SERVICE_ACCOUNT_JSON):
    print(f"❌ Error: '{FIREBASE_SERVICE_ACCOUNT_JSON}' not found!")
    sys.exit(1)

# Initialize Firebase (agar pehle se initialize nahi hai)
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_JSON)
    firebase_admin.initialize_app(cred)

db = firestore.client()
firestore_collection = db.collection("cbse_live_notices")

# =====================================================================
# 🤖 GEMINI AI SUMMARY GENERATOR
# =====================================================================
def generate_ai_summary(bytes_payload, title):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = (
            f"Notice Title: '{title}'\n"
            "Task: Please read the entire attached document thoroughly from start to finish. "
            "Carefully analyze all the pages, extract key information such as important dates, deadlines, "
            "rules, and the main purpose of the notice. "
            "After reading the complete document, provide a clear, highly accurate, and easy-to-understand "
            "4-5 line (bullet point) summary in Hindi(script also). If more important then add more lines."
        )
        response = model.generate_content([
            prompt,
            {"mime_type": "application/pdf", "data": bytes_payload}
        ])
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ Google AI Summary Error: {e}")
        return "Summary generation failed."

# =====================================================================
# 🛠️ MAIN CLEANUP LOGIC
# =====================================================================
def fix_missing_summaries():
    print("\n🔍 Scanning database for missing or failed summaries...")
    
    # Un documents ko fetch karo jahan summary fail hui thi aur wo PDF hain
    failed_docs = firestore_collection.where("summary", "==", "Summary generation failed.").stream()
    
    count = 0
    for doc in failed_docs:
        doc_data = doc.to_dict()
        doc_id = doc.id
        title = doc_data.get("title", "Unknown Title")
        pdf_url = doc_data.get("serverFileUrl", "")
        is_pdf = doc_data.get("isPdf", False)

        # Webportals me AI summary nahi hoti, unhe skip karo
        if not is_pdf or not pdf_url:
            continue
            
        print("-" * 50)
        print(f"🔄 Fixing: {title[:50]}...")
        
        try:
            print(f"📥 Downloading PDF from R2: {pdf_url}")
            # R2 se directly file download kar rahe hain
            response = requests.get(pdf_url, timeout=15)
            
            if response.status_code == 200:
                print("⏳ Throttling API (5 seconds)...")
                time.sleep(5)
                
                print("🧠 Generating New Summary...")
                new_summary = generate_ai_summary(response.content, title)
                
                if new_summary != "Summary generation failed.":
                    # Firestore me update command chalao
                    firestore_collection.document(doc_id).update({
                        "summary": new_summary
                    })
                    print("✅ Successfully updated in database!")
                    count += 1
                else:
                    print("❌ Still failing to generate summary for this document.")
            else:
                print(f"❌ Failed to download file. Status Code: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error processing document {doc_id}: {e}")

    print("\n" + "=" * 50)
    print(f"🏁 CLEANUP COMPLETE | Successfully fixed: {count} summaries.")
    print("=" * 50)

if __name__ == "__main__":
    fix_missing_summaries()
