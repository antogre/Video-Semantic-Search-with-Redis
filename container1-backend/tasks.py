import os
import time
import json
import uuid
import numpy as np
import requests
import traceback

# Importa l'istanza Celery definita in celery_app.py
from celery_app import celery

# Import dei moduli
try:
    from clip4clip_module import get_video_embedding
    EMBEDDING_AVAILABLE = True
except ImportError:
    EMBEDDING_AVAILABLE = False
    def get_video_embedding(path): raise ImportError("Modulo Embedding non disponibile")

try:
    from google.oauth2 import service_account
    import google.auth.transport.requests
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False
    print("ATTENZIONE [Worker]: Librerie Google Auth non trovate. Il batch non funzionerà.")

import redis

# Costanti e Configurazioni
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
VECTOR_DIMENSION = 512
METRIC_TYPE = os.environ.get('METRIC_TYPE', 'L2').upper()
COLLECTION_NAME = "video_embeddings"
EXTERNAL_API_TARGET = 'https://external-api.vidoser.io' # Assicurati che sia corretto
SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '/app/service_account.json')

redis_host = os.environ.get('REDIS_HOST')
redis_port = int(os.environ.get('REDIS_PORT', 6379))

# Cache Globale per le credenziali nel worker
AUTH_CREDENTIALS_WORKER = None

def get_auth_token_for_task(force_refresh=False):
    """Gestisce il token di autenticazione per l'API esterna."""
    global AUTH_CREDENTIALS_WORKER
    if not GOOGLE_AUTH_AVAILABLE:
        raise ConnectionError("Librerie Google Auth non disponibili.")
    
    # Carica le credenziali
    if AUTH_CREDENTIALS_WORKER is None:
        try:
            if not os.path.exists(SERVICE_ACCOUNT_FILE):
                raise FileNotFoundError(f"File service_account.json non trovato in {SERVICE_ACCOUNT_FILE}")
            AUTH_CREDENTIALS_WORKER = service_account.IDTokenCredentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, target_audience=EXTERNAL_API_TARGET
            )
            print("[Worker Task] Credenziali SA caricate.")
        except Exception as e:
            print(f"[Worker Task] ERRORE CRITICO caricamento credenziali SA: {e}")
            raise ConnectionError(f"Impossibile caricare credenziali SA: {e}")

    # Aggiorna il token se è scaduto o se forzato
    if force_refresh or not AUTH_CREDENTIALS_WORKER.valid:
        print("[Worker Task] Aggiornamento token di autenticazione...")
        try:
            request = google.auth.transport.requests.Request()
            AUTH_CREDENTIALS_WORKER.refresh(request)
            print("[Worker Task] Token aggiornato.")
        except Exception as e:
            print(f"[Worker Task] Errore durante l'aggiornamento del token: {e}")
            raise ConnectionError(f"Errore aggiornamento token: {e}")
            
    return AUTH_CREDENTIALS_WORKER.token

# Task Celery per processare una pagina di video
@celery.task(bind=True, max_retries=2, default_retry_delay=60,
              autoretry_for=(requests.exceptions.RequestException, ConnectionError))
def process_video_batch_page(self, page_num, limit_per_page):
    """Task Celery che processa una singola pagina di video dall'API esterna."""
    print(f"[Task {self.request.id}] Avvio processamento per Pagina: {page_num}")
    page_processed_count, page_failed_count = 0, 0
    page_download_time, page_embedding_time, page_indexing_time = 0.0, 0.0, 0.0
    
    page_videos = []

    try:
        token = get_auth_token_for_task()
        api_page_url = f'{EXTERNAL_API_TARGET}/v1/videos?onlyWithFeedback=true&limit={limit_per_page}&page={page_num}&orderBy=createdAt&orderDirection=DESC'
        headers = {'accept': 'application/json', 'Authorization': f'Bearer {token}'}
        
        response = requests.get(api_page_url, headers=headers, timeout=45)
        response.raise_for_status() # Lancia un errore per status >= 400
        
        page_videos = response.json().get('docs', [])
        print(f"[Task {self.request.id}] Pagina {page_num}: Trovati {len(page_videos)} video da processare.")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code in [401, 403]:
            print(f"[Task {self.request.id}] Errore di autenticazione ({e.response.status_code}). Riprovo con un nuovo token...")
            get_auth_token_for_task(force_refresh=True) # Forza l'aggiornamento del token
        raise self.retry(exc=e, countdown=10) # Riprova la task
    except Exception as e:
        print(f"[Task {self.request.id}] Errore imprevisto durante la chiamata API: {e}")
        traceback.print_exc()
        raise self.retry(exc=e)

    if not page_videos:
        print(f"[Task {self.request.id}] Nessun video trovato per la pagina {page_num}. Task completata.")
        return {'page': page_num, 'processed': 0, 'failed': 0, 'status': 'NO_VIDEOS'}

    redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=False)

    # Processa ogni video nella pagina
    for index, video_info in enumerate(page_videos):
        video_url = video_info.get('src')
        video_id_str = str(video_info.get('id', uuid.uuid4()))
        temp_filename = f"task_{self.request.id}_{video_id_str}.mp4"
        temp_save_path = os.path.join(UPLOAD_FOLDER, temp_filename)

        if not video_url:
            print(f"[Task {self.request.id}] URL MANCANTE per video ID {video_id_str}. Skipping.")
            page_failed_count += 1
            continue

        try:
            print(f"[Task {self.request.id}] Processing {index+1}/{len(page_videos)}: ID {video_id_str}")
            
            dl_start = time.perf_counter()
            with requests.get(video_url, stream=True, timeout=(10, 180)) as r:
                r.raise_for_status()
                with open(temp_save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            page_download_time += (time.perf_counter() - dl_start)

            emb_start = time.perf_counter()
            embedding = get_video_embedding(temp_save_path)
            vector_np = np.array(embedding.tolist(), dtype=np.float32)
            page_embedding_time += (time.perf_counter() - emb_start)
            
            metadata = {k: v for k, v in video_info.items() if v is not None}
            metadata['timestamp'] = time.time()
            
            idx_start = time.perf_counter()
            key = f"{COLLECTION_NAME}:{video_id_str}"
            redis_payload = {'vector': vector_np.tobytes(), 'metadata': json.dumps(metadata)}
            redis_client.hset(key, mapping=redis_payload)
            page_indexing_time += (time.perf_counter() - idx_start)

            page_processed_count += 1
        except Exception as e_vid:
            print(f"[Task {self.request.id}] ERRORE processamento video {video_id_str}: {e_vid}")
            page_failed_count += 1
        finally:
            if os.path.exists(temp_save_path):
                os.remove(temp_save_path)

    print(f"[Task {self.request.id}] Pagina {page_num} completata. Success: {page_processed_count}, Failed: {page_failed_count}")
    return {
        'page': page_num, 'processed': page_processed_count, 'failed': page_failed_count,
        'total_download_ms': round(page_download_time * 1000, 2),
        'total_embedding_ms': round(page_embedding_time * 1000, 2),
        'total_indexing_ms': {'redis': round(page_indexing_time * 1000, 2)}
    }
