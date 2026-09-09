"""Small synthetic counterexample probe; not a calibrated retrieval threshold.

Run with PYTHONPATH=. and a cached model via HF_HOME, with hub offline enabled.
"""
import json
import math

from sb.embeddings import encoder_session, resolve_encoder

QUERIES = ['일정', '회의 일정이 언제야?', '비용은 얼마야?', '배포 서버 주소는?']
DOCUMENTS = ['회의는 월요일', '다음 만남은 수요일', '비용은 만원', '배포는 금요일',
             '서버 주소는 아직 정하지 않았다']


def main() -> None:
    encoder = resolve_encoder()
    with encoder_session(encoder) as session:
        vectors = session.encode(QUERIES + DOCUMENTS)
    rows = []
    for i, query in enumerate(QUERIES):
        scores = []
        for j, document in enumerate(DOCUMENTS):
            a, b = vectors[i], vectors[len(QUERIES) + j]
            cosine = sum(x * y for x, y in zip(a, b, strict=True)) / math.sqrt(
                sum(x * x for x in a) * sum(y * y for y in b))
            scores.append({'document': document, 'cosine': cosine})
        rows.append({'query': query, 'scores': scores})
    print(json.dumps({'model': encoder.identity.model_id, 'revision': encoder.identity.revision,
                      'synthetic': True, 'rows': rows}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
