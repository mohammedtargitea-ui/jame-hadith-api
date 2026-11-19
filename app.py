# -*- coding: utf-8 -*-
"""
jame-hadith-server — خادم واجهة برمجية محلي لموسوعة جامع الحديث النبوي.
يستنسخ واجهة التطبيق المنشور سابقًا على مودال بنفس المسارات:
  GET /hadith/{hid}            — نص الحديث وبيانات كتابه
  GET /hadith/{hid}/isnads     — سلاسل إسناد الحديث بأسماء الرواة ومعرفاتهم
  GET /narrator/{id}           — بطاقة الراوي مع أحكام العلماء فيه
  GET /narrators/search?q=     — البحث في الرواة الـ13,784
  GET /search?q=&book=&limit=  — البحث النصي الكامل في 530,966 حديثًا
  GET /health                  — فحص صحة الخادم والقاعدتين

القواعد تُقرأ للقراءة فقط. ترتيب البحث عن كل قاعدة:
  1) متغير البيئة (JAME_TEXT_DB، JAME_ANALYSIS_DB، JAME_RAWI_DB)
  2) الملف بجوار هذا السكربت (وضع الاستضافة السحابية والفهرس المصغّر)
  3) الموضع الافتراضي على القرص دي (وضع هذا الجهاز)

التشغيل المحلي:
  python -m uvicorn app:app --host 127.0.0.1 --port 8000
التشغيل السحابي (مساحة هوغنغ فيس): يشغَّل تلقائيًا على المنفذ 7860.
"""
import os
import re
import sqlite3
from contextlib import closing
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

_HERE = os.path.dirname(os.path.abspath(__file__))


def _resolve_db(env_var: str, filename: str, fallback: str) -> str:
    value = os.environ.get(env_var)
    if value and os.path.exists(value):
        return value
    candidate = os.path.join(_HERE, filename)
    if os.path.exists(candidate):
        return candidate
    return fallback


TEXT_DB = _resolve_db("JAME_TEXT_DB", "jame_hadith.db", r"D:\jame_hadith.db")
ANALYSIS_DB = _resolve_db("JAME_ANALYSIS_DB", "jame_analysis.db", r"D:\jame_analysis.db")
JW_RAWI_DB = _resolve_db("JAME_RAWI_DB", "rawi_index.db",
                         r"D:\Jawami-AlKalem-GPT\jawami_alkalem.db")

# مفتاح اختياري: إن ضُبط عبر متغير البيئة API_KEY فلط كل نداء واجهة أن يحمل
# نفس المفتاح في معامل key (مثال: /hadith/148020?key=XXXX) — تستخدم في النشر العلني.
API_KEY = os.environ.get("API_KEY", "").strip()


def _guard(key: Optional[str] = Query(None)) -> None:
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="مفتاح الواجهة غير صحيح أو ناقص")


_GUARD = [Depends(_guard)] if API_KEY else []

app = FastAPI(
    title="jame-hadith API",
    description="واجهة موسوعة جامع الحديث النبوي: النصوص والأسانيد والرواة والأحكام",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── التطبيع: حذف التشكيل وتوحيد الهمزات (نفس منطق الخادم المحلي) ──
DIAC = {ord(c): None for c in
        "\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0670\u0640\u06d6\u06d7\u06d8\u06d9\u06da\u06db\u06dc"}
HAMZA = {0x0623: 0x0627, 0x0625: 0x0627, 0x0622: 0x0627, 0x0671: 0x0627, 0x0649: 0x064a}
NORM = {**DIAC, **HAMZA}


def dev(s: str) -> str:
    return (s or "").translate(NORM)


def open_text() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{TEXT_DB.replace(chr(92), '/')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def open_ana() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{ANALYSIS_DB.replace(chr(92), '/')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.create_function("NORM", 1, lambda s: dev(s or ""))
    return con


def open_jw() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{JW_RAWI_DB.replace(chr(92), '/')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def fts_match(query: str) -> Optional[str]:
    d = dev(query).strip()
    words = [w for w in d.split() if w]
    if not words:
        return None
    return " ".join('"%s*"' % w for w in words)


def parse_dashed(value: str):
    """يفكك سلاسل بصيغة -عنصر-عنصر- إلى قائمة نظيفة."""
    if not value:
        return []
    return [part for part in value.strip().strip("-").split("-") if part]


@app.get("/")
def root():
    return {
        "service": "jame-hadith API",
        "version": "1.0.0",
        "endpoints": [
            "/hadith/{hid}",
            "/hadith/{hid}/isnads",
            "/narrator/{id}",
            "/narrators/search?q=",
            "/search?q=&book=&limit=",
            "/health",
        ],
    }


@app.get("/health")
def health():
    out = {"status": "ok", "dbs": {}}
    checks = (("text", TEXT_DB, open_text, "hadiths"),
              ("analysis", ANALYSIS_DB, open_ana, "narrators"),
              ("rawi_engine", JW_RAWI_DB, open_jw, "rawi"))
    for name, path, opener, table in checks:
        try:
            with closing(opener()) as con:
                n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            out["dbs"][name] = {"path": path, "ok": True, "rows": n}
        except Exception as ex:
            out["status"] = "degraded"
            out["dbs"][name] = {"path": path, "ok": False, "error": str(ex)}
    return out


@app.get("/hadith/{hid}", dependencies=_GUARD)
def get_hadith(hid: int):
    with closing(open_text()) as con:
        r = con.execute(
            "SELECT h.hid, h.book_id, h.num, h.text, b.title, b.death "
            "FROM hadiths h JOIN books b ON b.id = h.book_id WHERE h.hid = ?", (hid,)
        ).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail=f"لا يوجد حديث برقم {hid}")
        hadith_count = con.execute(
            "SELECT COUNT(*) FROM hadiths WHERE book_id = ?", (r["book_id"],)).fetchone()[0]
    return {
        "hid": r["hid"],
        "book_id": r["book_id"],
        "num": r["num"],
        "text": r["text"],
        "book": {"id": r["book_id"], "title": r["title"], "author_death": r["death"],
                 "hadiths_count": hadith_count},
    }


@app.get("/hadith/{hid}/isnads", dependencies=_GUARD)
def get_isnads(hid: int):
    """سلاسل إسناد الحديث، ومع كل راوٍ معرفاته في جدول جوامع الكلم ورتبته وسنة وفاته.

    ملاحظة: معرّفات rawi_ids تشير إلى جدول الرواة في قاعدة المحرك
    (jawami_alkalem.db) لا إلى جدول الرواة في قاعدة التحليل.
    """
    with closing(open_ana()) as con:
        chains = con.execute(
            "SELECT id, rawi_id, narrators, rawi_ids FROM chains WHERE rawi_id = ?", (hid,)
        ).fetchall()
        if not chains:
            raise HTTPException(status_code=404, detail=f"لا توجد سلاسل إسناد للحديث {hid}")
        all_ids = set()
        out = []
        for c in chains:
            names = parse_dashed(c["narrators"])
            rids = [int(x) for x in parse_dashed(c["rawi_ids"]) if x.isdigit()]
            all_ids.update(rids)
            out.append({"chain_id": c["id"],
                        "isnad": " ← ".join(names),
                        "narrators": names,
                        "rawi_ids": rids})
    details = {}
    if all_ids:
        known = sorted(x for x in all_ids if 1 <= x <= 999999)
        step = 500
        with closing(open_jw()) as con:
            for i in range(0, len(known), step):
                chunk = known[i:i + step]
                marks = ",".join("?" * len(chunk))
                for row in con.execute(
                        f"SELECT rawi_id, name, alt_name, rank_text, wafat FROM rawi "
                        f"WHERE rawi_id IN ({marks})", chunk):
                    rid_int = int(row["rawi_id"])  # العمود مخزّن كنص في القاعدة
                    details[rid_int] = {
                        "rawi_id": rid_int, "name": row["name"],
                        "alt_name": row["alt_name"], "rank_text": row["rank_text"],
                        "wafat": row["wafat"]}
    for chain in out:
        chain["rawi_details"] = [details.get(rid) for rid in chain["rawi_ids"]]
    return {"hid": hid, "chains_count": len(chains), "chains": out}


@app.get("/narrator/{nid}", dependencies=_GUARD)
def get_narrator(nid: int):
    with closing(open_ana()) as con:
        r = con.execute("SELECT * FROM narrators WHERE id = ?", (nid,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail=f"لا يوجد راوٍ برقم {nid}")
        judgments = [{"scholar": row["scholar"], "judgment": row["judgment"]}
                     for row in con.execute(
                         "SELECT scholar, judgment FROM judgments WHERE rawi_id = ? ORDER BY id",
                         (nid,))]
        chains_count = con.execute(
            "SELECT COUNT(*) FROM chains WHERE rawi_id = ?", (nid,)).fetchone()[0]
    return {
        "narrator_id": r["id"],
        "full_name": r["full_name"],
        "name": r["name"],
        "kunya": r["kunya"],
        "laqab": r["laqab"],
        "nasab": r["nasab"],
        "shuhra": r["shuhra"],
        "view_name": r["view_name"],
        "birth": r["birth"],
        "death": r["death"],
        "judgments": judgments,
        "chains_count": chains_count,
    }


@app.get("/narrators/search", dependencies=_GUARD)
def search_narrators(q: str = Query(..., min_length=1, max_length=200),
                     limit: int = Query(10, ge=1, le=40)):
    nq = dev(q.strip())
    with closing(open_ana()) as con:
        rows = con.execute(
            "SELECT id, full_name, shuhra, birth, death FROM narrators "
            "WHERE NORM(full_name) LIKE ? OR NORM(name) LIKE ? OR NORM(shuhra) LIKE ? "
            "ORDER BY id LIMIT ?",
            (f"%{nq}%", f"%{nq}%", f"%{nq}%", limit)).fetchall()
        total = con.execute(
            "SELECT COUNT(*) FROM narrators "
            "WHERE NORM(full_name) LIKE ? OR NORM(name) LIKE ? OR NORM(shuhra) LIKE ?",
            (f"%{nq}%", f"%{nq}%", f"%{nq}%")).fetchone()[0]
    return {
        "query": q,
        "total_matches": total,
        "count_shown": len(rows),
        "results": [{"narrator_id": r["id"], "full_name": r["full_name"],
                     "shuhra": r["shuhra"], "birth": r["birth"], "death": r["death"]}
                    for r in rows],
    }


@app.get("/search", dependencies=_GUARD)
def search_hadith(q: str = Query(..., min_length=1, max_length=500),
                  book: Optional[str] = Query(None, max_length=200),
                  limit: int = Query(10, ge=1, le=50)):
    m = fts_match(q)
    if not m:
        raise HTTPException(status_code=400, detail="ادخل كلمات للبحث")
    sql = ("SELECT h.hid, h.num, h.text, b.title, b.id AS book_id, "
           "snippet(hadiths_fts, 0, '»', '«', '…', 20) AS snip "
           "FROM hadiths_fts f JOIN hadiths h ON h.hid = f.rowid "
           "JOIN books b ON b.id = h.book_id WHERE hadiths_fts MATCH ?")
    params = [m]
    if book:
        sql += " AND b.title LIKE ?"
        params.append(f"%{dev(book)}%")
    sql += " LIMIT ?"
    params.append(limit)
    with closing(open_text()) as con:
        rows = con.execute(sql, params).fetchall()
        total = None
        if len(m.split()) <= 2:
            csql = ("SELECT count(*) FROM hadiths_fts f JOIN hadiths h ON h.hid = f.rowid "
                    "JOIN books b ON b.id = h.book_id WHERE hadiths_fts MATCH ?")
            cparams = [m]
            if book:
                csql += " AND b.title LIKE ?"
                cparams.append(f"%{dev(book)}%")
            total = con.execute(csql, cparams).fetchone()[0]
    return {
        "query": q,
        "total_matches": total,
        "count_shown": len(rows),
        "results": [{"hid": r["hid"], "book_id": r["book_id"], "book": r["title"],
                     "num": r["num"], "snippet": r["snip"], "text": r["text"]}
                    for r in rows],
    }


# ── صفحة غراديو للاستضافة السحابية (تُتجاهل محليًا إن لم تكن غراديو مثبتة) ──
try:
    import gradio as gr

    with gr.Blocks(title="جامع الحديث — API") as _demo:
        gr.Markdown("## واجهة موسوعة جامع الحديث النبوي")
        gr.Markdown(
            "التوثيق التفاعلي على المسار `/docs`. "
            "المسارات: `/hadith/{hid}` و `/hadith/{hid}/isnads` و "
            "`/narrator/{id}` و `/narrators/search?q=` و `/search?q=` و `/health`"
        )
    app = gr.mount_gradio_app(app, _demo, path="/ui")
except ImportError:
    pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
