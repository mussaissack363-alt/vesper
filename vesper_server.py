import os
import json
import datetime
from flask import Flask, request, jsonify, send_from_directory

from groq_brain_v3 import (
    think, think_with_image, read_text_file, DEVICE_TYPE,
    handle_phone_command, handle_pc_command, IMAGE_EXTENSIONS,
    handle_memory_command, mem_recall, mem_count, migrate_firebase_once,
    last_emotion
)

# emotion keyword fallback for quick command replies that skip the LLM
import re as _re

def _fallback_emotion(text):
    t = text.lower()
    if any(w in t for w in ('lol', 'haha', 'nice one', '😄', '😂')):
        return 'playful'
    if any(w in t for w in ('shutting down', 'locked', 'screenshot', 'done ✓', 'torch on', 'torch off', 'opening', 'set to', 'playing')):
        return 'playful'
    if any(w in t for w in ('error', 'failed', 'unavailable', 'not found', "can't", 'cannot', 'no ')):
        return 'sad'
    if any(w in t for w in ('warning', 'urgent', 'in 0 days', 'in 1 day', 'in 2 days')):
        return 'worried'
    return 'calm'

app = Flask(__name__, static_folder='static', static_url_path='')


@app.after_request
def _no_cache_static(resp):
    """Static assets and the model must always reflect the latest files on disk."""
    if (resp.mimetype or '').startswith(('text/html', 'application/javascript',
                                         'text/javascript', 'model/')):
        resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return resp


@app.route('/')
def index():
    # Voice-enabled UI is the default; classic UI still reachable at /classic
    return send_from_directory('static', 'vesper_index_v2_voice.html')


@app.route('/classic')
def classic():
    return send_from_directory('static', 'index.html')


@app.route('/showcase')
def showcase():
    # animation showcase: idle breathing, scold→playful expressions, blinks, visemes,
    # head tilts, spring-bone hair/tassels, cel shading
    return send_from_directory('static', 'showcase.html')


@app.route('/model/ella.vrm')
def ella_model():
    return send_from_directory('model', 'ella.vrm', mimetype='model/gltf-binary')


@app.route('/api/client-log', methods=['POST'])
def client_log():
    """Receive diagnostic events from the browser page (avatar load tracing)."""
    try:
        data = request.get_json(silent=True) or {}
        entry = {
            'ts': datetime.datetime.now().isoformat(timespec='seconds'),
            'msg': str(data.get('msg', ''))[:300],
            'detail': str(data.get('detail', ''))[:600],
        }
        with open('client_errors.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return jsonify({'ok': True})


@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_input = (data.get('message') or '').strip()
    if not user_input:
        return jsonify({'reply': ''})

    if DEVICE_TYPE == 'mobile':
        result = handle_phone_command(user_input)
        if result:
            return jsonify({'reply': result, 'emotion': _fallback_emotion(result)})

    if DEVICE_TYPE == 'pc':
        result = handle_pc_command(user_input)
        if result:
            return jsonify({'reply': result, 'emotion': _fallback_emotion(result)})

    reply = think(user_input)
    emo = last_emotion() if reply and not reply.startswith(('API error', 'Brain error')) else _fallback_emotion(reply)
    return jsonify({'reply': reply, 'emotion': emo})


@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400
    f = request.files['file']
    question = (request.form.get('message') or '').strip()
    os.makedirs('uploads', exist_ok=True)
    path = os.path.join('uploads', f.filename)
    f.save(path)

    ext = os.path.splitext(f.filename)[1].lower()

    # Images → vision model
    if ext in IMAGE_EXTENSIONS:
        mime = 'image/png' if ext == '.png' else 'image/jpeg' if ext in ('.jpg', '.jpeg') else 'image/webp' if ext == '.webp' else 'image/gif'
        reply = think_with_image(question, path, mime)
        emo = last_emotion() if reply and not reply.startswith(('API error', 'Vision error', 'Vision unavailable')) else _fallback_emotion(reply)
        return jsonify({'reply': reply, 'emotion': emo})

    # Text files and PDFs → extract text and think about it
    content = read_text_file(path)
    if content:
        prompt = question or f"I uploaded the file '{f.filename}'. Here is its content:\n\n{content}\n\nSummarize it and tell me what matters."
        reply = think(prompt)
        emo = last_emotion() if reply and not reply.startswith(('API error', 'Brain error')) else _fallback_emotion(reply)
        return jsonify({'reply': reply, 'emotion': emo})

    return jsonify({'reply': f"Saved \"{f.filename}\", but I can't read that file type yet "
                             f"(supported: images, PDFs, and text/code files)."})


@app.route('/api/memory', methods=['GET'])
def get_memory():
    query = request.args.get('q', '').strip()
    return jsonify({
        'count': mem_count(),
        'memories': mem_recall(query)
    })


@app.route('/api/memory', methods=['DELETE'])
def delete_memory():
    from groq_brain_v3 import mem_forget
    fragment = (request.args.get('q') or '').strip()
    if not fragment:
        return jsonify({'error': 'pass ?q=<text to forget>'}), 400
    deleted = mem_forget(fragment)
    return jsonify({'reply': f'Forgotten "{fragment}".' if deleted else f'Nothing matching "{fragment}" in memory.'})


@app.route('/api/device')
def device():
    return jsonify({'device': DEVICE_TYPE})


if __name__ == '__main__':
    migrate_firebase_once()
    print(f"\nVesper web GUI running ({DEVICE_TYPE.upper()}) — open http://localhost:5000 in your browser")
    print("Voice UI at / — classic UI at /classic\n")
    app.run(host='127.0.0.1', port=5000, debug=False)
