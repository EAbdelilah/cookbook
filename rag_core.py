import google.generativeai as genai
import json
import re
import os
import time
import random
from googlesearch import search
import PyPDF2
from pptx import Presentation

# --- CONFIGURATION ---
# NOTE: Set your API Key here.
API_KEY = "AIzaSyCWrbfoa0ASrkhpu71XVZl2B_xVmuo-yQE"  # <--- PASTE YOUR GEMINI API KEY HERE
genai.configure(api_key=API_KEY)


# --- File Reading Functions ---

def read_txt(file_path):
    """Reads text from a .txt file."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()

def read_pdf(file_path):
    """Reads text from a .pdf file."""
    text = ""
    try:
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f, strict=False)
            for page in reader.pages:
                text += page.extract_text() or ""
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
    return text

def read_pptx(file_path):
    """Reads text from a .pptx file."""
    text = ""
    try:
        prs = Presentation(file_path)
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text += shape.text + "\n"
    except Exception as e:
        print(f"Error reading PPTX {file_path}: {e}")
    return text

# --- Document Handling ---

DOCUMENTS = {}
DOCUMENT_DESCRIPTIONS = {}

def load_documents_from_directory(dir_path):
    """Loads all supported documents from a directory and returns the populated dictionaries."""
    global DOCUMENTS, DOCUMENT_DESCRIPTIONS
    DOCUMENTS = {}
    DOCUMENT_DESCRIPTIONS = {}
    doc_id = 1
    for filename in os.listdir(dir_path):
        file_path = os.path.join(dir_path, filename)
        content = ""
        if filename.endswith(".txt"):
            content = read_txt(file_path)
        elif filename.endswith(".pdf"):
            content = read_pdf(file_path)
        elif filename.endswith(".pptx"):
            content = read_pptx(file_path)

        if content:
            doc_key = str(doc_id)
            doc_name = os.path.splitext(filename)[0].upper()
            DOCUMENTS[doc_key] = (doc_name, content)
            DOCUMENT_DESCRIPTIONS[doc_key] = f"{doc_name}: {content[:100]}..."
            doc_id += 1

    if not DOCUMENTS:
        print(f"[Warning] No documents found in '{dir_path}'.")

# --- The Metrics Vault ---
METRICS = {
    "funding_raised_usd": 250000,
    "seed_round_target_usd": 1500000,
    # ... (rest of the metrics)
}

# --- CORE API COMMUNICATION ---
def make_api_call(payload, system_prompt_text, retries=3):
    """Makes a single API call to Gemini with retry logic."""
    model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_prompt_text)
    for attempt in range(retries):
        try:
            time.sleep(2) # Rate limiting
            response = model.generate_content(payload['contents'])
            return response.text
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep(60 + random.uniform(1, 5))
            else:
                return f"An error occurred: {e}"
    return "Error: Failed after max retries."

# --- AI CHAIN ---
def searcher_ai(user_query, grant_context, all_questions):
    """Step 0: The "Searcher" AI."""
    system_prompt = "You are an expert researcher..."
    search_query = f"{user_query} {grant_context} {all_questions}"
    try:
        search_results = search(search_query, num_results=5)
        formatted_results = "\n".join([f"- {result}" for result in search_results])
        summary_prompt = f"Please summarize... Search Results:\n{formatted_results}"
        payload = {"contents": [{"parts": [{"text": summary_prompt}]}]}
        return make_api_call(payload, system_prompt)
    except Exception as e:
        return f"An error during web search: {e}"

def select_best_documents(user_query, document_descriptions, searcher_results):
    """Step 1: The "Librarian" AI."""
    system_prompt = "You are an intelligent document routing assistant..."
    descriptions_text = "\n".join([f"{num}: {desc}" for num, desc in document_descriptions.items()])
    full_prompt = f"... AVAILABLE INTERNAL DOCUMENTS ---\n{descriptions_text}\n\n..."
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    response_text = make_api_call(payload, system_prompt)
    selected_ids = re.findall(r'\d+', response_text)
    valid_ids = [s_id for s_id in selected_ids if s_id in DOCUMENTS]
    return valid_ids if valid_ids else list(DOCUMENTS.keys())

def generate_final_answer(user_query, document_context, grant_context, persona, metrics, searcher_results):
    """Generates the final answer."""
    system_prompt = "You are a world-class AI writer..."
    full_prompt = f"... QUESTION TO ANSWER ---\n'{user_query}'"
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    return make_api_call(payload, system_prompt)

# --- MAIN PROCESSING FUNCTION ---
def process_request(upload_dir, grant_context, persona, questions_text):
    """Main function to run the RAG process."""
    if not API_KEY or "AIzaSy" not in API_KEY:
        return ["FATAL ERROR: API_KEY is not set correctly in rag_core.py."]

    load_documents_from_directory(upload_dir)
    if not DOCUMENTS:
        return ["[Error] No documents were successfully processed from the uploads directory."]

    questions = [q.strip() for q in questions_text.split('\n') if q.strip()]
    if not questions:
        return ["[Error] No questions provided."]

    final_answers = []
    sharia_keywords = ["sharia", "halal", "islamic", "riba", "muslim"]

    for i, user_question in enumerate(questions):
        answer_block = f"===== PROCESSING QUESTION {i+1}/{len(questions)} =====\n"
        answer_block += f"QUESTION: {user_question}\n\n"

        adapted_persona = persona
        if any(keyword in user_question.lower() for keyword in sharia_keywords):
            adapted_persona += "\n\n--- SPECIAL INSTRUCTION ---\n...prioritize Sharia-compliant terms..."
        else:
            adapted_persona += "\n\n--- SPECIAL INSTRUCTION ---\n...use secular terms like 'ethical finance'..."

        searcher_results = searcher_ai(user_question, grant_context, questions)
        selected_doc_ids = select_best_documents(user_question, DOCUMENT_DESCRIPTIONS, searcher_results)

        combined_context = ""
        selected_names = []
        for doc_id in selected_doc_ids:
            if doc_id in DOCUMENTS:
                doc_name, doc_content = DOCUMENTS[doc_id]
                selected_names.append(doc_name)
                combined_context += f"\n--- DOC: {doc_name} ---\n{doc_content}\n"

        if not combined_context:
            final_answers.append(answer_block + "[Error] Could not build context from selected documents.")
            continue

        answer_block += f"[Info] Using knowledge from: {', '.join(selected_names)}\n\n"

        final_answer = generate_final_answer(user_question, combined_context, grant_context, adapted_persona, METRICS, searcher_results)

        answer_block += "===== FINAL RECOMMENDED ANSWER =====\n"
        answer_block += final_answer
        final_answers.append(answer_block)

    return final_answers