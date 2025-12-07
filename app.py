"""
Spleeter API Server - Production Ready
"""

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import os
import tempfile
import uuid
import threading

app = Flask(__name__, static_folder='static')
CORS(app)

# Store job status
jobs = {}

# Output directory
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/spleeter-output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Serve static files
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Spleeter API is running'})

@app.route('/api/analyze', methods=['POST'])
def analyze_audio():
    """Analyze audio for BPM and Key detection"""
    import librosa
    import numpy as np
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.mp3")
    file.save(temp_path)
    
    try:
        y, sr = librosa.load(temp_path, sr=22050, mono=True)
        
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(tempo) if hasattr(tempo, '__float__') else float(tempo[0])
        
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_avg = np.mean(chroma, axis=1)
        
        keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        key_index = int(np.argmax(chroma_avg))
        
        major_third = chroma_avg[(key_index + 4) % 12]
        minor_third = chroma_avg[(key_index + 3) % 12]
        scale = 'Major' if major_third > minor_third else 'Minor'
        
        duration = librosa.get_duration(y=y, sr=sr)
        
        return jsonify({
            'bpm': round(bpm),
            'key': keys[key_index],
            'scale': scale,
            'duration': round(duration, 2)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/api/separate', methods=['POST'])
def separate_audio():
    """Start stem separation job"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    stems = request.form.get('stems', '2')
    
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    input_path = os.path.join(job_dir, 'input.mp3')
    file.save(input_path)
    
    jobs[job_id] = {
        'status': 'processing',
        'progress': 0,
        'stems': stems,
        'files': []
    }
    
    thread = threading.Thread(target=run_separation, args=(job_id, input_path, stems))
    thread.start()
    
    return jsonify({'job_id': job_id, 'status': 'processing'})

def run_separation(job_id, input_path, stems):
    """Run Spleeter separation in background"""
    try:
        from spleeter.separator import Separator
        
        jobs[job_id]['progress'] = 10
        
        model = f'spleeter:{stems}stems'
        separator = Separator(model)
        
        jobs[job_id]['progress'] = 30
        
        output_dir = os.path.join(OUTPUT_DIR, job_id, 'stems')
        separator.separate_to_file(input_path, output_dir)
        
        jobs[job_id]['progress'] = 90
        
        stem_dir = os.path.join(output_dir, 'input')
        if os.path.exists(stem_dir):
            files = []
            for f in os.listdir(stem_dir):
                if f.endswith('.wav'):
                    files.append({
                        'name': f.replace('.wav', ''),
                        'path': f'/api/download/{job_id}/{f}'
                    })
            jobs[job_id]['files'] = files
        
        jobs[job_id]['status'] = 'complete'
        jobs[job_id]['progress'] = 100
        
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
        print(f"Separation error: {e}")

@app.route('/api/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(jobs[job_id])

@app.route('/api/download/<job_id>/<filename>', methods=['GET'])
def download_stem(job_id, filename):
    file_path = os.path.join(OUTPUT_DIR, job_id, 'stems', 'input', filename)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype='audio/wav')
    return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    # Railway provides PORT env variable
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Spleeter API on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
