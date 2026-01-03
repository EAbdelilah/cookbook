from flask import Flask, render_template, request
import os
from werkzeug.utils import secure_filename
import rag_core

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/', methods=['GET', 'POST'])
def index():
    results = None
    if request.method == 'POST':
        # Handle file uploads
        uploaded_files = request.files.getlist('files')
        for file in uploaded_files:
            if file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        # Get text inputs
        grant_context = request.form.get('grant_context', 'A general inquiry; no specific context provided.')
        persona = request.form.get('persona', 'A professional and clear project representative.')
        questions = request.form.get('questions', '')

        # Process the request using the refactored core logic
        results = rag_core.process_request(
            upload_dir=app.config['UPLOAD_FOLDER'],
            grant_context=grant_context,
            persona=persona,
            questions_text=questions
        )

        # Clean up uploaded files after processing
        for file in uploaded_files:
             if file.filename != '':
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename)))

    return render_template('index.html', results=results)

if __name__ == '__main__':
    app.run(debug=True, port=8080)