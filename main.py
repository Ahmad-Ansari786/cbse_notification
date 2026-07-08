import os
import json
import requests
from bs4 import BeautifulSoup
import boto3
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from urllib.parse import urljoin

# ----------------- Configuration ----------------- #
# Cloudflare R2 Setup (Using AWS Boto3)
s3 = boto3.client(
    service_name='s3',
    endpoint_url=os.environ['R2_ENDPOINT_URL'],
    aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
    aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY']
)
R2_BUCKET = os.environ['R2_BUCKET_NAME']

# Firebase Firestore Setup
firebase_creds_json = json.loads(os.environ['FIREBASE_CREDENTIALS'])
cred = credentials.Certificate(firebase_creds_json)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Gemini API Setup
genai.configure(api_key=os.environ['GEMINI_API_KEY'])
model = genai.GenerativeModel('gemini-1.5-flash')

# Base URL for relative links
BASE_URL = "https://www.cbse.gov.in/cbsenew/"

# ----------------- Functions ----------------- #

def upload_to_r2(file_content, filename, content_type):
    """Uploads file bytes to Cloudflare R2 and returns the public URL"""
    try:
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=filename,
            Body=file_content,
            ContentType=content_type
        )
        # Assuming you have a custom domain mapped to R2, otherwise construct the URL based on your setup
        return f"https://your-r2-public-domain.com/{filename}"
    except Exception as e:
        print(f"Error uploading {filename}: {e}")
        return None

def analyze_with_gemini(text_context):
    """Uses Gemini API to extract structured details from the link context"""
    prompt = f"""
    Analyze the following CBSE update and extract the details in JSON format:
    Text: {text_context}
    
    Format required:
    {{
        "title": "Main subject of the notice",
        "date": "Date mentioned (if any)",
        "summary": "A 2-line brief explanation of what this document/portal is for"
    }}
    Return ONLY valid JSON.
    """
    try:
        response = model.generate_content(prompt)
        # Clean the response to parse JSON safely
        clean_json = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(clean_json)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return {"title": text_context, "summary": "Failed to analyze."}

def process_links():
    # Load the HTML (For automation, you'd fetch the live URL using requests.get)
    # response = requests.get('https://www.cbse.gov.in/cbsenew/cbse.html')
    # soup = BeautifulSoup(response.text, 'html.parser')
    
    # Using a local file for demonstration based on your prompt
    with open('CBSE.html', 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    # Find the specific unordered list (ul.list)
    ul_element = soup.find('ul', class_='list')
    if not ul_element:
        print("UL element not found.")
        return

    # Extract all anchor tags
    links = ul_element.find_all('a')
    
    for a_tag in links:
        href = a_tag.get('href')
        if not href:
            continue
            
        full_url = urljoin(BASE_URL, href)
        link_text = a_tag.get_text(strip=True)
        
        # Categorize File Type
        file_type = "webportal"
        content_type = "text/html"
        if href.endswith('.pdf'):
            file_type = "document"
            content_type = "application/pdf"
        elif href.endswith(('.jpg', '.jpeg', '.png', '.JPG')):
            file_type = "image"
            content_type = "image/jpeg"

        print(f"Processing: {link_text} ({file_type})")
        
        # 1. Download Content & Upload to R2 (Skip downloading heavy portals, just save the link)
        r2_url = full_url
        if file_type in ["document", "image"]:
            try:
                file_response = requests.get(full_url)
                if file_response.status_code == 200:
                    filename = href.split('/')[-1]
                    r2_url = upload_to_r2(file_response.content, filename, content_type)
            except Exception as e:
                print(f"Download failed for {full_url}: {e}")

        # 2. Extract Details via Gemini API
        gemini_details = analyze_with_gemini(link_text)

        # 3. Save to Firestore
        doc_data = {
            "original_url": full_url,
            "r2_url": r2_url,
            "category": file_type,
            "title": gemini_details.get("title", link_text),
            "date": gemini_details.get("date", "Not Specified"),
            "summary": gemini_details.get("summary", ""),
            "timestamp": firestore.SERVER_TIMESTAMP
        }
        
        db.collection("cbse_updates").add(doc_data)
        print(f"Saved to Firestore: {doc_data['title']}\n")

if __name__ == "__main__":
    process_links()
