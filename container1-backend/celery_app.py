import os
from celery import Celery

# Configurazione Celery per l'elaborazione dei task
celery_broker_host = os.environ.get('CELERY_BROKER_HOST', 'localhost')
celery_broker_port = os.environ.get('CELERY_BROKER_PORT', '6379')

redis_broker_url = f"redis://{celery_broker_host}:{celery_broker_port}/1"
redis_backend_url = f"redis://{celery_broker_host}:{celery_broker_port}/2"

print(f"Configurazione Celery: Broker={redis_broker_url}, Backend={redis_backend_url}")

# Creazione dell'istanza Celery
celery = Celery(
    'video_processing_tasks',
    broker=redis_broker_url,
    backend=redis_backend_url,
    include=['tasks'] 
)

# Configurazione delle opzioni di Celery
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Europe/Rome',
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)

if __name__ == '__main__':
    celery.start()