from flask import Flask, render_template_string, request
import os
from werkzeug.utils import secure_filename
import google.generativeai as genai
import json
import re
import time
import random
from googlesearch import search
import PyPDF2
from pptx import Presentation

# --- Flask App Setup ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- HTML Template ---
HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>Strategic Writing Assistant</title>
    <style>
      body { font-family: sans-serif; margin: 2em; }
      textarea { width: 100%; height: 100px; }
      .results { white-space: pre-wrap; background-color: #f4f4f4; padding: 1em; border: 1px solid #ddd; }
    </style>
  </head>
  <body>
    <h1>Strategic Writing Assistant</h1>
    <form method="post" enctype="multipart/form-data">
      <h2>1. Upload Your Documents</h2>
      <p>Select your PDF, TXT, and PowerPoint files.</p>
      <input type="file" name="files" multiple>

      <h2>2. Application Context</h2>
      <p>Paste the grant/accelerator description, focus areas, or mission.</p>
      <textarea name="grant_context"></textarea>

      <h2>3. Persona & Tone</h2>
      <p>Describe the ideal tone for this application (e.g., "Ambitious, data-driven founder").</p>
      <textarea name="persona"></textarea>

      <h2>4. Questions</h2>
      <p>Enter each question on a new line.</p>
      <textarea name="questions"></textarea>

      <br><br>
      <button type="submit">Generate Answers</button>
    </form>

    {% if results %}
      <h2>Generated Answers</h2>
      <div class="results">
        {% for result in results %}
          <p>{{ result }}</p>
          <hr>
        {% endfor %}
      </div>
    {% endif %}
  </body>
</html>
"""

# --- Core RAG Logic (from rag_core.py) ---

# --- CONFIGURATION ---
API_KEY = "AIzaSyCWrbfoa0ASrkhpu71XVZl2B_xVmuo-yQE"
genai.configure(api_key=API_KEY)

# --- File Reading Functions ---
def read_txt(file_path):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()

def read_pdf(file_path):
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

METRICS = { "funding_raised_usd": 250000, "seed_round_target_usd": 1500000 }

def make_api_call(payload, system_prompt_text, retries=3):
    model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=system_prompt_text)
    for attempt in range(retries):
        try:
            time.sleep(2)
            response = model.generate_content(payload['contents'])
            return response.text
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep(60 + random.uniform(1, 5))
            else:
                return f"An error occurred: {e}"
    return "Error: Failed after max retries."

def searcher_ai(user_query, grant_context, all_questions):
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
    system_prompt = "You are an intelligent document routing assistant..."
    descriptions_text = "\n".join([f"{num}: {desc}" for num, desc in document_descriptions.items()])
    full_prompt = f"... AVAILABLE INTERNAL DOCUMENTS ---\n{descriptions_text}\n\n..."
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    response_text = make_api_call(payload, system_prompt)
    selected_ids = re.findall(r'\d+', response_text)
    valid_ids = [s_id for s_id in selected_ids if s_id in DOCUMENTS]
    return valid_ids if valid_ids else list(DOCUMENTS.keys())

def generate_final_answer(user_query, document_context, grant_context, persona, metrics, searcher_results):
    system_prompt = "You are a world-class AI writer..."
    full_prompt = f"... QUESTION TO ANSWER ---\n'{user_query}'"
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    return make_api_call(payload, system_prompt)

def process_request(upload_dir, grant_context, persona, questions_text):
    if not API_KEY or "AIzaSy" not in API_KEY:
        return ["FATAL ERROR: API_KEY is not set correctly."]

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
        # ... (rest of the processing logic)

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

# --- Flask Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    results = None
    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')
        for file in uploaded_files:
            if file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        grant_context = request.form.get('grant_context', 'A general inquiry.')
        persona = request.form.get('persona', 'A professional representative.')
        questions = request.form.get('questions', '')

        results = process_request(
            upload_dir=app.config['UPLOAD_FOLDER'],
            grant_context=grant_context,
            persona=persona,
            questions_text=questions
        )

        for file in uploaded_files:
             if file.filename != '':
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename)))

    return render_template_string(HTML_TEMPLATE, results=results)

if __name__ == '__main__':
    app.run(debug=True, port=8080)
