"""Local Ollama embeddings only. No source is sent to a cloud service."""
import json
import math
from urllib.request import Request, build_opener, ProxyHandler


def semantic_rank(query, scripts, model='embeddinggemma', limit=10):
    chunks = []
    for script in scripts:
        source = script.get('source', '')
        for start in range(0, min(len(source), 24000), 3000):
            chunks.append({'path': script['path'], 'offset': start, 'text': source[start:start+3000]})
            if len(chunks) >= 128:
                break
        if len(chunks) >= 128:
            break
    if not chunks:
        return {'matches': [], 'note': 'No readable script sources in this batch'}
    request = Request('http://127.0.0.1:11434/api/embed',
        data=json.dumps({'model': model, 'input': [query] + [c['text'] for c in chunks]}).encode(),
        headers={'Content-Type': 'application/json'})
    with build_opener(ProxyHandler({})).open(request, timeout=120) as response:
        vectors = json.loads(response.read())['embeddings']
    if len(vectors) != len(chunks) + 1:
        raise ValueError('Embedding provider returned an unexpected vector count')
    def cosine(a, b):
        if len(a) != len(b):
            raise ValueError('Embedding dimensions differ')
        return sum(x*y for x, y in zip(a, b)) / max(1e-12, math.sqrt(sum(x*x for x in a)*sum(x*x for x in b)))
    for chunk, vector in zip(chunks, vectors[1:]):
        chunk['score'] = cosine(vectors[0], vector)
    return {'matches': sorted(chunks, key=lambda c: c['score'], reverse=True)[:max(1, min(limit, 30))],
            'indexed_chunks': len(chunks), 'scope': 'Only the requested source batch, capped at 128 chunks'}
