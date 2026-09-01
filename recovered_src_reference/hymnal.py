# Source Generated with Decompyle++
# File: hymnal.pyc (Python 3.12)

'''
hymnal.py ΓÇö Query the SDA Hymnal SQLite database (695 hymns).

DB schema (Hymns table):
  _id, number, title, refrain, refrain2,
  verse1 ΓÇª verse7, section, subsection

Returns stanzas as: [{"number": N, "type": "verse"|"refrain", "lines": [...]}]
The refrain appears once; _hymn_slide_sequence() in generator.py handles interleaving.
'''
import logging
import sqlite3
import os
import re
logger = logging.getLogger('leiturgia.hymnal')
VERSE_COLS = [
    'verse1',
    'verse2',
    'verse3',
    'verse4',
    'verse5',
    'verse6',
    'verse7']

def _db_path(lang = 'en'):
    return os.path.join(os.path.dirname(__file__), 'data', f'''hymns_{lang}.db''')


def _row_to_stanzas(row):
    '''Convert a DB row into our stanza list format.'''
    stanzas = []
    for i, col in enumerate(VERSE_COLS, start = 1):
        text = row[col]
        if not text:
            continue
        
        try:
            for l in text.splitlines():
                if not l.strip():
                    continue
        l = enumerate([
            'refrain',
            'refrain2'], start = 1)
        
        try:
            for l in text.splitlines():
                if not l.strip():
                    continue
        l = enumerate(VERSE_COLS, start = 1)


        lines = []
        l = l
        stanzas.append({
            'number': i,
            'type': 'verse',
            'lines': lines })
    for i, col in enumerate([
        'refrain',
        'refrain2'], start = 1):
        text = row[col]
        if not text:
            continue
        
        try:
            for l in text.splitlines():
                if not l.strip():
                    continue
        l = enumerate(VERSE_COLS, start = 1)

        lines = []
        l = l
        stanzas.append({
            'number': i,
            'type': 'refrain',
            'lines': lines })
    return stanzas
    
    try:
        for l in text.splitlines():
            if not l.strip():
                continue
    l = enumerate([
        'refrain',
        'refrain2'], start = 1)
    
    try:
        for l in text.splitlines():
            if not l.strip():
                continue
    l = enumerate(VERSE_COLS, start = 1)




def _connect(lang = 'en'):
    con = sqlite3.connect(_db_path(lang))
    con.row_factory = sqlite3.Row
    return con


def get_by_number(number, lang = 'en'):
    '''
    Fetch a hymn by its number (1ΓÇô695).
    Returns {"number": N, "title": "...", "stanzas": [...]} or None.
    '''
    with _connect(lang) as con:
        row = con.execute('SELECT * FROM Hymns WHERE number = ?', (number,)).fetchone()
    if not row:
        return None
    return {
        'number': row['number'],
        'title': row['title'],
        'stanzas': _row_to_stanzas(row) }


def get_by_title(title, lang = 'en'):
    '''
    Search hymns by title using progressively looser matching:
      1. Exact (case-insensitive)
      2. Starts-with
      3. Contains all words
      4. Contains any word (picks closest by word-overlap score)
    Returns the best match or None.
    '''
    q = title.strip().lower()
    with _connect(lang) as con:
        rows = con.execute('SELECT * FROM Hymns ORDER BY number').fetchall()
    
    def score(row):
        t = row['title'].lower()
        if t == q:
            return 100
        if t.startswith(q):
            return 80
        words = re.findall('\\w+', q)
        if all(( w in t for w in words )):
            return 60
        matched = sum(( 1 for w in words if w in t ))
        return (matched / max(len(words), 1)) * 40

    best = max(rows, key = score)
    if score(best) < 1:
        return None
    return {
        'number': best['number'],
        'title': best['title'],
        'stanzas': _row_to_stanzas(best) }


def search_titles(query, limit = 10, lang = 'en'):
    '''
    Return up to `limit` hymns whose title contains the query string.
    Each result: {"number": N, "title": "..."}
    '''
    q = f'''%{query.strip()}%'''
    with _connect(lang) as con:
        rows = con.execute('SELECT number, title FROM Hymns WHERE LOWER(title) LIKE LOWER(?) ORDER BY number LIMIT ?', (q, limit)).fetchall()
    
    try:
        for r in rows:
            pass
    r = rows

    r = r
    return []
    
    try:
        for r in rows:
            pass
    r = rows

# WARNING: Decompyle incomplete


def search_by_number_prefix(prefix, limit = 8, lang = 'en'):
    pattern = f'''{prefix}%'''
    with _connect(lang) as con:
        rows = con.execute('SELECT number, title FROM Hymns WHERE CAST(number AS TEXT) LIKE ? ORDER BY number LIMIT ?', (pattern, limit)).fetchall()
    
    try:
        for r in rows:
            pass
    r = rows

    r = r
    return []
    
    try:
        for r in rows:
            pass
    r = rows

# WARNING: Decompyle incomplete


