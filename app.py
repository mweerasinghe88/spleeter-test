"""
Audio Analyzer API - Lite Version (No Spleeter)
BPM/Key detection only - stem separation done client-side
"""

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import os
import tempfile
import uuid

app = Flask(__name__, static_folder='static')
CORS(app)

# Serve static files
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Audio Analyzer API (Lite)'})

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
    """Stem separation not available in lite version"""
    return jsonify({
        'error': 'Stem separation requires premium plan',
        'message': 'Use browser-based vocal removal instead'
    }), 503

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Audio Analyzer API (Lite) on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
