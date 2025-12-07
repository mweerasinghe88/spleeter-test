"""
Spleeter API Server - Memory Optimized
======================================
Uses 2-stem by default, limits duration, aggressive cleanup
"""

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import os
import tempfile
import uuid
import threading
import time
import gc
from collections import OrderedDict

app = Flask(__name__, static_folder='static')
CORS(app)

# Job queue and status tracking
jobs = OrderedDict()
queue_lock = threading.Lock()
is_processing = False

# Separator instance (reuse to save memory)
separator_instance = None
current_model = None

# Output directory
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/spleeter-output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Memory limit - max 5 minutes of audio
MAX_DURATION_SECONDS = 600

print(f"🚀 Starting Spleeter API Server (Memory Optimized)")
print(f"📁 Output directory: {OUTPUT_DIR}")
print(f"⏱️ Max duration: {MAX_DURATION_SECONDS}s")

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    queue_length = len([j for j in jobs.values() if j['status'] == 'queued'])
    processing = len([j for j in jobs.values() if j['status'] == 'processing'])
    return jsonify({
        'status': 'ok',
        'message': 'Spleeter API (Memory Optimized)',
        'queue_length': queue_length,
        'currently_processing': processing,
        'max_duration': MAX_DURATION_SECONDS
    })

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
        # Load first 30 seconds only for analysis (saves memory)
        y, sr = librosa.load(temp_path, sr=22050, mono=True, duration=30)
        
        # BPM Detection
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(tempo) if hasattr(tempo, '__float__') else float(tempo[0])
        
        # Key Detection
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_avg = np.mean(chroma, axis=1)
        
        keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        key_index = int(np.argmax(chroma_avg))
        
        major_third = chroma_avg[(key_index + 4) % 12]
        minor_third = chroma_avg[(key_index + 3) % 12]
        scale = 'Major' if major_third > minor_third else 'Minor'
        
        # Get duration without loading whole file
        duration = librosa.get_duration(path=temp_path)
        
        # Cleanup
        del y, chroma, chroma_avg
        gc.collect()
        
        return jsonify({
            'bpm': round(bpm),
            'key': keys[key_index],
            'scale': scale,
            'duration': round(duration, 2),
            'max_duration': MAX_DURATION_SECONDS
        })
        
    except Exception as e:
        print(f"Analysis error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        gc.collect()

@app.route('/api/separate', methods=['POST'])
def separate_audio():
    """Queue a stem separation job"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    stems = request.form.get('stems', '2')  # Default to 2 stems (least memory)
    
    # Force 2 stems for now to save memory
    if stems == '5':
        stems = '4'  # 5-stem uses too much memory
    
    # Create job
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    input_path = os.path.join(job_dir, 'input.mp3')
    file.save(input_path)
    
    # Check duration
    try:
        import librosa
        duration = librosa.get_duration(path=input_path)
        if duration > MAX_DURATION_SECONDS:
            return jsonify({
                'error': f'Audio too long ({int(duration)}s). Max is {MAX_DURATION_SECONDS}s (5 min). Please trim your file.'
            }), 400
    except:
        pass  # Continue anyway
    
    with queue_lock:
        queue_position = len([j for j in jobs.values() if j['status'] in ['queued', 'processing']])
        
        jobs[job_id] = {
            'status': 'queued',
            'progress': 0,
            'stems': stems,
            'files': [],
            'queue_position': queue_position,
            'created_at': time.time(),
            'input_path': input_path
        }
    
    start_queue_processor()
    
    return jsonify({
        'job_id': job_id,
        'status': 'queued',
        'queue_position': queue_position,
        'stems': stems,
        'message': f"You're #{queue_position + 1} in queue" if queue_position > 0 else "Processing now..."
    })

def start_queue_processor():
    global is_processing
    with queue_lock:
        if is_processing:
            return
        is_processing = True
    
    thread = threading.Thread(target=process_queue, daemon=True)
    thread.start()

def process_queue():
    global is_processing
    
    while True:
        job_to_process = None
        
        with queue_lock:
            for job_id, job in jobs.items():
                if job['status'] == 'queued':
                    job_to_process = (job_id, job)
                    break
            
            if not job_to_process:
                is_processing = False
                return
        
        job_id, job = job_to_process
        run_separation(job_id)
        
        # Update queue positions
        with queue_lock:
            position = 0
            for jid, j in jobs.items():
                if j['status'] == 'queued':
                    j['queue_position'] = position
                    position += 1

def run_separation(job_id):
    global separator_instance, current_model
    
    try:
        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['progress'] = 5
        jobs[job_id]['queue_position'] = 0
        
        stems = jobs[job_id]['stems']
        input_path = jobs[job_id]['input_path']
        model = f'spleeter:{stems}stems'
        
        print(f"🎵 Starting separation for job {job_id}")
        print(f"📦 Model: {model}")
        
        # Clear old separator if model changed
        if separator_instance is not None and current_model != model:
            print("♻️ Clearing old model from memory...")
            del separator_instance
            separator_instance = None
            gc.collect()
        
        jobs[job_id]['progress'] = 10
        
        # Lazy load Spleeter
        from spleeter.separator import Separator
        
        if separator_instance is None or current_model != model:
            print(f"📦 Loading model: {model}")
            separator_instance = Separator(model)
            current_model = model
        
        jobs[job_id]['progress'] = 30
        
        output_dir = os.path.join(OUTPUT_DIR, job_id, 'stems')
        print(f"🔄 Separating audio...")
        
        separator_instance.separate_to_file(input_path, output_dir)
        
        jobs[job_id]['progress'] = 90
        
        # Find output files
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
            print(f"✅ Separation complete: {len(files)} stems")
        
        jobs[job_id]['status'] = 'complete'
        jobs[job_id]['progress'] = 100
        
        # Cleanup input file to save space
        if os.path.exists(input_path):
            os.remove(input_path)
        
    except Exception as e:
        print(f"❌ Separation error: {e}")
        import traceback
        traceback.print_exc()
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)
    finally:
        gc.collect()

@app.route('/api/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = jobs[job_id]
    response = {
        'status': job['status'],
        'progress': job['progress'],
        'files': job.get('files', [])
    }
    
    if job['status'] == 'queued':
        response['queue_position'] = job.get('queue_position', 0)
        response['message'] = f"You're #{job['queue_position'] + 1} in queue"
    elif job['status'] == 'processing':
        response['message'] = "AI processing your audio..."
    elif job['status'] == 'error':
        response['error'] = job.get('error', 'Unknown error')
    
    return jsonify(response)

@app.route('/api/download/<job_id>/<filename>', methods=['GET'])
def download_stem(job_id, filename):
    file_path = os.path.join(OUTPUT_DIR, job_id, 'stems', 'input', filename)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype='audio/wav', as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/queue', methods=['GET'])
def get_queue_status():
    queued = len([j for j in jobs.values() if j['status'] == 'queued'])
    processing = len([j for j in jobs.values() if j['status'] == 'processing'])
    completed = len([j for j in jobs.values() if j['status'] == 'complete'])
    
    return jsonify({
        'queued': queued,
        'processing': processing,
        'completed': completed
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 Server starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
