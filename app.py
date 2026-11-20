#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
واجهة برمجية عربية لقاعدة «جامع الحديث النبوي الشريف» — شبكة المدارس الإسلامية
نقل حرفي كامل: النصوص المشكولة، التصنيفات، عناقيد التخريج، تراجم الرواة، الجرح والتعديل.

تشغيل محلي:  uvicorn app:app --host 0.0.0.0 --port 7860
"""
import re
import sqlite3
import json
import os
from fastapi import FastAPI, HTTPException, Query

def _find_db():
    """تحديد مسار القاعدة: متغير البيئة، ثم مجلد api، ثم جذر المستودع، ثم مجلد التشغيل."""
    env = os.environ.get("JAMA_DB")
    if env and os.path.exists(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (
        os.path.join(here, "jama_hadith.sqlite"),
        os.path.join(here, "..", "jama_hadith.sqlite"),
        "jama_hadith.sqlite",
    ):
        if os.path.exists(c):
            return os.path.abspath(c)
    return os.path.join(here, "jama_hadith.sqlite")

DB_PATH = _find_db()

HARAKAT = re.compile(r'[\u064B-\u065F\u0670\u0640]')

def normalize(t: str) -> str:
    t = HARAKAT.sub('', t or '')
    t = t.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ٱ', 'ا')
    t = t.replace('ى', 'ي').replace('ة', 'ه')
    return t

def get_db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.execute("PRAGMA cache_size=-20000")
    return con

db = get_db()

# ─── مدير جلسات خادم MCP (يُملأ في أسفل الملف بعد بناء الخادم إن توفرت الحزمة) ───
_mcp_session = None

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(_app):
    if _mcp_session is not None:
        async with _mcp_session:
            yield
    else:
        yield

app = FastAPI(
    title="جامع الحديث النبوي الشريف — API",
    lifespan=_lifespan,
    description="""
قاعدة بيانات موحدة مبنية على برنامج **«جامع الحديث النبوي الشريف»** من شبكة المدارس الإسلامية (madarisweb.com)
بنقل حرفي كامل من ملفات البرنامج الأصلية، دون أي تدخل:

- **401 كتابًا مسندًا** + 4 كتب أطراف (تحفة الأشراف، أطراف مسند أحمد، نصب الراية، تلخيص الحبير)
- **521,566 حديثًا وأثرًا** مشكولًا كما ورد في البرنامج
- **التصنيفات الأصلية**: مرفوع / موقوف / مقطوع / قدسي (+ موقوف له حكم الرفع)
- **كيانات الحديث (التخريجات)**: 54,200 كيانًا يربط روايات الحديث الواحد على مستوى
  كل المصادر مع اتحاد المتن (أو أحد أجزائه) والصحابي — كما ربطها مختصو البرنامج
  (هذه هي «تخريجات الحديث» في نافذة البرنامج: `/takhrij/{rec_id}`)
- **عناقيد الأطراف**: 53,871 عنقودًا تربط روايات الحديث بكتب الأطراف الأربعة مع نص طرفه
- **13,784 ترجمة راوٍ** مع 53,571 حكم جرح وتعديل
- **270,794 إسنادًا** و 3.4 مليون رابط راوٍ بالأحاديث
- **بحث كامل غير متحسس للتشكيل** (اكتب بلا تشكيل وستجد النص المشكول)،
  وعلامات الترقيم لا تضر، ومطابقة العبارة المتتابعة مقدَّمة على تفرق الكلمات

ملاحظة: التصنيفات وكيانات الحديث (التخريجات) وعناقيد الأطراف وأحكام الأسانيد كما وضعها مختصو البرنامج — لا يد للذكاء الاصطناعي فيها.
""",
    version="1.3.0",
)


def fts_words(q: str) -> list:
    """كلمات الاستعلام بعد التطبيع وتنقية علامات الترقيم."""
    t = ''.join(ch if ch.isalnum() else ' ' for ch in normalize(q or ''))
    return t.split()


def fts_query(q: str) -> str:
    """تحويل استعلام حر إلى عبارة FTS آمنة: كلمات مقتبسة موصولة بـ AND.

    علامات الترقيم (، , ؛ : ؟ « » …) تُحال فراغات كما يفعل مُقطِّع الفهرس unicode61،
    فلو بقيت في الاستعلام لبُحث عن رمز «،» نفسه كلمةً فيُصفَّر كل نتيجة
    (كما وقع مع «في الإسلام ، فيفرق» قديمًا)."""
    words = fts_words(q)
    if not words:
        raise HTTPException(400, "الاستعلام فارغ")
    return ' AND '.join(f'"{w}"' for w in words)


def row_to_dict(row):
    return {k: row[k] for k in row.keys()} if row is not None else None


def excerpt(text: str, q: str, width: int = 220) -> str:
    """مقتطف حول أول تطابق (بعد التطبيع)."""
    if not text:
        return ""
    nt = normalize(text)
    qt = ''.join(ch if ch.isalnum() else ' ' for ch in normalize(q or ''))
    words = [w for w in qt.split() if w]
    pos = -1
    for w in words:
        pos = nt.find(w)
        if pos >= 0:
            break
    if pos < 0:
        return text[:width]
    ratio = pos / max(1, len(nt))
    p = int(ratio * len(text))
    start = max(0, p - width // 3)
    return ("…" if start > 0 else "") + text[start:start + width] + ("…" if start + width < len(text) else "")


# ==================== المسارات ====================

@app.get("/", tags=["عام"])
def root():
    meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta")}
    return {
        "اسم القاعدة": "جامع الحديث النبوي الشريف — شبكة المدارس الإسلامية",
        "المصدر": "الملف الرسمي من madarisweb.com (نقل حرفي كامل)",
        "إحصاءات": meta,
        "التوثيق": "/docs",
        "المسارات": {
            "الكتب": "/books",
            "كتاب": "/books/{book_id}?page=1",
            "حديث": "/hadith/{rec_id}",
            "بحث": "/search?q=...&kind=مرفوع&book=سنن الدارمي",
            "تخريجات الحديث": "/takhrij/{rec_id}",
            "عنقود أطراف": "/cluster/{cluster_id}",
            "كيان حديث": "/entity/{entity_id}",
            "راوٍ": "/narrator/{rowah_id}",
            "بحث الرواة": "/narrators/search?q=...",
            "إسناد": "/isnad/{asn_id}",
            "إحصاءات": "/stats",
            "الصحة": "/health",
        },
    }


@app.get("/health", tags=["عام"])
def health():
    """فحص الصحة — لرندر (Health Check Path) وروبوتات الإيقاظ (UptimeRobot).

    خفيف فوري: استعلام واحد على جدول meta الصغير لا يقرب جداول الملايين،
    فيصلح للنقر كل 5 دقائق دون إثقال المعالج المجاني.
    حقل version يميز النسخة المنتشرة بلمحة واحدة بعد أي نشر جديد."""
    try:
        db_ok = db.execute("SELECT 1 FROM meta LIMIT 1").fetchone() is not None
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "version": app.version}


# تخزين مؤقت: أرقام الإحصاءات ثابتة لكل نسخة من القاعدة (تُحسب مرة واحدة فقط).
# قبل هذا التخزين كانت كل زيارة تعيد 12 استعلام COUNT على ملايين الصفوف
# (~10–16 ثانية على المعالج المجاني في Render).
_stats_cache = None


@app.get("/stats", tags=["عام"])
def stats():
    global _stats_cache
    if _stats_cache is None:
        q = lambda s: db.execute(s).fetchone()[0]
        _stats_cache = {
            "الكتب": q("SELECT COUNT(*) FROM books"),
            "الأحاديث والآثار": q("SELECT COUNT(*) FROM records WHERE rtype='hadith'"),
            "نصوص الأطراف": q("SELECT COUNT(*) FROM records WHERE rtype='taraf'"),
            "عناوين الأبواب": q("SELECT COUNT(*) FROM records WHERE rtype='chapter'"),
            "كيانات الحديث (التخريجات)": q("SELECT COUNT(*) FROM entities"),
            "روايات مرتبطة بكيانات الحديث": q("SELECT COUNT(*) FROM entity_members"),
            "عناقيد الأطراف": q("SELECT COUNT(*) FROM clusters"),
            "الرواة": q("SELECT COUNT(*) FROM narrators"),
            "أحكام الجرح والتعديل": q("SELECT COUNT(*) FROM narrator_rulings"),
            "الأسانيد": q("SELECT COUNT(*) FROM asaneed"),
            "الأحكام على الأحاديث": q("SELECT COUNT(*) FROM record_rulings"),
            "تعليقات المحققين": q("SELECT COUNT(*) FROM record_comments"),
            "التصنيفات": {r["kind"]: r["c"] for r in db.execute(
                "SELECT kind, COUNT(*) c FROM records WHERE rtype='hadith' AND kind IS NOT NULL GROUP BY kind")},
        }
    return _stats_cache


@app.get("/books", tags=["الكتب"])
def books():
    rows = db.execute("""
        SELECT book_id, name, author, book_type, tabaqa, author_dod, hadith_count, n_records, n_hadith
        FROM books ORDER BY book_id""").fetchall()
    return {"العدد": len(rows), "الكتب": [row_to_dict(r) for r in rows]}


@app.get("/books/{book_id}", tags=["الكتب"])
def book(book_id: int, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
         rtype: str = Query("hadith", description="hadith | chapter | taraf | all")):
    b = db.execute("SELECT * FROM books WHERE book_id=?", (book_id,)).fetchone()
    if not b:
        raise HTTPException(404, "الكتاب غير موجود")
    cond = "" if rtype == "all" else "AND rtype=?"
    args = [book_id] + ([rtype] if rtype != "all" else [])
    total = db.execute(f"SELECT COUNT(*) FROM records WHERE book_id=? {cond}", args).fetchone()[0]
    rows = db.execute(f"""
        SELECT rec_id, serial, rtype, kind, text FROM records
        WHERE book_id=? {cond} ORDER BY rec_id LIMIT ? OFFSET ?""",
        args + [size, (page - 1) * size]).fetchall()
    return {
        "الكتاب": row_to_dict(b),
        "الإجمالي": total,
        "الصفحة": page,
        "النتائج": [row_to_dict(r) for r in rows],
    }


@app.get("/hadith/{rec_id}", tags=["الأحاديث"])
def hadith(rec_id: int):
    r = db.execute("SELECT * FROM records WHERE rec_id=?", (rec_id,)).fetchone()
    if not r:
        raise HTTPException(404, "السجل غير موجود")
    d = row_to_dict(r)
    d["الكتاب"] = row_to_dict(db.execute(
        "SELECT book_id, name, author FROM books WHERE book_id=?", (r["book_id"],)).fetchone())
    d["الرواة"] = [row_to_dict(x) for x in db.execute("""
        SELECT rn.rowah_id, n.summary_name, rn.ctx, rn.ord FROM record_narrators rn
        LEFT JOIN narrators n ON n.rowah_id = rn.rowah_id
        WHERE rn.rec_id=? ORDER BY rn.ord""", (rec_id,))]
    d["الأحكام"] = [x["ruling"] for x in db.execute(
        "SELECT ruling FROM record_rulings WHERE rec_id=?", (rec_id,))]
    d["التعليقات"] = [x["comment"] for x in db.execute(
        "SELECT comment FROM record_comments WHERE rec_id=?", (rec_id,))]
    clusters = json.loads(d["cluster_ids"]) if d["cluster_ids"] else []
    d["العناقيد"] = []
    for cid in clusters:
        cl = db.execute("SELECT * FROM clusters WHERE cluster_id=?", (cid,)).fetchone()
        if cl:
            d["العناقيد"].append(row_to_dict(cl))
    if clusters:
        cid = clusters[0]
        d["روايات_العنقود_الأساسي"] = [
            row_to_dict(x) for x in db.execute("""
                SELECT r.rec_id, r.serial, r.kind, b.name AS الكتاب
                FROM cluster_members cm JOIN records r ON r.rec_id=cm.rec_id
                JOIN books b ON b.book_id=r.book_id
                WHERE cm.cluster_id=? AND cm.is_primary=1 AND r.rtype='hadith'
                ORDER BY r.rec_id""", (cid,))]
    # تخريجات الحديث: كيانات المتن التي ينتمي إليها السجل
    entities = json.loads(d["entity_ids"]) if d["entity_ids"] else []
    d["كيانات_الحديث"] = []
    for eid in entities:
        n = db.execute("SELECT n_members FROM entities WHERE entity_id=?", (eid,)).fetchone()
        if n:
            d["كيانات_الحديث"].append({"entity_id": eid, "عدد_الروايات": n["n_members"]})
    if entities:
        d["التخريجات_على_مستوى_المصادر"] = [
            row_to_dict(x) for x in db.execute("""
                SELECT DISTINCT r.rec_id, r.serial, r.kind, b.name AS الكتاب, r.text
                FROM entity_members em JOIN records r ON r.rec_id=em.rec_id
                JOIN books b ON b.book_id=r.book_id
                WHERE em.entity_id IN (%s) AND r.rtype='hadith'
                ORDER BY r.rec_id""" % ",".join("?" * len(entities)), entities)]
    return d


@app.get("/search", tags=["البحث"])
def search(q: str, kind: str = Query(None, description="مرفوع | موقوف | مقطوع | قدسي"),
           book: str = Query(None, description="اسم الكتاب (جزء من الاسم)"),
           rtype: str = Query("hadith", description="hadith | taraf | all"),
           page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    """بحث حر في نصوص الأحاديث والأطراف — غير متحسس للتشكيل والهمزات وعلامات الترقيم.
    ترتيب النتائج: مطابقة «العبارة المتتابعة» (الكلمات بالترتيب نفسه متجاورة)
    مقدَّمة على مطابقة «كل الكلمات» وإن تفرقت في النص."""
    words = fts_words(q)
    if not words:
        raise HTTPException(400, "الاستعلام فارغ")
    fts_q = ' AND '.join(f'"{w}"' for w in words)
    conds = []
    args = []
    if rtype != "all":
        conds.append("r.rtype=?")
        args.append(rtype)
    if kind:
        conds.append("r.kind=?")
        args.append(kind)
    if book:
        conds.append("b.name LIKE ?")
        args.append(f"%{book}%")
    where = (" AND " + " AND ".join(conds)) if conds else ""
    # CROSS JOIN يمنع مخطِّط SQLite (قبل الإصدار 3.53) من مسح جدول records
    # كاملًا (521 ألف صف) وفحص كل صف ضد الفهرس — خطة تستغرق ~10 ثوانٍ لكل
    # استعلام — ويُجبر فهرس FTS5 على قيادة الاستعلام (أجزاء من الثانية).
    # لا يغيّر النتائج في شيء (INNER JOIN داخلي بكل الأحوال).
    base = f"""
        FROM records_fts f
        CROSS JOIN records r ON r.rec_id=f.rowid
        CROSS JOIN books b ON b.book_id=r.book_id
        WHERE records_fts MATCH ? {where}"""
    total = db.execute(f"SELECT COUNT(*) FROM (SELECT f.rowid {base} LIMIT 20000)",
                       [fts_q] + args).fetchone()[0]

    # (أ) مطابقة العبارة المتتابعة: كل كلمات الاستعلام بالترتيب نفسه متجاورة في النص
    phrase_q = '"' + ' '.join(words) + '"' if len(words) > 1 else None
    phrase_ids = []
    if phrase_q and total:
        n_ph = db.execute(f"SELECT COUNT(*) FROM (SELECT f.rowid {base} LIMIT 20000)",
                          [phrase_q] + args).fetchone()[0]
        if 0 < n_ph <= 5000:
            phrase_ids = [x[0] for x in db.execute(
                f"SELECT f.rowid {base} ORDER BY r.rec_id LIMIT 5000",
                [phrase_q] + args).fetchall()]
    phrase_set = set(phrase_ids)

    # (ب) تقطيع الصفحة: نتائج العبارة أولًا ثم باقي المطابقات بترتيب الكتب
    start = (page - 1) * size
    end = start + size
    if start < len(phrase_ids):
        head = phrase_ids[start:end]
        bag_from, bag_to = 0, end - len(phrase_ids)
    else:
        head = []
        bag_from, bag_to = start - len(phrase_ids), end - len(phrase_ids)
    tail = []
    if bag_to > 0:
        excl = ""
        bag_args = [fts_q] + args
        if phrase_set:
            excl = " AND r.rec_id NOT IN (SELECT rowid FROM records_fts WHERE records_fts MATCH ?)"
            bag_args.append(phrase_q)
        tail = [x[0] for x in db.execute(f"""
            SELECT f.rowid {base} {excl}
            ORDER BY r.rec_id LIMIT ? OFFSET ?""",
            bag_args + [max(0, bag_to - bag_from), max(0, bag_from)]).fetchall()]

    page_ids = head + tail
    out = []
    if page_ids:
        rows = db.execute(f"""
            SELECT r.rec_id, r.serial, r.rtype, r.kind, r.text, b.name AS الكتاب
            FROM records r JOIN books b ON b.book_id=r.book_id
            WHERE r.rec_id IN ({','.join('?' * len(page_ids))})""",
            page_ids).fetchall()
        by_id = {r["rec_id"]: r for r in rows}
        for rid in page_ids:
            r = by_id.get(rid)
            if r is None:
                continue
            d = row_to_dict(r)
            d["مطابقة"] = "عبارة متتابعة" if rid in phrase_set else "كل الكلمات"
            d["مقتطف"] = excerpt(r["text"], q)
            out.append(d)
    return {"الاستعلام": q, "الإجمالي": total,
            "مطابقة_العبارة_المتتابعة": len(phrase_ids),
            "الصفحة": page, "النتائج": out}


@app.get("/takhrij/{rec_id}", tags=["التخريج"])
def takhrij(rec_id: int, size: int = Query(100, ge=1, le=500)):
    """نافذة «تخريجات الحديث» كما في البرنامج: مكررات الحديث الحالي على مستوى جميع
    مصادر البرنامج، مع اتحاد المتن (أو أحد أجزائه) والصحابي راوي الحديث.

    هذا الربط صنعه مختصو البرنامج يدويًا (روابط كيانات المتن)، فهو يلتقط الروايات
    مختلفة الألفاظ أيضًا (مثل «أن يتقنه»/«أن يحكمه») التي لا يلتقطها البحث النصي.
    """
    r = db.execute("SELECT * FROM records WHERE rec_id=?", (rec_id,)).fetchone()
    if not r:
        raise HTTPException(404, "السجل غير موجود")
    entities = json.loads(r["entity_ids"]) if r["entity_ids"] else []
    out = {
        "rec_id": rec_id,
        "الكتاب": db.execute("SELECT name FROM books WHERE book_id=?", (r["book_id"],)).fetchone()["name"],
        "عدد_الأحاديث": len(entities),
        "الكيانات": [],
        "الأطراف": [],
    }
    seen = set()
    total = 0
    for eid in entities:
        n = db.execute("SELECT n_members FROM entities WHERE entity_id=?", (eid,)).fetchone()
        rows = db.execute("""
            SELECT r.rec_id, r.serial, r.kind, b.name AS الكتاب, r.text
            FROM entity_members em JOIN records r ON r.rec_id=em.rec_id
            JOIN books b ON b.book_id=r.book_id
            WHERE em.entity_id=? AND r.rtype='hadith'
            ORDER BY r.rec_id LIMIT ?""", (eid, size)).fetchall()
        group = {"entity_id": eid, "عدد_الروايات": n["n_members"] if n else 0, "الروايات": []}
        for x in rows:
            d = row_to_dict(x)
            d["مقتطف"] = excerpt(x["text"], "")
            group["الروايات"].append(d)
            if x["rec_id"] not in seen:
                seen.add(x["rec_id"])
                total += 1
        out["الكيانات"].append(group)
    out["عدد_الظهورات"] = total
    # عناقيد الأطراف (إن وجدت) — كما في نافذة التخريج بالبرنامج أيضًا
    clusters = json.loads(r["cluster_ids"]) if r["cluster_ids"] else []
    for cid in clusters:
        cl = db.execute("SELECT * FROM clusters WHERE cluster_id=?", (cid,)).fetchone()
        if not cl:
            continue
        taraf = [row_to_dict(x) for x in db.execute("""
            SELECT ct.taraf_rec_id, ct.taraf_text, b.name AS المصدر
            FROM cluster_taraf ct
            JOIN records r ON r.rec_id=ct.taraf_rec_id JOIN books b ON b.book_id=r.book_id
            WHERE ct.cluster_id=?""", (cid,))]
        members = [row_to_dict(x) for x in db.execute("""
            SELECT r.rec_id, r.serial, r.kind, b.name AS الكتاب
            FROM cluster_members cm JOIN records r ON r.rec_id=cm.rec_id
            JOIN books b ON b.book_id=r.book_id
            WHERE cm.cluster_id=? AND r.rtype='hadith'
            ORDER BY r.rec_id""", (cid,))]
        out["الأطراف"].append({
            "cluster_id": cid,
            "نص_الطرف": taraf,
            "الروايات": members,
        })
    return out


@app.get("/entity/{entity_id}", tags=["التخريج"])
def entity(entity_id: int, size: int = Query(100, ge=1, le=500)):
    """كيان الحديث: كل رواياته على مستوى مصادر البرنامج (المكررات بتوحيد المتن/جزئه والصحابي)."""
    e = db.execute("SELECT * FROM entities WHERE entity_id=?", (entity_id,)).fetchone()
    if not e:
        raise HTTPException(404, "الكيان غير موجود")
    rows = db.execute("""
        SELECT r.rec_id, r.serial, r.kind, b.name AS الكتاب, r.text
        FROM entity_members em JOIN records r ON r.rec_id=em.rec_id
        JOIN books b ON b.book_id=r.book_id
        WHERE em.entity_id=? AND r.rtype='hadith'
        ORDER BY r.rec_id LIMIT ?""", (entity_id, size)).fetchall()
    return {
        "entity_id": entity_id,
        "عدد_الروايات": e["n_members"],
        "الروايات": [row_to_dict(x) for x in rows],
    }


@app.get("/cluster/{cluster_id}", tags=["التخريج"])
def cluster(cluster_id: int):
    """عنقود الأطراف: نص الطرف من كتب الأطراف الأربعة + كل رواياته عبر الكتب (كما في نافذة التخريج بالبرنامج)."""
    cl = db.execute("SELECT * FROM clusters WHERE cluster_id=?", (cluster_id,)).fetchone()
    if not cl:
        raise HTTPException(404, "العنقود غير موجود")
    taraf = [row_to_dict(x) for x in db.execute("""
        SELECT ct.taraf_rec_id, ct.taraf_text, b.name AS المصدر
        FROM cluster_taraf ct
        JOIN records r ON r.rec_id=ct.taraf_rec_id JOIN books b ON b.book_id=r.book_id
        WHERE ct.cluster_id=?""", (cluster_id,))]
    primary = [row_to_dict(x) for x in db.execute("""
        SELECT r.rec_id, r.serial, r.kind, r.text, b.name AS الكتاب
        FROM cluster_members cm JOIN records r ON r.rec_id=cm.rec_id
        JOIN books b ON b.book_id=r.book_id
        WHERE cm.cluster_id=? AND cm.is_primary=1 AND r.rtype='hadith'
        ORDER BY r.rec_id""", (cluster_id,))]
    related = [row_to_dict(x) for x in db.execute("""
        SELECT r.rec_id, r.serial, r.kind, r.text, b.name AS الكتاب
        FROM cluster_members cm JOIN records r ON r.rec_id=cm.rec_id
        JOIN books b ON b.book_id=r.book_id
        WHERE cm.cluster_id=? AND cm.is_primary=0 AND r.rtype='hadith'
        ORDER BY r.rec_id""", (cluster_id,))]
    return {
        "cluster_id": cluster_id,
        "عدد_الروايات_الأساسية": cl["n_primary"],
        "عدد_المرتبطة": cl["n_related"],
        "نص_الطرف": taraf,
        "الروايات": primary,
        "الروايات_المرتبطة": related,
    }


@app.get("/narrator/{rowah_id}", tags=["الرواة"])
def narrator(rowah_id: int):
    """ترجمة الراوي كاملة كما في البرنامج + أحكام الجرح والتعديل."""
    n = db.execute("SELECT * FROM narrators WHERE rowah_id=?", (rowah_id,)).fetchone()
    if not n:
        raise HTTPException(404, "الراوي غير موجود")
    d = row_to_dict(n)
    d["الجرح_والتعديل"] = [row_to_dict(x) for x in db.execute(
        "SELECT scholar, ruling FROM narrator_rulings WHERE rowah_id=?", (rowah_id,))]
    return d


@app.get("/narrators/search", tags=["الرواة"])
def narrators_search(q: str, size: int = Query(20, ge=1, le=100)):
    """بحث في أسماء الرواة (الاسم المشهور أو الكاملة)."""
    nq = normalize(q)
    like = f"%{nq}%"
    rows = db.execute("""
        SELECT rowah_id, summary_name, view_name, dod, hadith_freq FROM narrators
        WHERE replace(replace(replace(replace(replace(summary_name,'أ','ا'),'إ','ا'),'آ','ا'),'ى','ي'),'ة','ه') LIKE ?
        ORDER BY hadith_freq DESC LIMIT ?""",
        (like, size)).fetchall()
    if not rows:
        rows = db.execute("""
            SELECT rowah_id, summary_name, view_name, dod, hadith_freq FROM narrators
            WHERE view_name LIKE ? ORDER BY hadith_freq DESC LIMIT ?""", (f"%{q}%", size)).fetchall()
    return {"الاستعلام": q, "النتائج": [row_to_dict(r) for r in rows]}


@app.get("/isnad/{asn_id}", tags=["الأسانيد"])
def isnad(asn_id: int):
    a = db.execute("SELECT * FROM asaneed WHERE asn_id=?", (asn_id,)).fetchone()
    if not a:
        raise HTTPException(404, "الإسناد غير موجود")
    return row_to_dict(a)


@app.get("/hadith/{rec_id}/isnads", tags=["الأسانيد"])
def hadith_isnads(rec_id: int):
    """أسانيد الحديث: سلسلة معرفات الرواة وأسماؤهم بالترتيب."""
    r = db.execute("SELECT rec_id FROM records WHERE rec_id=?", (rec_id,)).fetchone()
    if not r:
        raise HTTPException(404, "السجل غير موجود")
    rows = db.execute("""
        SELECT rn.rowah_id, n.summary_name, n.view_name, rn.ctx, rn.ord
        FROM record_narrators rn LEFT JOIN narrators n ON n.rowah_id=rn.rowah_id
        WHERE rn.rec_id=? ORDER BY rn.ord""", (rec_id,)).fetchall()
    return {"rec_id": rec_id, "سلسلة_الرواة": [row_to_dict(x) for x in rows]}


# ═════════════════════════════════════════════════════════════════════════════
# خادم MCP — ربط المساعدات الذكية (Claude بخطته المجانية، GLM، Cursor…) بالقاعدة
# عن بُعد عبر الرابط:  https://<الخدمة>.onrender.com/mcp   بلا مفاتيح ولا تنصيب.
# الأدوات أدناه تلتف على دوال الواجهة نفسها أعلاه (بحث/تخريج/رواة) مع اختصار
# النتائج بما يناسب نافذة سياق المساعدات. وإن تعذّر استيراد الحزمة لأي سبب
# عملت واجهة REST طبيعية دون أي تأثر (القسم كله داخل try/except).
# ═════════════════════════════════════════════════════════════════════════════
try:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "جامع الحديث النبوي الشريف",
        instructions=(
            "قاعدة «جامع الحديث النبوي الشريف» (شبكة المدارس الإسلامية madarisweb.com): "
            "521,566 حديثًا وأثرًا مشكولًا في 401 كتابًا مسندًا، مع التخريجات وعناقيد "
            "الأطراف وتراجم الرواة وأحكام الجرح والتعديل. البحث غير متحسس للتشكيل "
            "والهمزات وعلامات الترقيم. لتخريج حديث: نادِ takhrij_by_phrase بعبارة من "
            "متنه، أو search_hadith للبحث، ثم get_hadith للمتن الكامل وget_takhrij "
            "للتخريج المفصل وget_narrator لترجمة الراوي."
        ),
        streamable_http_path="/",
    )

    def _short(t, n=220):
        t = t or ""
        return t if len(t) <= n else t[:n] + " …"

    @mcp.tool()
    def search_hadith(q: str, limit: int = 5, kind: str = None, rtype: str = "hadith") -> dict:
        """بحث حر في نصوص الأحاديث والآثار والأطراف — غير متحسس للتشكيل والهمزات.
        يعيد لكل نتيجة المعرّف (rec_id) والكتاب والتصنيف ومقتطفًا حول موضع المطابقة؛
        استعمل المعرّف لاحقًا مع get_hadith أو get_takhrij.
        kind اختياري: مرفوع | موقوف | مقطوع | قدسي — rtype: hadith | taraf | all."""
        limit = max(1, min(int(limit or 5), 10))
        r = search(q=q, kind=kind, book=None, rtype=rtype, page=1, size=limit)
        items = [
            {k: it.get(k) for k in ("rec_id", "serial", "rtype", "kind", "الكتاب", "مطابقة", "مقتطف")}
            for it in r.get("النتائج", [])
        ]
        return {"الاستعلام": q, "الإجمالي": r.get("الإجمالي"), "النتائج": items}

    @mcp.tool()
    def takhrij_by_phrase(q: str, limit: int = 3) -> dict:
        """تخريج حديث بعبارة من متنه مباشرة: يبحث عن أقرب المطابقات ثم يعيد لكل واحدة
        ملخص تخريجها — الكتب التي روته وعدد رواياتها وظهوراتها — لتمييز الحديث ولفظه."""
        limit = max(1, min(int(limit or 3), 5))
        s = search(q=q, kind=None, book=None, rtype="hadith", page=1, size=limit)
        out = []
        for it in s.get("النتائج", []):
            rec_id = it.get("rec_id")
            if not rec_id:
                continue
            t = takhrij(rec_id=rec_id, size=50)
            books, n_total = [], 0
            for e in t.get("الكيانات", []):
                n_total += int(e.get("عدد_الروايات") or 0)
                for r in (e.get("الروايات") or []):
                    b = r.get("الكتاب")
                    if b and b not in books:
                        books.append(b)
            out.append({
                "rec_id": rec_id, "الكتاب": it.get("الكتاب"), "kind": it.get("kind"),
                "المقتطف": _short(it.get("مقتطف") or it.get("text"), 260),
                "عدد_الظهورات": t.get("عدد_الظهورات"),
                "عدد_روايات_التخريج": n_total,
                "الكتب_التي_روته": books[:25],
            })
        return {"الاستعلام": q, "الإجمالي": s.get("الإجمالي"), "التخاريج": out}

    @mcp.tool()
    def get_hadith(rec_id: int) -> dict:
        """المتن الكامل لحديث أو أثر بمعرّفه (rec_id)، مع رواة إسناده والتصنيف
        والعناقيد وكيانات التخريج المرتبطة به والأحكام والتعليقات إن وجدت."""
        h = hadith(rec_id=rec_id)
        if isinstance(h, dict) and isinstance(h.get("text"), str):
            h["text"] = _short(h["text"], 4000)
        return h

    @mcp.tool()
    def get_takhrij(rec_id: int, size: int = 30) -> dict:
        """تخريج السجل كاملًا: كيانات التخريج (كل من روى الحديث من الكتب مع رواياتهم)
        وأطرافه في كتب الأطراف الأربعة مع نص الطرف."""
        size = max(1, min(int(size or 30), 60))
        t = takhrij(rec_id=rec_id, size=size)
        ents = [
            {
                "entity_id": e.get("entity_id"),
                "عدد_الروايات": e.get("عدد_الروايات"),
                "الروايات": [
                    {k: r.get(k) for k in ("rec_id", "kind", "الكتاب", "مقتطف")}
                    for r in (e.get("الروايات") or [])
                ],
            }
            for e in t.get("الكيانات", [])
        ]
        atr = []
        for a in t.get("الأطراف", []):
            txt = a.get("نص_الطرف")
            if isinstance(txt, list) and txt:
                first = txt[0]
                txt = first.get("taraf_text") if isinstance(first, dict) else str(first)
            atr.append({
                "cluster_id": a.get("cluster_id"),
                "نص_الطرف": _short(txt, 300),
                "عدد_روايات_العنقود": len(a.get("الروايات") or []),
            })
        return {
            "rec_id": t.get("rec_id"), "الكتاب": t.get("الكتاب"),
            "عدد_الظهورات": t.get("عدد_الظهورات"),
            "عدد_الكيانات": len(ents), "الكيانات": ents, "الأطراف": atr,
        }

    @mcp.tool()
    def search_narrator(q: str, size: int = 10) -> dict:
        """البحث عن راوٍ بالاسم — يعيد المعرّف واسمه الشائع وسنة وفاته وعدد أحاديثه."""
        return narrators_search(q=q, size=max(1, min(int(size or 10), 20)))

    @mcp.tool()
    def get_narrator(rowah_id: int) -> dict:
        """ترجمة راوٍ كاملة بمعرّفه: أسماؤه وطبقته وشيوخه وأحكام الجرح والتعديل."""
        return narrator(rowah_id=rowah_id)

    @mcp.tool()
    def db_stats() -> dict:
        """أرقام القاعدة: عدد الكتب والأحاديث والآثار والأطراف والتخريجات
        والرواة وأحكام الجرح والتعديل والأسانيد."""
        return stats()

    # تطبيق MCP الفرعي (Starlette) يُلحق بمسار /mcp بعد كل مسارات REST
    _mcp_asgi = mcp.streamable_http_app()
    _mcp_session = mcp.session_manager.run()
    app.mount("/mcp", _mcp_asgi)
except Exception as _mcp_err:  # pragma: no cover
    print("[MCP] خادم MCP غير متاح — واجهة REST تعمل طبيعيًا:", _mcp_err)
