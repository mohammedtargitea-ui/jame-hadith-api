FROM python:3.12-slim

WORKDIR /app

# القاعدة (1.4GB) تُجلب عند البناء من الـDataset العام مباشرة —
# لا حاجة لرفعها مع الكود في أي منصة (HF Space / Oracle / أي مضيف Docker).
# إن حدَّثت القاعدة في الـDataset فحدِّث الرقم أدناه (حجم الملف بالبايت).
# jama_hadith_v2.sqlite = النسخة المحسّنة بفهرس مغط records(book_id, rtype, rec_id)
# (تسريع مسار /books من ~9 ثوانٍ إلى أجزاء من الثانية على الخطة المجانية).
#
# درس إخفاقات 2026-11-20 (سبب update_failed المتكررة):
#   1) كانت هذه الخطوة بعد «COPY app.py» فكان أي تعديل على app.py يُبطل ذاكرة
#      طبقات دوكر ويُعيد تنزيل 1.4GB مع كل رفع — الآن التنزيل أول خطوة بعد
#      WORKDIR فتعديلات الكود والمتطلبات لا تمسه إطلاقاً.
#   2) محاولة تنزيل واحدة كانت تفشل خلال ثوانٍ عند تقييد HuggingFace للتزاحم —
#      الآن خمس محاولات متباعدة تلقائياً (15/30/45/60 ثانية) قبل الاستسلام.
RUN ok=0; for i in 1 2 3 4 5; do \
      if python -c "import urllib.request, os, sys; \
          urllib.request.urlretrieve('https://huggingface.co/datasets/MoChihab/jame-alhadith/resolve/main/jama_hadith_v2.sqlite', 'jama_hadith.sqlite'); \
          sz = os.path.getsize('jama_hadith.sqlite'); \
          print('DB size:', sz); \
          sys.exit(0 if sz == 1460117504 else 1)"; then ok=1; break; fi; \
      echo "محاولة تنزيل القاعدة $i/5 فشلت — إعادة بعد $((i*15)) ثانية"; \
      sleep $((i*15)); \
    done; [ "$ok" = "1" ]

ENV JAMA_DB=/app/jama_hadith.sqlite

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# مهم: رندر يحدد منفذ الخدمة بمتغير البيئة PORT (10000 افتراضيًا)،
# وHF Spaces يحدده 7860 — لذلك نقرأه من البيئة ولا نثبّته أبدًا.
# (تثبيت 7860 في CMD هو ما أفشل عمليات النشر الثلاث في 2026-11-20)
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]
