import os
import time
import json
import uuid
import numpy as np
import traceback
import math
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Import del modulo Task Celery
try:
    from celery_app import celery
    TASK_AVAILABLE = True
    print("Task Celery importata con successo.")
except ImportError:
    print("ATTENZIONE: Impossibile importare task Celery.")
    TASK_AVAILABLE = False

#Import deL CLIENT Redis e dei comandi RediSearch
import redis
try:
    from redis.commands.search.field import VectorField, TextField
    from redis.commands.search.indexDefinition import IndexDefinition, IndexType
    from redis.commands.search.query import Query
    REDIS_SEARCH_AVAILABLE = True
    print("Comandi RediSearch importati con successo.")
except ImportError:
    print("ATTENZIONE: Comandi RediSearch non trovati. Funzionalità Redis vettoriali disabilitate.")
    REDIS_SEARCH_AVAILABLE = False

# Import del modulo per l'estrazione degli embedding video e testo
try:
    from clip4clip_module import get_video_embedding, get_text_embedding
    EMBEDDING_MODULE_AVAILABLE = True
except ImportError:
    EMBEDDING_MODULE_AVAILABLE = False
    def get_video_embedding(path): raise NotImplementedError("Modulo Embedding non disponibile")
    def get_text_embedding(text): raise NotImplementedError("Modulo Embedding non disponibile")

# Configurazione Flask e Redis
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
VECTOR_DIMENSION = 512
METRIC_TYPE = os.environ.get('METRIC_TYPE', 'L2').upper()
COLLECTION_NAME = "video_embeddings"
redis_host = os.environ.get('REDIS_HOST', 'localhost')
redis_port = int(os.environ.get('REDIS_PORT', '6379'))

app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

redis_client = None
db_init_status = {}

def initialize_database():
    global redis_client, db_init_status
    print("--- Inizializzazione Database Redis per Flask API ---")
    if REDIS_SEARCH_AVAILABLE:
        try:
            print(f"[Flask Init] Tentativo connessione a Redis: host={redis_host}, port={redis_port}...")
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)
            r.ping()
            redis_client = r
            print("[Flask Init] Connessione a Redis OK.")
            
            redis_index_name = f"{COLLECTION_NAME}_idx"
            redis_doc_prefix = f"{COLLECTION_NAME}:"
            redis_schema = (
                VectorField("vector", "HNSW", { "TYPE": "FLOAT32", "DIM": VECTOR_DIMENSION, "DISTANCE_METRIC": METRIC_TYPE }, as_name="vector"),
                TextField("metadata", as_name="metadata"),
            )
            redis_index_def = IndexDefinition(prefix=[redis_doc_prefix], index_type=IndexType.HASH)
            
            try:
                r.ft(redis_index_name).info()
                print(f"[Flask Init] Indice Redis '{redis_index_name}' già esistente.")
            except redis.exceptions.ResponseError:
                print(f"[Flask Init] Creazione indice Redis '{redis_index_name}'...")
                r.ft(redis_index_name).create_index(fields=redis_schema, definition=redis_index_def)
                print(f"[Flask Init] Indice Redis '{redis_index_name}' creato.")

            db_init_status['redis'] = "OK"
            print("[Flask Init] Redis inizializzato per ricerca vettoriale.")
        except Exception as e:
            db_init_status['redis'] = f"ERROR: {e}"
            print(f"[Flask Init] Errore init Redis: {e}")
            traceback.print_exc()
    else:
        db_init_status['redis'] = "Skipped (Libreria Mancante)"
        print("[Flask Init] Redis VSS saltato (comandi RediSearch non disponibili).")
    
    print("--- Inizializzazione Database Flask Completata ---")

initialize_database()

# Controllo dello stato del database all'avvio
@app.route('/')
def home():
    return jsonify({
        'message': 'Embedding and Redis Search Service (Flask API) attivo!',
        'database_status': db_init_status
    })

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/upload', methods=['POST'])
def upload_video():
    if not EMBEDDING_MODULE_AVAILABLE:
        return jsonify({'error': 'Modulo Embedding non disponibile'}), 503
    if 'video' not in request.files:
        return jsonify({'error': 'Nessun file video ricevuto'}), 400

    file = request.files['video']
    original_video_id_str = file.filename
    if not original_video_id_str:
        return jsonify({'error': 'Nome file non valido'}), 400

    save_path = os.path.join(app.config['UPLOAD_FOLDER'], original_video_id_str)
    file.save(save_path)

    try:
        embedding = get_video_embedding(save_path)
        embedding_list = embedding.tolist()
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f"Errore estrazione embedding: {str(e)}"}), 500

# Creazione del metadata per Redis
    metadata = {
        'name': original_video_id_str,
        'url': f"/uploads/{original_video_id_str}", # URL per video locali
        'timestamp': time.time()
    }
    vector_np = np.array(embedding_list, dtype=np.float32)
    
    if db_init_status.get('redis') == "OK":
        try:
            key = f"{COLLECTION_NAME}:{original_video_id_str}"
            redis_payload = {'vector': vector_np.tobytes(), 'metadata': json.dumps(metadata)}
            redis_client.hset(key, mapping=redis_payload)
            return jsonify({'message': f'Video {original_video_id_str} processato.'}), 200
        except Exception as e:
            return jsonify({'error': f"Errore indicizzazione Redis: {e}"}), 500
    else:
        return jsonify({'error': "Servizio Redis non disponibile"}), 503

# ENDPOINT PER L'INDICIZZAZIONE BATCH
@app.route('/trigger_batch_index', methods=['POST'])
def trigger_batch_index():
    from tasks import process_video_batch_page 

    if not TASK_AVAILABLE:
       return jsonify({'error': 'Modulo Task Celery non disponibile.'}), 503
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body must be JSON'}), 400

    num_videos = data.get('num_videos', 10)
    start_page = data.get('start_page', 1)
    limit_per_page = 10 

    num_pages_to_process = math.ceil(num_videos / limit_per_page)
    end_page = start_page + num_pages_to_process

    task_ids = []
    for page in range(start_page, end_page):
        try:
            task = process_video_batch_page.delay(page, limit_per_page)
            task_ids.append(task.id)
        except Exception as e:
            return jsonify({'error': f'Errore invio task Celery: {e}'}), 500
            
    return jsonify({
        'message': f'Richiesta di indicizzazione batch avviata per {num_videos} video.',
        'task_ids': task_ids,
    }), 202

# ENDPOINT PER CONTROLLARE LO STATO DEI TASK
@app.route('/task_status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Controlla lo stato di un task Celery specifico."""
    if not TASK_AVAILABLE:
        return jsonify({'error': 'Servizio Celery non disponibile'}), 503
    
    task_result = celery.AsyncResult(task_id)
    
    response = {
        'task_id': task_id,
        'status': task_result.status,
        'result': None
    }
    
    if task_result.successful():
        response['result'] = task_result.get()
    elif task_result.failed():
        response['result'] = repr(task_result.info)
        
    return jsonify(response)

# ENDPOINT PER LA RICERCA DEI VIDEO
@app.route('/search', methods=['POST'])
def search_videos():
    if not EMBEDDING_MODULE_AVAILABLE:
        return jsonify({'error': 'Modulo Embedding non disponibile'}), 503
    
    data = request.get_json()
    query_text = data.get('query')
    k = data.get('k', 12)
    if not query_text:
        return jsonify({'error': 'Nessuna query fornita'}), 400

    try:
        start_embed_time = time.perf_counter()
        query_embedding = get_text_embedding(query_text)
        query_vector_np = np.array(query_embedding.tolist(), dtype=np.float32)
        embed_time = (time.perf_counter() - start_embed_time) * 1000
        
        search_results = []
        search_time = 0.0

        if db_init_status.get('redis') == "OK":
            start_search = time.perf_counter()
            try:
                redis_index_name = f"{COLLECTION_NAME}_idx"
                redis_query = (Query(f'*=>[KNN {k} @vector $query_vector AS vector_score]')
                               .return_fields("vector_score", "metadata")
                               .sort_by("vector_score", asc=(METRIC_TYPE == 'L2'))
                               .dialect(2))
                query_params = {"query_vector": query_vector_np.tobytes()}
                search_res = redis_client.ft(redis_index_name).search(redis_query, query_params)
                
                for doc in search_res.docs:
                    meta = json.loads(doc.metadata)
                    search_results.append({
                        'name': meta.get('name', doc.id),
                        'local_url': meta.get('url', ''),
                        'source_url': meta.get('src', ''), 
                        'similarity': float(doc.vector_score)
                    })
            except Exception as e:
                traceback.print_exc()
                return jsonify({'error': f'Errore durante la ricerca in Redis: {e}'}), 500
            end_search = time.perf_counter()
            search_time = round((end_search - start_search) * 1000, 2)
        else:
             return jsonify({'error': 'Servizio Redis non disponibile per la ricerca.'}), 503

        return jsonify({
            'query': query_text,
            'embedding_time_ms': round(embed_time, 2),
            'search_time_ms': search_time,
            'results': search_results
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f"Errore imprevisto durante la ricerca: {str(e)}"}), 500

# ENDPOINT PER OTTENERE STATISTICHE SUL DATABASE
@app.route('/db_stats', methods=['GET'])
def get_database_stats():
    stats = {}
    if db_init_status.get('redis') == "OK":
        try:
            redis_index_name = f"{COLLECTION_NAME}_idx"
            stats['redis'] = int(redis_client.ft(redis_index_name).info().get('num_docs', 0))
        except Exception as e:
            stats['redis'] = "Error"
    else:
        stats['redis'] = "N/A"
    return jsonify(stats)

if __name__ == '__main__':
    print("Avvio server Flask...")
    app.run(host='0.0.0.0', port=5000, debug=False)
