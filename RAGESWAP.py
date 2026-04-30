from flask import Flask, render_template_string, request, jsonify
import os
import uuid
import shutil
import threading
import time
import random
import logging
from typing import Callable, Any, TypeVar, List, Optional
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types
import PyPDF2
from pptx import Presentation
import numpy as np

# --- CONFIGURATION ---
# Replace 'YOUR_API_KEY_HERE' with your actual Gemini API key.
# For security, you should preferably set it as an environment variable: export GEMINI_API_KEY="your-key"
API_KEY = os.environ.get("GEMINI_API_KEY")
UPLOAD_FOLDER = 'uploads'
RESULTS_STORE = {} # In-memory results store: {session_id: {'status': 'processing', 'results': [], 'progress': 0, 'total': 0}}

# --- Flask App Setup ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

T = TypeVar('T')

# --- HTML Templates ---

INDEX_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>Strategic Writing Assistant</title>
    <style>
      body { font-family: sans-serif; margin: 2em; max-width: 800px; margin-left: auto; margin-right: auto; }
      textarea { width: 100%; height: 100px; }
      .error { color: #d9534f; background-color: #f2dede; padding: 1em; border: 1px solid #ebccd1; border-radius: 4px; margin-bottom: 1em; }
      .form-group { margin-bottom: 1.5em; }
      label { display: block; font-weight: bold; margin-bottom: 0.5em; }
      button { padding: 0.8em 1.5em; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
      button:hover { background-color: #0056b3; }
    </style>
  </head>
  <body>
    <h1>Strategic Writing Assistant</h1>

    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}

    <form method="post" enctype="multipart/form-data">
      <div class="form-group">
        <label>1. Upload Your Documents</label>
        <p>Select your PDF, TXT, and PowerPoint files.</p>
        <input type="file" name="files" multiple>
      </div>

      <div class="form-group">
        <label>2. Application Context</label>
        <p>Paste the grant/accelerator description, focus areas, or mission.</p>
        <textarea name="grant_context"></textarea>
      </div>

      <div class="form-group">
        <label>3. Persona & Tone</label>
        <p>Describe the ideal tone for this application (e.g., "Ambitious, data-driven founder").</p>
        <textarea name="persona"></textarea>
      </div>

      <div class="form-group">
        <label>4. Questions</label>
        <p>Enter each question on a new line.</p>
        <textarea name="questions" placeholder="e.g., Name of the startup\nStartup's website\nPlease describe your startup."></textarea>
      </div>

      <br>
      <button type="submit">Generate Answers</button>
    </form>

    <script>
      document.querySelector('form').addEventListener('submit', function() {
        var btn = this.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = 'Starting generation...';
        btn.style.cursor = 'wait';
      });
    </script>
  </body>
</html>
"""

RESULTS_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>Results - Strategic Writing Assistant</title>
    <style>
      body { font-family: sans-serif; margin: 2em; max-width: 900px; margin-left: auto; margin-right: auto; }
      .results { white-space: pre-wrap; background-color: #f8f9fa; padding: 1.5em; border: 1px solid #dee2e6; border-radius: 4px; margin-top: 1em; }
      .status-box { padding: 1em; margin-bottom: 2em; border-radius: 4px; border: 1px solid #ddd; display: flex; align-items: center; justify-content: space-between; }
      .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 24px; height: 24px; animation: spin 2s linear infinite; margin-right: 15px; }
      @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
      .progress-bar { width: 100%; background-color: #f1f1f1; border-radius: 4px; margin-top: 0.5em; }
      .progress-inner { height: 10px; background-color: #28a745; border-radius: 4px; transition: width 0.5s ease; }
      .error-msg { color: #d9534f; font-weight: bold; }
      hr { border: 0; border-top: 1px solid #eee; margin: 1.5em 0; }
    </style>
  </head>
  <body>
    <h1>Generating Answers</h1>

    <div id="status-container" class="status-box">
      <div style="display: flex; align-items: center;">
        <div id="status-spinner" class="spinner"></div>
        <div>
          <span id="status-text">Starting background processing...</span>
          <div id="progress-container" class="progress-bar">
            <div id="progress-bar" class="progress-inner" style="width: 0%"></div>
          </div>
        </div>
      </div>
      <div id="progress-count"></div>
    </div>

    <div id="results-list"></div>

    <a href="/" style="display: inline-block; margin-top: 2em; text-decoration: none; color: #007bff;">&larr; Start New Request</a>

    <script>
      const session_id = "{{ session_id }}";
      const resultsList = document.getElementById('results-list');
      const statusText = document.getElementById('status-text');
      const progressCount = document.getElementById('progress-count');
      const progressBar = document.getElementById('progress-bar');
      const statusSpinner = document.getElementById('status-spinner');

      let pollInterval = setInterval(checkStatus, 3000); // Poll every 3 seconds

      function checkStatus() {
        fetch(`/status/${session_id}`)
          .then(response => response.json())
          .then(data => {
            if (data.status === 'processing' || data.status === 'completed') {
              // Update progress
              if (data.total > 0) {
                const percent = (data.progress / data.total) * 100;
                progressBar.style.width = percent + '%';
                progressCount.innerText = `${data.progress} / ${data.total}`;
                statusText.innerText = data.status === 'completed' ? 'Generation complete!' : 'Generating answers...';
              } else {
                statusText.innerText = 'Extracting and embedding documents...';
              }

              // Update results list
              if (data.results && data.results.length > 0) {
                // Clear and rebuild to ensure order
                resultsList.innerHTML = '';
                data.results.forEach((result, index) => {
                  const div = document.createElement('div');
                  div.className = 'results';
                  div.innerText = result;
                  resultsList.appendChild(div);
                });
              }

              if (data.status === 'completed') {
                clearInterval(pollInterval);
                statusSpinner.style.display = 'none';
              }
            } else if (data.status === 'error') {
              clearInterval(pollInterval);
              statusSpinner.style.display = 'none';
              statusText.innerHTML = `<span class="error-msg">Error: ${data.error}</span>`;
            }
          })
          .catch(err => {
            console.error('Polling error:', err);
          });
      }
    </script>
  </body>
</html>
"""

# --- Industry-Grade RAG Pipeline Classes ---

class GeminiClient:
    """Encapsulates the Gemini API client with robust retry, quota handling, and global throttling."""

    _lock = threading.Lock()
    _last_call_time = 0.0
    MIN_SECONDS_BETWEEN_CALLS = 6.0 # Ensure max 10 calls per minute globally

    def __init__(self, api_key: str, generation_model: str = 'gemini-2.5-flash', embedding_model: str = 'gemini-embedding-001'):
        self.client = genai.Client(api_key=api_key, http_options={'timeout': 60.0})
        self.generation_model = generation_model
        self.embedding_model = embedding_model

    def _throttle(self):
        """Enforces a global delay between any two API calls to stay within Free Tier limits."""
        with GeminiClient._lock:
            now = time.time()
            elapsed = now - GeminiClient._last_call_time
            if elapsed < GeminiClient.MIN_SECONDS_BETWEEN_CALLS:
                wait_time = GeminiClient.MIN_SECONDS_BETWEEN_CALLS - elapsed
                time.sleep(wait_time)
            GeminiClient._last_call_time = time.time()

    def call_with_retry(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Industry-standard retry wrapper with exponential backoff, jitter, and quota detection. Retries indefinitely for retryable errors."""
        attempt = 0
        while True:
            try:
                self._throttle() # Apply global throttle
                return func(*args, **kwargs)
            except Exception as e:
                error_message = str(e).lower()
                is_quota_error = any(x in error_message for x in ["429", "quota", "resource_exhausted"])
                is_transient_error = any(x in error_message for x in ["500", "502", "503", "504", "unavailable", "high demand", "deadline_exceeded", "internal error", "bad gateway", "gateway timeout"])

                if is_quota_error or is_transient_error:
                    if is_quota_error and attempt >= 5:
                        wait_time = 60 + random.uniform(0, 5)
                        logger.warning(f"  [Critical Quota Hit] Waiting for {wait_time:.2f}s (Attempt {attempt+1})...")
                    else:
                        wait_time = min(2 ** attempt, 60) + random.uniform(0, 2)
                        logger.info(f"  Transient error or Rate limit hit. Waiting for {wait_time:.2f}s (Attempt {attempt+1})...")
                    time.sleep(wait_time)
                    attempt += 1
                else:
                    logger.error(f"  Non-retryable API error: {e}")
                    raise e

    def embed_documents(self, chunks: List[str]) -> List[List[float]]:
        """Embeds documents in batches to avoid API limitations on content size."""
        all_embeddings = []
        batch_size = 90 # Gemini batch limit is usually 100, we use 90 for safety
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            def do_embed():
                return self.client.models.embed_content(
                    model=self.embedding_model,
                    contents=batch,
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
                )
            result = self.call_with_retry(do_embed)
            all_embeddings.extend([e.values for e in result.embeddings])
        return all_embeddings

    def embed_query(self, query: str) -> List[float]:
        def do_embed_query():
            return self.client.models.embed_content(
                model=self.embedding_model,
                contents=query,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
            )
        result = self.call_with_retry(do_embed_query)
        return result.embeddings[0].values

    def generate_answer(self, prompt: str, system_instruction: str) -> str:
        def do_generate():
            return self.client.models.generate_content(
                model=self.generation_model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system_instruction)
            )
        response = self.call_with_retry(do_generate)
        return response.text

class FileProcessor:
    """Provides methods for reading and extracting text from supported file formats."""

    @staticmethod
    def read_txt(file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading TXT {file_path}: {e}")
            return ""

    @staticmethod
    def read_pdf(file_path: str) -> str:
        text = ""
        try:
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f, strict=False)
                for page in reader.pages:
                    text += page.extract_text() or ""
        except Exception as e:
            logger.error(f"Error reading PDF {file_path}: {e}")
        return text

    @staticmethod
    def read_pptx(file_path: str) -> str:
        text = ""
        try:
            prs = Presentation(file_path)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
        except Exception as e:
            logger.error(f"Error reading PPTX {file_path}: {e}")
        return text

    def extract_text_from_directory(self, directory_path: str) -> str:
        all_text = ""
        for filename in os.listdir(directory_path):
            file_path = os.path.join(directory_path, filename)
            logger.info(f"Processing file: {filename}")
            if filename.lower().endswith(".txt"):
                all_text += self.read_txt(file_path) + "\n\n"
            elif filename.lower().endswith(".pdf"):
                all_text += self.read_pdf(file_path) + "\n\n"
            elif filename.lower().endswith(".pptx"):
                all_text += self.read_pptx(file_path) + "\n\n"
        return all_text

class RAGEngine:
    """Manages the core RAG pipeline."""

    def __init__(self, gemini_client: GeminiClient, top_k_chunks: int = 15):
        self.gemini = gemini_client
        self.top_k_chunks = top_k_chunks

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 400) -> List[str]:
        if not text: return []
        chunks, start, text_len = [], 0, len(text)
        while start < text_len:
            end = start + chunk_size
            if end >= text_len:
                chunks.append(text[start:].strip())
                break
            break_point = text.rfind('\n', end - 200, end)
            if break_point == -1: break_point = text.rfind(' ', end - 100, end)
            if break_point != -1: end = break_point
            chunk = text[start:end].strip()
            if chunk: chunks.append(chunk)
            next_start = max(start + 1, end - overlap)
            # Final sanity check: ensure we always move forward
            if next_start <= start:
                start = end
            else:
                start = next_start
        return [c for c in chunks if c]

    def find_relevant_context(self, query_embedding: List[float], chunk_embeddings: List[List[float]], chunks: List[str]) -> str:
        query_vec = np.array(query_embedding)
        chunk_vecs = np.array(chunk_embeddings)
        dot_products = np.dot(chunk_vecs, query_vec)
        norms = np.linalg.norm(chunk_vecs, axis=1) * np.linalg.norm(query_vec)
        similarities = dot_products / norms
        k = min(self.top_k_chunks, len(chunks))
        top_k_indices = np.argsort(similarities)[-k:][::-1]
        return "\n---\n".join([chunks[i] for i in top_k_indices])

    def process_question(self, question: str, chunk_embeddings: List[List[float]], chunks: List[str], grant_context: str, persona: str) -> str:
        logger.info(f"RAG Engine: Processing question - '{question[:50]}...'")
        try:
            query_embedding = self.gemini.embed_query(question)
            context = self.find_relevant_context(query_embedding, chunk_embeddings, chunks)
            system_prompt = (
                "You are a world-class AI writer and grant reviewer. Synthesize the query, persona, "
                "and provided knowledge base to produce a polished, final-version answer. "
                "Ensure alignment with the provided persona and context. Provide ONLY the final text."
            )
            full_prompt = (
                f"--- PERSONA ---\n{persona}\n\n"
                f"--- APPLICATION CONTEXT ---\n{grant_context}\n\n"
                f"--- KNOWLEDGE BASE ---\n{context}\n\n"
                f"--- QUESTION ---\n'{question}'"
            )
            return self.gemini.generate_answer(full_prompt, system_prompt)
        except Exception as e:
            logger.error(f"Failed to process question: {e}")
            return f"[Fatal Error] This question failed due to a non-retryable error: {e}"

# --- Background Task Orchestration ---

file_processor = FileProcessor()

def background_process_request(session_id, upload_dir, grant_context, persona, questions_text):
    """Processes a multi-question RAG request in the background."""
    RESULTS_STORE[session_id] = {'status': 'processing', 'results': [], 'progress': 0, 'total': 0}
    try:
        if not API_KEY or "AIzaSy" not in API_KEY:
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "FATAL ERROR: API_KEY is not set correctly."
            return

        gemini_client = GeminiClient(api_key=API_KEY)
        rag_engine = RAGEngine(gemini_client=gemini_client)

        logger.info(f"[{session_id}] Extracting text from documents...")
        all_text = file_processor.extract_text_from_directory(upload_dir)
        if not all_text.strip():
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "No text could be extracted from uploaded documents."
            return

        chunks = rag_engine.chunk_text(all_text)
        chunk_embeddings = gemini_client.embed_documents(chunks)
        if not chunk_embeddings:
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "Failed to create embeddings for document chunks."
            return

        questions = [q.strip() for q in questions_text.split('\n') if q.strip()]
        if not questions:
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "No questions provided."
            return

        RESULTS_STORE[session_id]['total'] = len(questions)
        final_answers = []

        for i, user_question in enumerate(questions):
            logger.info(f"[{session_id}] Processing question {i+1}/{len(questions)}")
            answer = rag_engine.process_question(user_question, chunk_embeddings, chunks, grant_context, persona)

            result_block = f"===== QUESTION {i+1}/{len(questions)} =====\n"
            result_block += f"QUESTION: {user_question}\n\n"
            result_block += "===== FINAL RECOMMENDED ANSWER =====\n"
            result_block += answer

            final_answers.append(result_block)
            RESULTS_STORE[session_id]['results'] = final_answers
            RESULTS_STORE[session_id]['progress'] = i + 1

        RESULTS_STORE[session_id]['status'] = 'completed'
    except Exception as e:
        logger.error(f"[{session_id}] Background error: {e}")
        RESULTS_STORE[session_id]['status'] = 'error'
        RESULTS_STORE[session_id]['error'] = str(e)
    finally:
        try: shutil.rmtree(upload_dir)
        except: pass

# --- Flask Routes ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')
        if not any(f.filename for f in uploaded_files):
            return render_template_string(INDEX_HTML, error="No files were uploaded.")

        session_id = str(uuid.uuid4())
        session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_upload_dir, exist_ok=True)

        saved_count = 0
        for file in uploaded_files:
            if file.filename != '':
                filename = secure_filename(file.filename)
                if filename.lower().endswith(('.pdf', '.txt', '.pptx')):
                    file_path = os.path.join(session_upload_dir, filename)
                    file.save(file_path)
                    saved_count += 1

        if saved_count == 0:
             shutil.rmtree(session_upload_dir)
             return render_template_string(INDEX_HTML, error="None of the uploaded files are supported.")

        grant_context = request.form.get('grant_context', 'A general inquiry.')
        persona = request.form.get('persona', 'A professional representative.')
        questions = request.form.get('questions', '')

        thread = threading.Thread(target=background_process_request, args=(session_id, session_upload_dir, grant_context, persona, questions))
        thread.start()
        return render_template_string(RESULTS_HTML, session_id=session_id)
    return render_template_string(INDEX_HTML)

@app.route('/status/<session_id>')
def status(session_id):
    if session_id not in RESULTS_STORE:
        return jsonify({'status': 'error', 'error': 'Session not found.'}), 404
    return jsonify(RESULTS_STORE[session_id])

if __name__ == '__main__':
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        logger.error("FATAL: GEMINI_API_KEY environment variable is not set.")
        print("\n[!] ERROR: GEMINI_API_KEY not found.")
        print("Please set it: export GEMINI_API_KEY='your-api-key-here'\n")
    else:
        logger.info("Starting Strategic Writing Assistant on http://127.0.0.1:8080")
        # Debug is disabled for production stability
        app.run(debug=False, port=8080)
