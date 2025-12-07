"""
Spleeter API Server - Full Version with Queue
=============================================
Production-ready stem separation for Worship Team Sync
"""

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import os
import tempfile
import uuid
import threading
import time
from collections import OrderedDict

app = Flask(__name__, static_folder='static')
CORS(app)

# Job queue and status tracking
jobs = OrderedDict()
job_queue = []
queue_lock = threading.Lock()
is_processing = False

# Output directory
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/spleeter-output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"🚀 Starting Spleeter API Server (Full Version)")
print(f"📁 Output directory: {OUTPUT_DIR}")

# Serve static files
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    queue_length = len([j for j in jobs.values() if j['status'] == 'queued'])
    processing = len([j for j in jobs.values() if j['status'] == 'processing'])
    return jsonify({
        'status': 'ok',
        'message': 'Spleeter API (Full Version)',
        'queue_length': queue_length,
        'currently_processing': processing
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
        # Load first 60 seconds for analysis
        y, sr = librosa.load(temp_path, sr=22050, mono=True, duration=60)
        
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
        
        # Get full duration
        duration = librosa.get_duration(path=temp_path)
        
        return jsonify({
            'bpm': round(bpm),
            'key': keys[key_index],
            'scale': scale,
            'duration': round(duration, 2)
        })
        
    except Exception as e:
        print(f"Analysis error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/api/separate', methods=['POST'])
def separate_audio():
    """Queue a stem separation job"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    stems = request.form.get('stems', '2')
    
    # Create job
    job_id = str(uuid.uuid4())
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    
    input_path = os.path.join(job_dir, 'input.mp3')
    file.save(input_path)
    
    # Calculate queue position
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
    
    # Start processor if not running
    start_queue_processor()
    
    return jsonify({
        'job_id': job_id,
        'status': 'queued',
        'queue_position': queue_position,
        'message': f"You're #{queue_position + 1} in queue" if queue_position > 0 else "Processing now..."
    })

def start_queue_processor():
    """Start background thread to process queue"""
    global is_processing
    with queue_lock:
        if is_processing:
            return
        is_processing = True
    
    thread = threading.Thread(target=process_queue, daemon=True)
    thread.start()

def process_queue():
    """Process jobs in queue one at a time"""
    global is_processing
    
    while True:
        job_to_process = None
        
        with queue_lock:
            # Find next queued job
            for job_id, job in jobs.items():
                if job['status'] == 'queued':
                    job_to_process = (job_id, job)
                    break
            
            if not job_to_process:
                is_processing = False
                return
        
        job_id, job = job_to_process
        run_separation(job_id)
        
        # Update queue positions for remaining jobs
        with queue_lock:
            position = 0
            for jid, j in jobs.items():
                if j['status'] == 'queued':
                    j['queue_position'] = position
                    position += 1

def run_separation(job_id):
    """Run Spleeter separation"""
    try:
        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['progress'] = 5
        jobs[job_id]['queue_position'] = 0
        
        print(f"🎵 Starting separation for job {job_id}")
        
        # Lazy import Spleeter (heavy)
        from spleeter.separator import Separator
        
        jobs[job_id]['progress'] = 10
        
        stems = jobs[job_id]['stems']
        input_path = jobs[job_id]['input_path']
        
        model = f'spleeter:{stems}stems'
        print(f"📦 Loading model: {model}")
        separator = Separator(model)
        
        jobs[job_id]['progress'] = 30
        
        output_dir = os.path.join(OUTPUT_DIR, job_id, 'stems')
        print(f"🔄 Separating audio...")
        separator.separate_to_file(input_path, output_dir)
        
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
        
    except Exception as e:
        print(f"❌ Separation error: {e}")
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)

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
        response['message'] = "Processing your audio..."
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
    """Get overall queue status"""
    queued = len([j for j in jobs.values() if j['status'] == 'queued'])
    processing = len([j for j in jobs.values() if j['status'] == 'processing'])
    completed = len([j for j in jobs.values() if j['status'] == 'complete'])
    
    return jsonify({
        'queued': queued,
        'processing': processing,
        'completed': completed,
        'total': len(jobs)
    })

# Cleanup old jobs periodically (keep last 100)
def cleanup_old_jobs():
    with queue_lock:
        if len(jobs) > 100:
            # Remove oldest completed jobs
            to_remove = []
            for job_id, job in jobs.items():
                if job['status'] in ['complete', 'error']:
                    to_remove.append(job_id)
                if len(jobs) - len(to_remove) <= 50:
                    break
            
            for job_id in to_remove:
                del jobs[job_id]
                # Clean up files
                job_dir = os.path.join(OUTPUT_DIR, job_id)
                if os.path.exists(job_dir):
                    import shutil
                    shutil.rmtree(job_dir, ignore_errors=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 Server starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
