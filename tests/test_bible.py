import os
import sys
import flask

REPO = r'C:\Users\LIFE HOPE CENTER\AppData\Local\Temp\opencode\ecb-app'

# Make bible.py importable for the direct module test
sys.path.insert(0, REPO)
import bible


def _check(label, cond):
    status = 'PASS' if cond else 'FAIL'
    print('  [%s] %s' % (status, label))
    return cond


def main():
    results = []

    print('Bible module (direct DB queries):')
    results.append(_check('languages include en/tl', {'en', 'tl'} == {l['code'] for l in bible.list_languages()}))
    results.append(_check('search "john" finds John (43)', any(b['number'] == 43 and b['osis'] == 'John' for b in bible.search_books('john', lang='en'))))
    results.append(_check('get_reference John 3:16 (en)', bible.get_reference('John 3:16', lang='en') is not None))
    results.append(_check('get_reference Gen 1:1 (tl)', bible.get_reference('Gen 1:1', lang='tl') is not None))
    d = bible.get_reference('John 3:16-17', lang='en')
    results.append(_check('range John 3:16-17 -> 2 verses', d is not None and len(d['verses']) == 2))
    results.append(_check('bad ref returns None', bible.get_reference('zzz 99:1', lang='en') is None))

    print('Bible UI wiring in index.html:')
    src = open(os.path.join(REPO, 'templates', 'index.html'), encoding='utf-8').read()
    results.append(_check('bible-search-row present', 'bible-search-row' in src))
    results.append(_check('bible-query input present', 'bible-query' in src))
    results.append(_check('bible-lang-select present', 'bible-lang-select' in src))
    results.append(_check('Insert Verse button present', 'insertBibleVerse' in src))
    results.append(_check('bibleSuggest function present', 'function bibleSuggest' in src))
    results.append(_check('insertBibleVerse function present', 'async function insertBibleVerse' in src))
    results.append(_check('calls /api/bible/verse', '/api/bible/verse' in src))
    results.append(_check('calls /api/bible/search', '/api/bible/search' in src))

    print('server_entry wiring:')
    se = open(os.path.join(REPO, 'server_entry.py'), encoding='utf-8').read()
    results.append(_check('imports bible module', 'import bible' in se))
    results.append(_check('calls bible.init_app(app)', 'bible.init_app(app)' in se))

    print('spec wiring:')
    spec = open(os.path.join(REPO, 'LeiturgiaServer.spec'), encoding='utf-8').read()
    results.append(_check('bundles bible_en.db', 'bible_en.db' in spec))
    results.append(_check('bundles bible_tl.db', 'bible_tl.db' in spec))
    results.append(_check('hiddenimport bible', "'bible'," in spec))

    failed = results.count(False)
    print()
    if failed:
        print('RESULT: %d of %d checks FAILED' % (failed, len(results)))
        return 1
    print('RESULT: all %d checks PASSED' % len(results))
    return 0


if __name__ == '__main__':
    sys.exit(main())
