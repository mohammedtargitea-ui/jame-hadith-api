FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# القاعدة (1.4GB) تُجلب عند البناء من الـDataset العام مباشرة —
# لا حاجة لرفعها مع الكود في أي منصة (HF Space / Oracle / أي مضيف Docker).
# إن حدَّثت القاعدة في الـDataset فحدِّث الرقم أدناه (حجم الملف بالبايت).
RUN python -c "import urllib.request, os, sys; \
    urllib.request.urlretrieve('https://huggingface.co/datasets/MoChihab/jame-alhadith/resolve/main/jama_hadith.sqlite', 'jama_hadith.sqlite'); \
    sz = os.path.getsize('jama_hadith.sqlite'); \
    print('DB size:', sz); \
    sys.exit(0 if sz == 1447137280 else 1)"

ENV JAMA_DB=/app/jama_hadith.sqlite

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "2"]
