import os
import sys
import time
import requests
from bs4 import BeautifulSoup
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

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT_JSON)
    firebase_admin.initialize_app(cred)

db = firestore.client()
firestore_collection = db.collection("live_notices")


# =====================================================================
# 🛠️ HELPER FUNCTIONS
# =====================================================================
def get_smart_content_type(url):
    extension = url.split('?')[0].split('.')[-1].lower()
    types_map = {
        'pdf': 'application/pdf',
        'jpeg': 'image/jpeg',
        'jpg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif'
    }
    return types_map.get(extension, 'application/octet-stream')

def extract_web_text(url):
    """Web portal se sirf text nikalne ka function"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Website se saara clean text nikalna
            text = soup.get_text(separator=' ', strip=True)
            return text
        return None
    except Exception as e:
        print(f"⚠️ Web scraping error: {e}")
        return None


# =====================================================================
# 🤖 GEMINI AI SUMMARY GENERATOR
# =====================================================================
def generate_ai_summary(payload, mime_type, title):
    if not payload:
        return "Summary generation failed due to invalid document."
        
    try:
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        
        prompt = (
            f"Notice Title: '{title}'\n\n"
            "Read the attached document or webpage content carefully and extract the core information. "
            "Provide a structured summary in Hindi (Devanagari script).\n\n"
            "Format your response EXACTLY like this:\n\n"
            "📌 **मुख्य विषय (Main Subject):** [Provide a 1-line crisp subject]\n"
            "📅 **महत्वपूर्ण तिथियां (Key Dates):** [Extract any deadlines or event dates. If none, write 'कोई विशेष तिथि नहीं']\n"
            "📝 **संक्षिप्त विवरण (Summary):**\n"
            "• [Key Point 1]\n"
            "• [Key Point 2]\n"
            "• [Key Point 3]"
        )
        
        # Agar file (PDF/Image) hai:
        if mime_type in ['application/pdf', 'image/jpeg', 'image/png']:
            response = model.generate_content([
                prompt,
                {"mime_type": mime_type, "data": payload}
            ])
            return response.text.strip()
            
        # Agar Web Portal ka scraped text hai:
        elif mime_type == 'text/plain':
            # Text prompt banakar limit kar diya taaki API overload na ho (15,000 characters)
            full_prompt = f"{prompt}\n\nWebpage Text Context:\n{payload[:15000]}"
            response = model.generate_content(full_prompt)
            return response.text.strip()
            
        else:
            return "Document format not supported for direct AI summary."
            
    except Exception as e:
        print(f"\n⚠️ GEMINI API ERROR: {str(e)}\n")
        return "Summary generation failed."


# =====================================================================
# 🛠️ MAIN CLEANUP LOGIC
# =====================================================================
def fix_missing_summaries():
    print("\n🔍 Scanning database for missing or failed summaries...")
    
# .stream() ki jagah .get() ka use karenge taaki saara data ek baar me aa jaye
    failed_docs = firestore_collection.where("summary", "==", "Summary generation failed.").get()
    
    count = 0
    for doc in failed_docs:
        doc_data = doc.to_dict()
        doc_id = doc.id
        title = doc_data.get("title", "Unknown Title")
        file_url = doc_data.get("serverFileUrl", "")
        is_webpage = doc_data.get("isWebpage", False)

        print("-" * 50)
        print(f"🔄 Fixing: {title[:50]}...")

        # 1. Agar Webportal hai: URL scrape karo aur text pass karo
        if is_webpage or not file_url.endswith(('.pdf', '.jpg', '.jpeg', '.png', '.gif')):
            print(f"🌐 Webportal Detected: {file_url}")
            print("📥 Scraping webpage content...")
            
            web_text = extract_web_text(file_url)
            
            if web_text:
                print("⏳ Throttling API (5 seconds)...")
                time.sleep(5)
                
                print("🧠 Generating AI Summary from webpage text...")
                new_summary = generate_ai_summary(web_text, 'text/plain', title)
            else:
                new_summary = "Portal link notice - please visit the portal for full details."
                
            if new_summary != "Summary generation failed." and "Summary generation failed" not in new_summary:
                firestore_collection.document(doc_id).update({"summary": new_summary})
                print("✅ Successfully updated in database!")
                count += 1
            else:
                print("❌ Failed to generate summary for webpage.")
            continue
            
        # 2. Agar File (PDF/Image) hai: Direct file download karke AI ko bhejo
        mime_type = get_smart_content_type(file_url)
        print(f"📥 Downloading File ({mime_type}) from R2: {file_url}")
        
        try:
            response = requests.get(file_url, timeout=15)
            
            if response.status_code == 200:
                print("⏳ Throttling API (5 seconds)...")
                time.sleep(5)
                
                print("🧠 Generating New AI Summary...")
                new_summary = generate_ai_summary(response.content, mime_type, title)
                
                if new_summary != "Summary generation failed." and "Summary generation failed" not in new_summary:
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
