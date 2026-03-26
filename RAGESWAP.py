from flask import Flask, render_template_string, request
import os
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types
import json
import re
import time
import random
import uuid
import shutil
from googlesearch import search
import PyPDF2
from pptx import Presentation
import numpy as np

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


    <script>
      document.querySelector('form').addEventListener('submit', function() {
        var btn = this.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = 'Generating Answers... (Please wait, this may take 1-3 minutes due to API limits)';
        btn.style.cursor = 'wait';
      });
    </script>
  </body>
</html>
"""

# --- Core RAG Logic ---

# --- CONFIGURATION ---
# Replace 'YOUR_API_KEY_HERE' with your actual Gemini API key.
# For security, you should preferably set it as an environment variable: export GEMINI_API_KEY="your-key"
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

client = genai.Client(api_key=API_KEY)

# --- Professional RAG Configuration ---
EMBEDDING_MODEL_NAME = 'gemini-embedding-001'
GENERATION_MODEL_NAME = 'gemini-1.5-flash'
TOP_K_CHUNKS = 15 # Number of most relevant chunks to retrieve (slightly reduced for token efficiency)

# --- API Interaction with Retry Logic ---

def call_with_retry(func, *args, max_retries=15, **kwargs):
    """Generic retry wrapper with exponential backoff, jitter, and quota detection for API calls."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_message = str(e).lower()

            # Catch rate limit, quota, and temporary server errors
            is_quota_error = any(x in error_message for x in ["429", "quota", "resource_exhausted"])
            is_transient_error = any(x in error_message for x in ["503", "unavailable", "high demand", "deadline_exceeded"])

            if is_quota_error or is_transient_error:
                # If we've hit quota multiple times, implement a 60-second "cool down"
                if is_quota_error and attempt >= 5:
                    wait_time = 60 + random.uniform(0, 5)
                    print(f"    - [Critical Quota Hit] Waiting for {wait_time:.2f} seconds before retrying (Attempt {attempt+1}/{max_retries})...")
                else:
                    # Exponential backoff with jitter: 2^attempt + random(0, 2)
                    wait_time = (2 ** attempt) + random.uniform(0, 2)
                    print(f"    - Transient error or Rate limit hit. Waiting for {wait_time:.2f} seconds before retrying (Attempt {attempt+1}/{max_retries})...")

                time.sleep(wait_time)
            else:
                # For non-transient errors, raise immediately
                print(f"    - A non-retryable error occurred: {e}")
                raise e

    raise Exception(f"Failed after {max_retries} attempts due to persistent API errors or rate limits.")

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

# --- Vector Search Pipeline ---

def chunk_text(text, chunk_size=2000, overlap=400):
    """Splits a long text into smaller, overlapping chunks, trying to break at whitespace."""
    if not text:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        # If we have less than chunk_size left, take it all
        if start + chunk_size >= text_len:
            chunks.append(text[start:].strip())
            break

        end = start + chunk_size
        # Try to find a good breaking point (newline or space) near the end
        break_point = text.rfind('\n', end - 200, end)
        if break_point == -1:
            break_point = text.rfind(' ', end - 100, end)

        if break_point != -1:
            end = break_point

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap
        if start < 0: start = 0
        # Safety check to ensure we always move forward
        if start >= end:
            start = end

    return [c for c in chunks if c]

def embed_content(chunks):
    """Embeds a list of text chunks in a single batch API call with retry logic."""
    print(f"    - Embedding {len(chunks)} chunks in a batch...")
    try:
        def do_embed():
            return client.models.embed_content(
                model=EMBEDDING_MODEL_NAME,
                contents=chunks,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
            )

        result = call_with_retry(do_embed)
        print("      ... Batch embedding complete.")
        return [e.values for e in result.embeddings]
    except Exception as e:
        print(f"      ... Error during batch embedding: {e}")
        return []

def find_most_relevant_chunks(question_embedding, chunk_embeddings, chunks):
    """Finds the most relevant chunks using cosine similarity."""
    print("    - Performing vector search...")
    # Convert lists to numpy arrays for vectorized operations
    question_vec = np.array(question_embedding)
    chunk_vecs = np.array(chunk_embeddings)

    # Calculate cosine similarity
    dot_products = np.dot(chunk_vecs, question_vec)
    norms = np.linalg.norm(chunk_vecs, axis=1) * np.linalg.norm(question_vec)
    similarities = dot_products / norms

    # Get the indices of the top K most similar chunks
    # Ensure TOP_K_CHUNKS does not exceed the actual number of chunks
    k = min(TOP_K_CHUNKS, len(chunks))
    top_k_indices = np.argsort(similarities)[-k:][::-1]

    print(f"      ... Found top {k} relevant chunks.")
    return [chunks[i] for i in top_k_indices]

# --- AI Chain ---

def generate_final_answer(user_query, document_context, grant_context, persona):
    """Generates the final answer using the Writer AI with robust retry logic."""
    print("\n[+] Running Writer AI...")
    system_prompt = (
        "You are a world-class AI writer and grant reviewer. Your process is to: "
        "1. Synthesize: Combine the user's query, persona, application context, and the provided knowledge base. "
        "2. Refine: Produce a polished, final-version answer. "
        "Your final answer MUST be perfectly aligned with the provided persona and context, and well-supported by the knowledge base. "
        "Provide only the final, polished text."
    )

    full_prompt = (
        f"--- ADOPT THIS PERSONA ---\n{persona}\n\n"
        f"--- APPLICATION CONTEXT (Your Primary Focus) ---\n{grant_context}\n\n"
        f"--- INTERNAL KNOWLEDGE BASE (Use for all qualitative info) ---\n{document_context}\n\n"
        f"--- QUESTION TO ANSWER ---\n"
        f"Based on all the above, generate the single best, final-version answer to the following question:\n"
        f"'{user_query}'"
    )

    try:
        def do_generate():
            return client.models.generate_content(
                model=GENERATION_MODEL_NAME,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt
                )
            )

        response = call_with_retry(do_generate)
        print("    - Final answer generated successfully.")
        return response.text
    except Exception as e:
        print(f"    - Failed to generate answer: {e}")
        return f"An error occurred during final generation after multiple retries: {e}"

# --- Main Processing Function ---
def process_request(upload_dir, grant_context, persona, questions_text):
    print("\n\n" + "="*50)
    print("===== STARTING NEW REQUEST (Vector Search Workflow) =====")
    print("="*50)

    if not API_KEY or "AIzaSy" not in API_KEY:
        error_msg = "FATAL ERROR: API_KEY is not set correctly. Please update the script with a valid API key."
        print(f"[!] {error_msg}")
        return [error_msg]

    # 1. Load and Chunk Documents
    print("\n[+] Step 1: Loading and Chunking Documents...")
    all_text = ""
    for filename in os.listdir(upload_dir):
        file_path = os.path.join(upload_dir, filename)
        print(f"    - Reading file: {filename}")
        if filename.endswith(".txt"):
            all_text += read_txt(file_path) + "\n\n"
        elif filename.endswith(".pdf"):
            all_text += read_pdf(file_path) + "\n\n"
        elif filename.endswith(".pptx"):
            all_text += read_pptx(file_path) + "\n\n"

    if not all_text.strip():
        error_msg = "[Error] No text could be extracted from the uploaded documents."
        print(f"[!] {error_msg}")
        return [error_msg]

    chunks = chunk_text(all_text)
    print(f"    - Document content split into {len(chunks)} chunks.")

    # 2. Embed all chunks
    print("\n[+] Step 2: Embedding Document Chunks...")
    chunk_embeddings = embed_content(chunks)
    if not chunk_embeddings:
        error_msg = "[Error] Failed to create embeddings for the document chunks."
        print(f"[!] {error_msg}")
        return [error_msg]

    questions = [q.strip() for q in questions_text.split('\n') if q.strip()]
    if not questions:
        error_msg = "[Error] No questions provided."
        print(f"[!] {error_msg}")
        return [error_msg]

    final_answers = []
    for i, user_question in enumerate(questions):
        print("\n" + "-"*50)
        print(f"===== PROCESSING QUESTION {i+1}/{len(questions)} =====")
        print(f"QUESTION: {user_question}")
        print("-"*50)

        answer_block = f"===== PROCESSING QUESTION {i+1}/{len(questions)} =====\n"
        answer_block += f"QUESTION: {user_question}\n\n"

        # 3. Embed the Question
        print("\n[+] Step 3: Embedding the User's Question...")
        try:
            def do_embed_query():
                return client.models.embed_content(
                    model=EMBEDDING_MODEL_NAME,
                    contents=user_question,
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
                )

            question_embedding_result = call_with_retry(do_embed_query)
            question_embedding = question_embedding_result.embeddings[0].values
            print("    - Question embedding complete.")
        except Exception as e:
            print(f"    - Failed to embed question after all retries: {e}")
            final_answers.append(answer_block + f"[Error] Failed to process this question due to persistent API errors: {e}")
            continue

        # 4. Find Relevant Chunks
        print("\n[+] Step 4: Finding Relevant Chunks via Vector Search...")
        relevant_chunks = find_most_relevant_chunks(question_embedding, chunk_embeddings, chunks)
        context = "\n---\n".join(relevant_chunks)

        # 5. Generate Final Answer
        final_answer = generate_final_answer(user_question, context, grant_context, persona)

        answer_block += f"[Info] Using knowledge from the {len(relevant_chunks)} most relevant document chunks.\n\n"
        answer_block += "===== FINAL RECOMMENDED ANSWER =====\n"
        answer_block += final_answer
        final_answers.append(answer_block)

        # Throttling to respect API Rate Limits (approx 15 RPM for free tier)
        # 1 question = 1 embed + 1 generation = 2 calls.
        # We need to slow down loop.
        print(f"    [Rate Limit Control] Sleeping for 20 seconds between questions...")
        time.sleep(20)

    print("\n" + "="*50)
    print("===== REQUEST COMPLETE =====")
    print("="*50 + "\n")
    return final_answers


# --- Flask Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    results = None
    if request.method == 'POST':
        print("\n[+] Received new request from web UI.")
        uploaded_files = request.files.getlist('files')

        # Check if any files were actually uploaded
        if not any(f.filename for f in uploaded_files):
            return render_template_string(HTML_TEMPLATE, results=["[Error] No files were uploaded. Please select your documents (PDF, TXT, PPTX)."])

        # Create a unique session folder for this request
        session_id = str(uuid.uuid4())
        session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_upload_dir, exist_ok=True)

        try:
            saved_count = 0
            for file in uploaded_files:
                if file.filename != '':
                    filename = secure_filename(file.filename)
                    # Only save supported extensions
                    if filename.lower().endswith(('.pdf', '.txt', '.pptx')):
                        file_path = os.path.join(session_upload_dir, filename)
                        file.save(file_path)
                        saved_count += 1

            if saved_count == 0:
                 return render_template_string(HTML_TEMPLATE, results=["[Error] None of the uploaded files are supported. Please upload .pdf, .txt, or .pptx files."])

            grant_context = request.form.get('grant_context', 'A general inquiry.')
            persona = request.form.get('persona', 'A professional representative.')
            questions = request.form.get('questions', '')

            results = process_request(
                upload_dir=session_upload_dir,
                grant_context=grant_context,
                persona=persona,
                questions_text=questions
            )
        finally:
            # Clean up session folder
            try:
                shutil.rmtree(session_upload_dir)
            except Exception as e:
                print(f"Error cleaning up {session_upload_dir}: {e}")

    return render_template_string(HTML_TEMPLATE, results=results)

if __name__ == '__main__':
    app.run(debug=True, port=8080)
