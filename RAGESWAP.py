from flask import Flask, render_template_string, request, jsonify, send_from_directory
import os
import uuid
import shutil
import threading
import time
import random
import logging
import hashlib
from typing import Callable, Any, TypeVar, List, Optional, Dict, Tuple
from werkzeug.utils import secure_filename
from google import genai
from google.genai import types
import PyPDF2
from pptx import Presentation
import numpy as np
from playwright.sync_api import sync_playwright, Page, Frame, ElementHandle

# --- CONFIGURATION ---
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")
UPLOAD_FOLDER = 'uploads'
SCREENSHOT_FOLDER = 'static/screenshots'
RESULTS_STORE = {} # In-memory results store: {session_id: {'status': 'processing', 'results': [], 'progress': 0, 'total': 0, 'screenshot': None}}

# --- Embedding Cache ---
EMBEDDING_CACHE: Dict[str, Dict] = {}
EMBEDDING_CACHE_LOCK = threading.Lock()
MAX_CACHE_ENTRIES = 50
_cache_insertion_order: List[str] = []

# --- Flask App Setup ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SCREENSHOT_FOLDER'] = SCREENSHOT_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['SCREENSHOT_FOLDER'], exist_ok=True)

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
    <title>Strategic Writing & Universal Form-Filling Assistant</title>
    <style>
      body { font-family: system-ui, -apple-system, sans-serif; margin: 2em; max-width: 800px; margin-left: auto; margin-right: auto; line-height: 1.5; color: #212529; }
      textarea, input[type="text"], input[type="url"] { width: 100%; padding: 0.6em; border: 1px solid #ced4da; border-radius: 4px; box-sizing: border-box; }
      textarea { height: 100px; }
      .error { color: #d9534f; background-color: #f2dede; padding: 1em; border: 1px solid #ebccd1; border-radius: 4px; margin-bottom: 1em; }
      .form-group { margin-bottom: 1.5em; }
      label { display: block; font-weight: bold; margin-bottom: 0.5em; }
      button { padding: 0.8em 1.5em; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em; font-weight: 600; }
      button:hover { background-color: #0056b3; }
      .checkbox-group { display: flex; align-items: center; gap: 0.5em; }
      .checkbox-group label { display: inline; font-weight: normal; margin-bottom: 0; }
      .checkbox-group input { width: auto; }
      .section-divider { border-top: 2px solid #e9ecef; margin: 2em 0; }
    </style>
  </head>
  <body>
    <h1>Strategic Writing & Universal Form-Filling Assistant</h1>
    <p>Upload context documents and either enter questions manually or provide any Web Form URL to extract, evaluate choices, and auto-fill forms (including inside iframes, radios, dropdowns, and rich text fields).</p>

    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}

    <form method="post" enctype="multipart/form-data">
      <div class="form-group">
        <label>1. Upload Knowledge Documents</label>
        <p style="margin-top:0; color: #6c757d;">Select your PDF, TXT, and PowerPoint files to build the RAG knowledge base.</p>
        <input type="file" name="files" multiple>
      </div>

      <div class="form-group">
        <label>2. Application / Grant Context</label>
        <p style="margin-top:0; color: #6c757d;">Paste the grant, program description, focus areas, or mission details.</p>
        <textarea name="grant_context" placeholder="e.g. AI Innovation Grant focusing on healthcare solutions..."></textarea>
      </div>

      <div class="form-group">
        <label>3. Persona & Tone</label>
        <p style="margin-top:0; color: #6c757d;">Describe the ideal persona for answers (e.g., "Ambitious, data-driven founder").</p>
        <textarea name="persona" placeholder="e.g. Professional, visionary tech founder..."></textarea>
      </div>

      <div class="section-divider"></div>

      <div class="form-group">
        <label>4. Direct Web Form URL (Universal Online Form Filling)</label>
        <p style="margin-top:0; color: #6c757d;">Enter the web URL of any online form on the internet to fill automatically.</p>
        <input type="url" name="form_url" placeholder="https://example.com/grant-application-form">
      </div>

      <div class="form-group checkbox-group">
        <input type="checkbox" id="auto_submit" name="auto_submit" value="true">
        <label for="auto_submit">Automatically click submit button on the web form after filling</label>
      </div>

      <div class="form-group">
        <label>5. Manual Questions (Optional if Form URL is provided)</label>
        <p style="margin-top:0; color: #6c757d;">Enter questions line-by-line if generating text answers without a target web form.</p>
        <textarea name="questions" placeholder="e.g., Name of the startup&#10;Startup's website&#10;Please describe your startup."></textarea>
      </div>

      <br>
      <button type="submit">Start Assistant & Fill Form</button>
    </form>

    <script>
      document.querySelector('form').addEventListener('submit', function() {
        var btn = this.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = 'Processing request...';
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
    <title>Results - Universal Form-Filling Assistant</title>
    <style>
      body { font-family: system-ui, -apple-system, sans-serif; margin: 2em; max-width: 900px; margin-left: auto; margin-right: auto; color: #212529; }
      .results { white-space: pre-wrap; background-color: #f8f9fa; padding: 1.5em; border: 1px solid #dee2e6; border-radius: 4px; margin-top: 1em; }
      .status-box { padding: 1em; margin-bottom: 2em; border-radius: 4px; border: 1px solid #ddd; display: flex; align-items: center; justify-content: space-between; }
      .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 24px; height: 24px; animation: spin 2s linear infinite; margin-right: 15px; }
      @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
      .progress-bar { width: 100%; background-color: #f1f1f1; border-radius: 4px; margin-top: 0.5em; }
      .progress-inner { height: 10px; background-color: #28a745; border-radius: 4px; transition: width 0.5s ease; }
      .error-msg { color: #d9534f; font-weight: bold; }
      .screenshot-container { margin-top: 2em; border: 1px solid #ced4da; padding: 1em; border-radius: 4px; background: #fff; }
      .screenshot-container img { max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; margin-top: 0.5em; }
    </style>
  </head>
  <body>
    <h1>Form Filling & Generation Status</h1>

    <div id="status-container" class="status-box">
      <div style="display: flex; align-items: center; width: 100%;">
        <div id="status-spinner" class="spinner"></div>
        <div style="flex-grow: 1;">
          <span id="status-text">Starting background processing...</span>
          <div id="progress-container" class="progress-bar">
            <div id="progress-bar" class="progress-inner" style="width: 0%"></div>
          </div>
        </div>
      </div>
      <div id="progress-count" style="margin-left: 15px; font-weight: bold; white-space: nowrap;"></div>
    </div>

    <div id="screenshot-area"></div>
    <div id="results-list"></div>

    <a href="/" style="display: inline-block; margin-top: 2em; text-decoration: none; color: #007bff; font-weight: 600;">&larr; Start New Request</a>

    <script>
      const session_id = "{{ session_id }}";
      const resultsList = document.getElementById('results-list');
      const screenshotArea = document.getElementById('screenshot-area');
      const statusText = document.getElementById('status-text');
      const progressCount = document.getElementById('progress-count');
      const progressBar = document.getElementById('progress-bar');
      const statusSpinner = document.getElementById('status-spinner');

      let pollInterval = setInterval(checkStatus, 3000);

      function checkStatus() {
        fetch(`/status/${session_id}`)
          .then(response => response.json())
          .then(data => {
            if (data.status === 'processing' || data.status === 'completed' || data.status.startsWith('Filling') || data.status.startsWith('Extracting') || data.status.startsWith('Generating') || data.status.startsWith('Navigating') || data.status.startsWith('Evaluating') || data.status.startsWith('Selecting') || data.status.startsWith('Attempting')) {
              if (data.total > 0) {
                const percent = (data.progress / data.total) * 100;
                progressBar.style.width = percent + '%';
                progressCount.innerText = `${data.progress} / ${data.total}`;
                statusText.innerText = data.status === 'completed' ? 'Processing & Form Filling Complete!' : data.status;
              } else {
                statusText.innerText = data.status;
              }

              if (data.screenshot) {
                screenshotArea.innerHTML = `
                  <div class="screenshot-container">
                    <h3>Web Form Screenshot</h3>
                    <p>Below is the visual confirmation of the filled web form:</p>
                    <a href="${data.screenshot}" target="_blank">
                      <img src="${data.screenshot}" alt="Web Form Screenshot">
                    </a>
                  </div>
                `;
              }

              if (data.results && data.results.length > 0) {
                resultsList.innerHTML = '';
                data.results.forEach((result) => {
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
    MIN_SECONDS_BETWEEN_CALLS = 6.0

    def __init__(self, api_key: str, generation_model: str = 'gemini-2.5-flash', embedding_model: str = 'gemini-embedding-001'):
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120_000))
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
        """Industry-standard retry wrapper with exponential backoff, jitter, and quota detection."""
        attempt = 0
        while True:
            try:
                self._throttle()
                return func(*args, **kwargs)
            except Exception as e:
                error_message = str(e).lower()
                is_quota_error = any(x in error_message for x in ["429", "quota", "resource_exhausted"])
                is_transient_error = any(x in error_message for x in ["500", "502", "503", "504", "unavailable", "high demand", "deadline_exceeded", "internal error", "bad gateway", "gateway timeout", "timed out", "timeout"])

                if is_quota_error or is_transient_error:
                    if is_quota_error:
                        wait_time = 60 + random.uniform(0, 5)
                        logger.warning(f"  [Quota Limit Hit] Waiting for {wait_time:.2f}s (Attempt {attempt+1}). Error: {e}")
                    else:
                        wait_time = min(2 ** attempt, 60) + random.uniform(0, 2)
                        logger.info(f"  Transient error. Waiting for {wait_time:.2f}s (Attempt {attempt+1}). Error: {e}")
                    time.sleep(wait_time)
                    attempt += 1
                else:
                    logger.error(f"  Non-retryable API error: {e}")
                    raise e

    def embed_documents(self, chunks: List[str], session_id: Optional[str] = None) -> List[List[float]]:
        all_embeddings = []
        batch_size = 30
        total_batches = (len(chunks) + batch_size - 1) // batch_size

        for i in range(0, len(chunks), batch_size):
            batch_idx = (i // batch_size) + 1
            if session_id and session_id in RESULTS_STORE:
                RESULTS_STORE[session_id]['status'] = f'Embedding documents (Batch {batch_idx}/{total_batches})...'

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
                "and provided knowledge base to produce a concise, polished answer suitable for a form input field. "
                "Ensure alignment with the provided persona and context. Provide ONLY the final answer text with no surrounding quotes."
            )
            full_prompt = (
                f"--- PERSONA ---\n{persona}\n\n"
                f"--- APPLICATION CONTEXT ---\n{grant_context}\n\n"
                f"--- KNOWLEDGE BASE ---\n{context}\n\n"
                f"--- QUESTION / FIELD LABEL ---\n'{question}'"
            )
            return self.gemini.generate_answer(full_prompt, system_prompt).strip()
        except Exception as e:
            logger.error(f"Failed to process question: {e}")
            return f"[Error] Could not generate response: {e}"

# --- Background Task & Universal Form Filling Logic ---

file_processor = FileProcessor()

def _hash_file(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def _cache_get(file_hash: str) -> Optional[Dict]:
    with EMBEDDING_CACHE_LOCK:
        return EMBEDDING_CACHE.get(file_hash)

def _cache_put(file_hash: str, chunks: List[str], embeddings: List[List[float]]):
    with EMBEDDING_CACHE_LOCK:
        if file_hash in EMBEDDING_CACHE:
            return
        if len(EMBEDDING_CACHE) >= MAX_CACHE_ENTRIES:
            oldest = _cache_insertion_order.pop(0)
            EMBEDDING_CACHE.pop(oldest, None)
        EMBEDDING_CACHE[file_hash] = {'chunks': chunks, 'embeddings': embeddings}
        _cache_insertion_order.append(file_hash)


def extract_field_label(frame: Frame, element: ElementHandle) -> str:
    """Extracts field context, legend/fieldset labels, aria attributes, and placeholders for any input."""
    elem_id = element.get_attribute("id")
    elem_name = element.get_attribute("name")
    elem_placeholder = element.get_attribute("placeholder")
    aria_label = element.get_attribute("aria-label")
    aria_labelledby = element.get_attribute("aria-labelledby")

    labels = []

    if aria_label:
        labels.append(aria_label.strip())

    if aria_labelledby:
        try:
            target_elem = frame.query_selector(f"#{aria_labelledby}")
            if target_elem:
                txt = target_elem.inner_text().strip()
                if txt: labels.append(txt)
        except Exception:
            pass

    if elem_id:
        try:
            label_elem = frame.query_selector(f'label[for="{elem_id}"]')
            if label_elem:
                txt = label_elem.inner_text().strip()
                if txt: labels.append(txt)
        except Exception:
            pass

    try:
        legend_txt = element.evaluate('''el => {
            let fieldset = el.closest("fieldset");
            if (fieldset) {
                let legend = fieldset.querySelector("legend");
                if (legend) return legend.innerText || legend.textContent;
            }
            return null;
        }''')
        if legend_txt and legend_txt.strip():
            labels.append(f"[{legend_txt.strip()}]")
    except Exception:
        pass

    try:
        parent_txt = element.evaluate('''el => {
            let parent = el.closest("label") || el.closest(".form-group, .field, .input-container");
            if (parent) {
                let clone = parent.cloneNode(true);
                let inputs = clone.querySelectorAll("input, textarea, select");
                inputs.forEach(i => i.remove());
                return clone.innerText || clone.textContent;
            }
            return null;
        }''')
        if parent_txt and parent_txt.strip():
            labels.append(parent_txt.strip())
    except Exception:
        pass

    if elem_placeholder:
        labels.append(f"Placeholder: {elem_placeholder.strip()}")

    if elem_name:
        labels.append(f"Name: {elem_name.replace('_', ' ').replace('-', ' ').title().strip()}")

    if labels:
        seen = set()
        clean_labels = []
        for l in labels:
            if l not in seen:
                seen.add(l)
                clean_labels.append(l)
        return " - ".join(clean_labels)

    return "Form Field"


def find_and_fill_all_fields(
    session_id: str,
    page: Page,
    grant_context: str,
    persona: str,
    all_chunks: List[str],
    all_embeddings: List[List[float]],
    rag_engine: RAGEngine
) -> Tuple[List[str], int]:
    """Traverses main page and all embedded frames/iframes to locate and fill out form inputs, radios, selects, checkboxes, and contenteditable elements."""

    frames = page.frames
    logger.info(f"[{session_id}] Scanning {len(frames)} frame(s) for online form elements...")

    all_fillable_items = []

    for frame in frames:
        try:
            inputs = frame.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='reset']):not([type='file']), textarea, select, div[contenteditable='true'], [role='textbox']")

            radio_groups = {}
            single_elements = []

            for elem in inputs:
                if not elem.is_visible() or not elem.is_enabled():
                    continue
                tag_name = elem.evaluate("el => el.tagName.toLowerCase()")
                input_type = (elem.get_attribute("type") or "text").lower()

                if input_type == "radio":
                    name = elem.get_attribute("name") or "unnamed_radio"
                    if name not in radio_groups:
                        radio_groups[name] = []
                    radio_groups[name].append((frame, elem))
                else:
                    single_elements.append((frame, elem, tag_name, input_type))

            for (f, elem, tag_name, input_type) in single_elements:
                all_fillable_items.append({
                    'type': 'single',
                    'frame': f,
                    'element': elem,
                    'tag_name': tag_name,
                    'input_type': input_type
                })

            for name, radios in radio_groups.items():
                all_fillable_items.append({
                    'type': 'radio_group',
                    'name': name,
                    'radios': radios
                })

        except Exception as scan_err:
            logger.warning(f"[{session_id}] Frame scan warning: {scan_err}")

    total_items = len(all_fillable_items)
    logger.info(f"[{session_id}] Total form items identified across frames: {total_items}")

    RESULTS_STORE[session_id]['total'] = total_items
    RESULTS_STORE[session_id]['progress'] = 0

    final_answers = []

    for idx, item in enumerate(all_fillable_items):
        try:
            if item['type'] == 'radio_group':
                first_frame, first_elem = item['radios'][0]
                group_label = extract_field_label(first_frame, first_elem)

                options_info = []
                for f, r_elem in item['radios']:
                    val = r_elem.get_attribute("value") or ""
                    r_label = extract_field_label(f, r_elem)
                    options_info.append(f"Value: '{val}' (Label: '{r_label}')")

                prompt = (
                    f"Which radio option best answers the group prompt '{group_label}'? "
                    f"Options available:\n" + "\n".join(options_info) + "\n"
                    "Provide ONLY the exact choice label or value to select."
                )

                RESULTS_STORE[session_id]['status'] = f"Evaluating radio group {idx+1}/{total_items}: '{group_label[:40]}'"
                answer = rag_engine.process_question(prompt, all_embeddings, all_chunks, grant_context, persona)

                best_match_elem = item['radios'][0][1]
                for f, r_elem in item['radios']:
                    val = r_elem.get_attribute("value") or ""
                    r_label = extract_field_label(f, r_elem)
                    if answer.lower() in val.lower() or answer.lower() in r_label.lower():
                        best_match_elem = r_elem
                        break

                best_match_elem.scroll_into_view_if_needed()
                best_match_elem.click(force=True)
                logger.info(f"[{session_id}] Selected radio option for group '{group_label}' -> {answer}")

                result_block = f"===== FORM FIELD {idx+1}/{total_items} (RADIO GROUP) =====\n"
                result_block += f"LABEL: {group_label}\n"
                result_block += f"SELECTED OPTION: {answer}\n"

            else:
                f = item['frame']
                elem = item['element']
                tag_name = item['tag_name']
                input_type = item['input_type']

                field_label = extract_field_label(f, elem)
                elem.scroll_into_view_if_needed()

                if input_type == "checkbox":
                    prompt = f"Should checkbox '{field_label}' be checked? Respond with YES or NO based on context."
                    RESULTS_STORE[session_id]['status'] = f"Evaluating checkbox {idx+1}/{total_items}: '{field_label[:40]}'"
                    answer = rag_engine.process_question(prompt, all_embeddings, all_chunks, grant_context, persona)
                    if "yes" in answer.lower() or "true" in answer.lower():
                        elem.check(force=True)
                        logger.info(f"[{session_id}] Checked checkbox '{field_label}'")
                    else:
                        elem.uncheck(force=True)

                elif tag_name == "select":
                    options = elem.query_selector_all("option")
                    opt_details = []
                    for opt in options:
                        val = opt.get_attribute("value") or ""
                        txt = opt.inner_text().strip()
                        if txt or val:
                            opt_details.append(f"Value: '{val}', Text: '{txt}'")

                    prompt = (
                        f"Select the best option for field '{field_label}'. "
                        f"Options:\n" + "\n".join(opt_details) + "\n"
                        "Provide ONLY the matching Value or Text."
                    )
                    RESULTS_STORE[session_id]['status'] = f"Selecting option for dropdown {idx+1}/{total_items}: '{field_label[:40]}'"
                    answer = rag_engine.process_question(prompt, all_embeddings, all_chunks, grant_context, persona)

                    selected = False
                    for opt in options:
                        val = opt.get_attribute("value") or ""
                        txt = opt.inner_text().strip()
                        if answer.lower() in val.lower() or answer.lower() in txt.lower():
                            elem.select_option(value=val if val else txt)
                            selected = True
                            break
                    if not selected and options:
                        elem.select_option(index=0)

                elif tag_name == "div" or elem.get_attribute("contenteditable") == "true":
                    prompt = f"Provide answer for rich-text field '{field_label}'"
                    RESULTS_STORE[session_id]['status'] = f"Generating response for rich-text field {idx+1}/{total_items}: '{field_label[:40]}'"
                    answer = rag_engine.process_question(prompt, all_embeddings, all_chunks, grant_context, persona)
                    elem.click()
                    f.evaluate("(el, text) => el.innerText = text", [elem, answer])

                else:
                    prompt = f"Provide response for field '{field_label}' (type: {input_type})"
                    RESULTS_STORE[session_id]['status'] = f"Generating response for field {idx+1}/{total_items}: '{field_label[:40]}'"
                    answer = rag_engine.process_question(prompt, all_embeddings, all_chunks, grant_context, persona)
                    elem.click()
                    elem.fill(answer)

                result_block = f"===== FORM FIELD {idx+1}/{total_items} =====\n"
                result_block += f"FIELD LABEL / PROMPT: {field_label}\n"
                result_block += "===== FILLED VALUE =====\n"
                result_block += answer

            final_answers.append(result_block)
            RESULTS_STORE[session_id]['results'] = final_answers
            RESULTS_STORE[session_id]['progress'] = idx + 1

        except Exception as fill_err:
            logger.error(f"[{session_id}] Error filling item {idx+1}: {fill_err}")

    return final_answers, total_items


def process_and_fill_web_form(
    session_id: str,
    form_url: str,
    grant_context: str,
    persona: str,
    all_chunks: List[str],
    all_embeddings: List[List[float]],
    rag_engine: RAGEngine,
    auto_submit: bool = False
):
    """Directly fills out any web form on the internet using Playwright."""
    logger.info(f"[{session_id}] Launching Playwright to process web form: {form_url}")
    RESULTS_STORE[session_id]['status'] = f'Navigating to form URL: {form_url}'

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        try:
            page.goto(form_url, wait_until="networkidle", timeout=45000)
        except Exception as e:
            logger.warning(f"[{session_id}] networkidle timeout, falling back: {e}")
            page.goto(form_url, wait_until="domcontentloaded", timeout=30000)

        page.wait_for_timeout(3000)

        final_answers, total_items = find_and_fill_all_fields(
            session_id=session_id,
            page=page,
            grant_context=grant_context,
            persona=persona,
            all_chunks=all_chunks,
            all_embeddings=all_embeddings,
            rag_engine=rag_engine
        )

        screenshot_filename = f"{session_id}.png"
        screenshot_path = os.path.join(app.config['SCREENSHOT_FOLDER'], screenshot_filename)
        page.screenshot(path=screenshot_path, full_page=True)
        RESULTS_STORE[session_id]['screenshot'] = f"/static/screenshots/{screenshot_filename}"

        if auto_submit:
            logger.info(f"[{session_id}] Auto-submit enabled. Locating submit button...")
            RESULTS_STORE[session_id]['status'] = 'Attempting auto-submit...'

            submit_found = False
            for f in page.frames:
                try:
                    submit_btn = f.query_selector("button[type='submit'], input[type='submit'], button:has-text('Submit'), button:has-text('Send'), button:has-text('Apply')")
                    if submit_btn and submit_btn.is_visible():
                        submit_btn.scroll_into_view_if_needed()
                        submit_btn.click(force=True)
                        submit_found = True
                        break
                except Exception:
                    pass

            if submit_found:
                page.wait_for_timeout(5000)
                page.screenshot(path=screenshot_path, full_page=True)
                logger.info(f"[{session_id}] Form submitted successfully.")

        RESULTS_STORE[session_id]['status'] = 'completed'
        browser.close()


def background_process_request(session_id, upload_dir, grant_context, persona, questions_text, form_url, auto_submit):
    """Processes a multi-question or direct online form filling request in the background."""
    RESULTS_STORE[session_id] = {'status': 'processing', 'results': [], 'progress': 0, 'total': 0, 'screenshot': None}
    try:
        if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "FATAL ERROR: API_KEY is not set correctly."
            return

        gemini_client = GeminiClient(api_key=API_KEY)
        rag_engine = RAGEngine(gemini_client=gemini_client)

        logger.info(f"[{session_id}] Checking document cache and extracting text...")
        RESULTS_STORE[session_id]['status'] = 'Checking document cache...'

        all_chunks: List[str] = []
        all_embeddings: List[List[float]] = []
        files_in_dir = [
            f for f in os.listdir(upload_dir)
            if f.lower().endswith(('.pdf', '.txt', '.pptx'))
        ]

        for filename in files_in_dir:
            file_path = os.path.join(upload_dir, filename)
            file_hash = _hash_file(file_path)
            cached = _cache_get(file_hash)

            if cached:
                logger.info(f"[{session_id}] CACHE HIT for '{filename}' - skipping embedding API call.")
                all_chunks.extend(cached['chunks'])
                all_embeddings.extend(cached['embeddings'])
            else:
                logger.info(f"[{session_id}] CACHE MISS for '{filename}' - embedding now.")
                if filename.lower().endswith('.txt'):
                    text = file_processor.read_txt(file_path)
                elif filename.lower().endswith('.pdf'):
                    text = file_processor.read_pdf(file_path)
                elif filename.lower().endswith('.pptx'):
                    text = file_processor.read_pptx(file_path)
                else:
                    continue

                if not text.strip():
                    logger.warning(f"[{session_id}] No text extracted from '{filename}', skipping.")
                    continue

                file_chunks = rag_engine.chunk_text(text)
                RESULTS_STORE[session_id]['status'] = f'Embedding "{filename}"...'
                file_embeddings = gemini_client.embed_documents(file_chunks, session_id=session_id)

                _cache_put(file_hash, file_chunks, file_embeddings)
                all_chunks.extend(file_chunks)
                all_embeddings.extend(file_embeddings)

        if not all_chunks or not all_embeddings:
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "No valid text or embeddings could be extracted from uploaded documents."
            return

        if form_url:
            from multiprocessing import Process
            p = Process(
                target=process_and_fill_web_form,
                args=(session_id, form_url, grant_context, persona, all_chunks, all_embeddings, rag_engine, auto_submit)
            )
            p.start()
            p.join()
        else:
            questions = [q.strip() for q in questions_text.split('\n') if q.strip()]
            if not questions:
                RESULTS_STORE[session_id]['status'] = 'error'
                RESULTS_STORE[session_id]['error'] = "No form URL or manual questions provided."
                return

            RESULTS_STORE[session_id]['total'] = len(questions)
            final_answers = []

            for i, user_question in enumerate(questions):
                logger.info(f"[{session_id}] Processing question {i+1}/{len(questions)}")
                answer = rag_engine.process_question(user_question, all_embeddings, all_chunks, grant_context, persona)

                result_block = f"===== QUESTION {i+1}/{len(questions)} =====\n"
                result_block += f"QUESTION: {user_question}\n\n"
                result_block += "===== FINAL RECOMMENDED ANSWER =====\n"
                result_block += answer

                final_answers.append(result_block)
                RESULTS_STORE[session_id]['results'] = final_answers
                RESULTS_STORE[session_id]['progress'] = i + 1

            RESULTS_STORE[session_id]['status'] = 'completed'
    except Exception as e:
        logger.error(f"[{session_id}] Background error: {e}", exc_info=True)
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
        form_url = request.form.get('form_url', '').strip()
        auto_submit = request.form.get('auto_submit') == 'true'

        if not form_url and not questions.strip():
            shutil.rmtree(session_upload_dir)
            return render_template_string(INDEX_HTML, error="Please provide either a target Web Form URL or manual questions.")

        thread = threading.Thread(
            target=background_process_request,
            args=(session_id, session_upload_dir, grant_context, persona, questions, form_url, auto_submit)
        )
        thread.start()
        return render_template_string(RESULTS_HTML, session_id=session_id)
    return render_template_string(INDEX_HTML)

@app.route('/status/<session_id>')
def status(session_id):
    if session_id not in RESULTS_STORE:
        return jsonify({'status': 'error', 'error': 'Session not found.'}), 404
    return jsonify(RESULTS_STORE[session_id])

@app.route('/static/screenshots/<path:filename>')
def serve_screenshot(filename):
    return send_from_directory(app.config['SCREENSHOT_FOLDER'], filename)

if __name__ == '__main__':
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        logger.error("FATAL: GEMINI_API_KEY environment variable is not set.")
        print("\n[!] ERROR: GEMINI_API_KEY not found.")
        print("Please set it: export GEMINI_API_KEY='your-api-key-here'\n")
    else:
        logger.info("Starting Strategic Writing & Form Filling Assistant on http://127.0.0.1:8080")
        app.run(debug=False, port=8080)
