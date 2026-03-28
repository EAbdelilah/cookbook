from flask import Flask, render_template, request, jsonify, current_app
import os
import uuid
import shutil
import threading
import time
import logging
from werkzeug.utils import secure_filename
from app.core.rag_engine import GeminiClient, RAGEngine
from app.utils.file_processor import FileProcessor

# Configuration
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")
UPLOAD_FOLDER = 'uploads'
RESULTS_STORE = {} # Simple in-memory results store: {session_id: {'status': 'processing', 'results': []}}

# Flask Setup
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Core logic
file_processor = FileProcessor()

def background_process_request(session_id, upload_dir, grant_context, persona, questions_text):
    """Processes a multi-question RAG request in the background."""
    RESULTS_STORE[session_id] = {'status': 'processing', 'results': [], 'progress': 0, 'total': 0}

    try:
        # 1. Initialize API Client
        if not API_KEY or "AIzaSy" not in API_KEY:
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "FATAL ERROR: API_KEY is not set correctly. Please update the script with a valid API key."
            return

        gemini_client = GeminiClient(api_key=API_KEY)
        rag_engine = RAGEngine(gemini_client=gemini_client)

        # 2. Extract and Chunk Documents
        logger.info(f"[{session_id}] Extracting text from documents...")
        all_text = file_processor.extract_text_from_directory(upload_dir)
        if not all_text.strip():
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "No text could be extracted from the uploaded documents."
            return

        chunks = rag_engine.chunk_text(all_text)
        logger.info(f"[{session_id}] Split documents into {len(chunks)} chunks.")

        # 3. Batch Embed All Chunks
        chunk_embeddings = gemini_client.embed_documents(chunks)
        if not chunk_embeddings:
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "Failed to create embeddings for document chunks after all retries."
            return

        # 4. Process Each Question
        questions = [q.strip() for q in questions_text.split('\n') if q.strip()]
        if not questions:
            RESULTS_STORE[session_id]['status'] = 'error'
            RESULTS_STORE[session_id]['error'] = "No questions provided."
            return

        RESULTS_STORE[session_id]['total'] = len(questions)
        final_answers = []

        for i, user_question in enumerate(questions):
            logger.info(f"[{session_id}] Processing question {i+1}/{len(questions)}")

            # Use the RAG pipeline for this question
            answer = rag_engine.process_question(user_question, chunk_embeddings, chunks, grant_context, persona)

            # Format and store result
            result_block = f"===== QUESTION {i+1}/{len(questions)} =====\n"
            result_block += f"QUESTION: {user_question}\n\n"
            result_block += "===== FINAL RECOMMENDED ANSWER =====\n"
            result_block += answer

            final_answers.append(result_block)
            RESULTS_STORE[session_id]['results'] = final_answers
            RESULTS_STORE[session_id]['progress'] = i + 1

            # Throttling to respect API Rate Limits (approx 15 RPM for free tier)
            # Sleep unless it's the last question
            if i < len(questions) - 1:
                logger.info(f"[{session_id}] Rate limit control: Sleeping for 20s before next question...")
                time.sleep(20)

        RESULTS_STORE[session_id]['status'] = 'completed'
        logger.info(f"[{session_id}] Request processing complete.")

    except Exception as e:
        logger.error(f"[{session_id}] Unhandled error in background processing: {e}")
        RESULTS_STORE[session_id]['status'] = 'error'
        RESULTS_STORE[session_id]['error'] = str(e)
    finally:
        # Cleanup uploaded files for this session
        try:
            shutil.rmtree(upload_dir)
        except Exception as e:
            logger.error(f"[{session_id}] Error cleaning up {upload_dir}: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')

        # Check if any files were actually uploaded
        if not any(f.filename for f in uploaded_files):
            return render_template('index.html', error="No files were uploaded. Please select your documents (PDF, TXT, PPTX).")

        # Create a unique session folder for this request
        session_id = str(uuid.uuid4())
        session_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_upload_dir, exist_ok=True)

        # Save supported files
        saved_count = 0
        for file in uploaded_files:
            if file.filename != '':
                filename = secure_filename(file.filename)
                if filename.lower().endswith(('.pdf', '.txt', '.pptx')):
                    file.save(os.path.join(session_upload_dir, filename))
                    saved_count += 1

        if saved_count == 0:
             shutil.rmtree(session_upload_dir)
             return render_template('index.html', error="None of the uploaded files are supported (.pdf, .txt, .pptx).")

        # Extract other form fields
        grant_context = request.form.get('grant_context', 'A general inquiry.')
        persona = request.form.get('persona', 'A professional representative.')
        questions = request.form.get('questions', '')

        # Start background processing
        thread = threading.Thread(target=background_process_request, args=(session_id, session_upload_dir, grant_context, persona, questions))
        thread.start()

        return render_template('results.html', session_id=session_id)

    return render_template('index.html')

@app.route('/status/<session_id>')
def status(session_id):
    """Returns the current status and results of a processing session."""
    if session_id not in RESULTS_STORE:
        return jsonify({'status': 'error', 'error': 'Session not found.'}), 404

    return jsonify(RESULTS_STORE[session_id])

if __name__ == '__main__':
    app.run(debug=True, port=8080)
