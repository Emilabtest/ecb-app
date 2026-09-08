"""bible.py - Bible verse search/input for Leiturgia (additive; pymod untouched).

Mirrors the sourceless ``hymnal`` module's public API but reads the ``books`` /
``verses`` tables from ``data/bible_<lang>.db`` (English / Tagalog Bibles).
Exposed to the running Flask app via ``init_app(app)``, like live_input and
server_version, so ``app.pyc`` is never recompiled.

Routes added:
    GET /api/bible/languages              -> [{code, label}]
    GET /api/bible/search?q=...&lang=...  -> book/verse autocomplete
    GET /api/bible/verse?book=..&chapter=..&verse=..&lang=.. -> verse text
"""
import os
import sqlite3


_HERE = os.path.dirname(os.path.abspath(__file__))

LANG_LABELS = {"en": "English", "tl": "Tagalog"}


def _resolve(name):
    """Return the first existing path under the module dir or the PyInstaller
    _MEIPASS bundle dir, matching the pattern used by server_entry."""
    cands = [os.path.join(_HERE, name)]
    _meipass = getattr(__import__('sys'), '_MEIPASS', None)
    if _meipass and _meipass != _HERE:
        cands.append(os.path.join(_meipass, name))
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


def _db_path(lang):
    """Path to the bible database for a language code, or None if missing."""
    for root in (_HERE, getattr(__import__('sys'), '_MEIPASS', _HERE)):
        p = os.path.join(root, 'data', 'bible_%s.db' % lang)
        if os.path.exists(p):
            return p
        p2 = os.path.join(root, 'pymod', 'data', 'bible_%s.db' % lang)
        if os.path.exists(p2):
            return p2
    return os.path.join(_HERE, 'data', 'bible_%s.db' % lang)


def _connect(lang):
    path = _db_path(lang)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def list_languages():
    import glob
    langs = []
    for root in (_HERE, getattr(__import__('sys'), '_MEIPASS', _HERE)):
        pattern = os.path.join(root, 'data', 'bible_*.db')
        for path in sorted(glob.glob(pattern)):
            code = os.path.basename(path)[len('bible_'):-len('.db')]
            langs.append({"code": code, "label": LANG_LABELS.get(code, code.upper())})
        pattern2 = os.path.join(root, 'pymod', 'data', 'bible_*.db')
        for path in sorted(glob.glob(pattern2)):
            code = os.path.basename(path)[len('bible_'):-len('.db')]
            langs.append({"code": code, "label": LANG_LABELS.get(code, code.upper())})
    # de-dup
    seen = set()
    out = []
    for l in langs:
        if l['code'] in seen:
            continue
        seen.add(l['code'])
        out.append(l)
    return out


def search_books(query, limit=8, lang='en'):
    """Return up to `limit` books whose name/osis contains the query."""
    q = (query or '').strip()
    if not q:
        return []
    con = _connect(lang)
    try:
        cur = con.execute(
            "SELECT number, osis, name FROM books "
            "WHERE LOWER(name) LIKE LOWER(?) OR LOWER(osis) LIKE LOWER(?) "
            "ORDER BY number LIMIT ?",
            ('%' + q + '%', '%' + q + '%', limit))
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []
    finally:
        con.close()


def get_reference(reference, lang='en'):
    """Given a reference like 'John 3:16' or 'Gen 1:1-5' return the verse text(s).

    Returns {"reference": ..., "verses": [{"chapter":..,"verse":..,"text":..}]}
    or None when the reference is not found / malformed.
    """
    import re
    ref = (reference or '').strip()
    if not ref:
        return None
    # "Book C:V" or "Book C:V-V2" -- book may be a number or a name/osis.
    m = re.match(r'^(.+?)\s+(\d+)\s*:\s*(\d+)(?:\s*-\s*(\d+))?$', ref)
    if not m:
        m = re.match(r'^(.+?)\s+(\d+)\s*:\s*(\d+)$', ref)
    if not m:
        return None
    book_part, chapter, verse, verse2 = m.group(1), int(m.group(2)), int(m.group(3)), None
    if m.lastindex and m.lastindex >= 4 and m.group(4):
        verse2 = int(m.group(4))

    con = _connect(lang)
    try:
        # Resolve the book by number or name/osis.
        book = None
        if book_part.isdigit():
            cur = con.execute("SELECT number FROM books WHERE number = ?", (int(book_part),))
            row = cur.fetchone()
            if row:
                book = int(row['number'])
        if book is None:
            cur = con.execute(
                "SELECT number FROM books WHERE LOWER(name) = LOWER(?) OR LOWER(osis) = LOWER(?) "
                "ORDER BY number LIMIT 1",
                (book_part, book_part))
            row = cur.fetchone()
            if row:
                book = int(row['number'])
        # Loose match: handle singular/plural & abbreviations (e.g. "Psalm" -> "Psalms",
        # "Gen" -> "Genesis", "Rev" -> "Revelation") by prefix/partial match on name/osis.
        if book is None:
            cur = con.execute(
                "SELECT number FROM books WHERE LOWER(name) LIKE LOWER(?) OR LOWER(osis) = LOWER(?) "
                "ORDER BY number LIMIT 1",
                ('%' + book_part + '%', book_part))
            row = cur.fetchone()
            if row:
                book = int(row['number'])
        if book is None:
            return None

        end = verse2 if verse2 is not None else verse
        cur = con.execute(
            "SELECT chapter, verse, text FROM verses "
            "WHERE book_number = ? AND chapter = ? AND verse BETWEEN ? AND ? "
            "ORDER BY verse",
            (book, chapter, verse, end))
        rows = cur.fetchall()
        if not rows:
            return None
        verses = [{"chapter": r['chapter'], "verse": r['verse'],
                   "text": "%d:%d %s" % (r['chapter'], r['verse'], r['text'])} for r in rows]
        return {"reference": ref, "verses": verses}
    except Exception:
        return None
    finally:
        con.close()


def init_app(app):
    """Register the Bible search routes on the running Flask app (additive)."""
    from flask import jsonify, request

    @app.route('/api/bible/languages')
    def _bible_languages():
        return jsonify(list_languages())

    @app.route('/api/bible/search')
    def _bible_search():
        q = request.args.get('q', '').strip()
        lang = request.args.get('lang', 'en')
        results = search_books(q, limit=8, lang=lang)
        return jsonify(results)

    @app.route('/api/bible/verse')
    def _bible_verse():
        ref = (request.args.get('ref') or '').strip()
        lang = request.args.get('lang', 'en')
        data = get_reference(ref, lang)
        if data is None:
            return jsonify({'ok': False, 'message': 'Reference not found'}), 404
        data['ok'] = True
        return jsonify(data)
