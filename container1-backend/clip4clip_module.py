import torch
from towhee import pipe, ops, DataCollection

# Pipeline per estrarre l'embedding del video
embedding_pipe = (
    pipe.input('video_path')
        .map('video_path', 'frames', ops.video_decode.ffmpeg(sample_type='uniform_temporal_subsample', args={'num_samples': 12}))
        .map('frames', 'embedding', ops.video_text_embedding.clip4clip(model_name='clip_vit_b32', modality='video'))
        .output('embedding')
)

# Pipeline per estrarre l'embedding del testo
text_embedding_pipe = (
    pipe.input('text')
        .map('text', 'embedding', ops.video_text_embedding.clip4clip(model_name='clip_vit_b32', modality='text'))
        .output('embedding')
)

# Funzioni per ottenere gli embedding video e testuali
def get_video_embedding(video_path):
    try:
        result = DataCollection(embedding_pipe(video_path)).to_list()
        embedding = result[0]['embedding']
        return embedding
    except Exception as e:
        raise RuntimeError(f"Errore durante l'estrazione dell'embedding video: {e}")

def get_text_embedding(text_query):
    try:
        result = DataCollection(text_embedding_pipe(text_query)).to_list()
        embedding = result[0]['embedding']
        return embedding
    except Exception as e:
        raise RuntimeError(f"Errore durante l'estrazione dell'embedding testuale: {e}")
