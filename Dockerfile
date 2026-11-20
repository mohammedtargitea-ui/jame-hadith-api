FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

# سحب القاعدة المصلحة من سلّة البيانات العامة في هوغنغ (مرة واحدة عند البناء)
# مع التحقق من الحجم بالبايت لضمان أنها النسخة المصلحة ذات الكيانات
ARG DATA_BASE=https://huggingface.co/datasets/MoChihab/jame-hadith-data/resolve/main
RUN curl -fsSL -o /app/jama_hadith.sqlite "$DATA_BASE/jama_hadith.sqlite" \
 && python3 -c "import os; s=os.path.getsize('/app/jama_hadith.sqlite'); print('DB size:', s); assert s == 1447137280, 'unexpected size %s' % s" \
 && ls -la /app

ENV PORT=10000
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
