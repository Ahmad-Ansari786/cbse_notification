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
# 🤖 PRO-LEVEL GEMINI AI SUMMARY GENERATOR
# =====================================================================
def generate_ai_summary(bytes_payload, mime_type, title):
    if not GEMINI_API_KEY:
        return "AI Summary unavailable (No API Key)"
    
    # Agar PDF properly download nahi hui hai (empty payload)
    if not bytes_payload or len(bytes_payload) < 100:
        print("❌ Error: PDF payload is empty or too small. Check your R2 URL/Permissions.")
        return "Summary generation failed due to invalid document."
        
    try:
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        
        # Professional Prompt Engineering
        prompt = (
            f"Notice Title: '{title}'\n\n"
            "You are an expert administrative assistant for the CBSE Board. "
            "Read the attached official document carefully and extract the core information. "
            "Provide a highly professional, structured summary in Hindi (Devanagari script). "
            "Use formal and respectful language. Do not add any extra conversational text.\n\n"
            "Format your response EXACTLY like this:\n\n"
            "📌 **मुख्य विषय (Main Subject):** [Provide a 1-line crisp subject]\n"
            "📅 **महत्वपूर्ण तिथियां (Key Dates):** [Extract any deadlines or event dates. If none, write 'कोई विशेष तिथि नहीं']\n"
            "📝 **संक्षिप्त विवरण (Summary):**\n"
            "• [Key Point 1]\n"
            "• [Key Point 2]\n"
            "• [Key Point 3]"
        )
        
        if mime_type in ['application/pdf', 'image/jpeg', 'image/png']:
            response = model.generate_content([
                prompt,
                {"mime_type": mime_type, "data": bytes_payload}
            ])
            return response.text.strip()
        else:
            return "Document format not supported for direct AI summary."
            
    except Exception as e:
        # Ye line exact error batayegi ki Gemini fail kyun ho raha hai
        print(f"\n⚠️ EXTREME ERROR IN GEMINI API: {str(e)}\n")
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
