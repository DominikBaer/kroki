import os
import subprocess
from flask import Flask, render_template, request

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return "Keine Datei ausgewählt"
    
    file = request.files['file']
    if file.filename == '':
        return "Kein Dateiname"

    # Datei speichern
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    # Skript ausführen und stdout abfangen
    try:
        result = subprocess.run(
            ['python', 'gpx_to_swiss_kroki.py', filepath], 
            capture_output=True, 
            text=True, 
            check=True
        )
        output = result.stdout # Hier ist die Konsolenausgabe
    except subprocess.CalledProcessError as e:
        output = f"Fehler im Skript: {e.stderr}"

    return render_template('index.html', output=output)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=4444, debug=True)

