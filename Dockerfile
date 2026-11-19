FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

# سحب القواعد من سلّة البيانات العامة في هوغنغ (مرة واحدة عند البناء، تُحفظ في الصورة)
ARG DATA_BASE=https://huggingface.co/datasets/MoChihab/jame-hadith-data/resolve/main
RUN curl -fsSL -o /app/rawi_index.db "$DATA_BASE/rawi_index.db" \
 && curl -fsSL -o /app/jame_analysis.db "$DATA_BASE/jame_analysis.db" \
 && curl -fsSL -o /app/jame_hadith.db "$DATA_BASE/jame_hadith.db" \
 && ls -la /app

ENV PORT=10000
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
