# Source Generated with Decompyle++
# File: app.pyc (Python 3.12)

import eventlet
eventlet.monkey_patch()
import logging
logging.basicConfig(level = logging.INFO, format = '%(asctime)s %(levelname)s %(name)s: %(message)s')
logging.getLogger('eventlet.wsgi.server').setLevel(logging.ERROR)
logger = logging.getLogger('leiturgia.program')
logger_socket = logging.getLogger('leiturgia.socket')
logger_media = logging.getLogger('leiturgia.media')
from flask import Flask, render_template, request, jsonify, send_file, session, redirect
from werkzeug.exceptions import HTTPException
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import os
import copy
import re
import requests
import uuid
import time
import glob
import subprocess
import ctypes
import tempfile
import hashlib
import sys
import shutil
from urllib.parse import quote as _url_quote
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
load_dotenv()
from hymnal import search_titles, get_by_title, get_by_number, search_by_number_prefix
from projection import ProjectionStateManager
from media_manager import list_media
import media_manager
from timer import TimerManager
from roles import RoleManager
from order_of_service import OrderOfServiceManager
from cloud_agent import agent as cloud_agent
from jsonio import atomic_write_json
from version import get_version
import updater
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 209715200
with open('config.json') as _f:
    _config = json.load(_f)
_log_level = getattr(logging, _config.get('log_level', 'INFO').upper(), logging.INFO)
logging.getLogger().setLevel(_log_level)
app.secret_key = _config['session_secret']
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours = _config.get('session_timeout_hours', 8))
_DEFAULT_PIN = '1234'
_DEFAULT_PIN_HASH = hashlib.sha256(_DEFAULT_PIN.encode()).hexdigest()

def _get_pin_hash():
    
    try:
        with open('config.json') as _f:
            _cfg = json.load(_f)
        if not _cfg.get('pin_hash'):
            _cfg.get('pin_hash')
        return str(_cfg.get('pin_hash'))
    except Exception:
        return _DEFAULT_PIN_HASH


socketio = SocketIO(app, cors_allowed_origins = '*', async_mode = 'eventlet')
limiter = Limiter(get_remote_address, app = app, default_limits = [])
proj = ProjectionStateManager()
timer = TimerManager()
roles = RoleManager()
oos = OrderOfServiceManager()
_active_item = {
    'program_id': None,
    'item_id': None,
    'allotted_seconds': 0,
    'title': '',
    'participant': '' }
_announcement_text = ''
_announcement_font = 'default'
_announcement_bold = False
_announcement_italic = False
_announcement_color = ''
_custom_text = ''
_custom_font = 'default'
_custom_bold = False
_custom_italic = False
_custom_color = ''
DATA_FILE = 'data/program.json'
HISTORY_FILE = 'data/history.json'
HISTORY_MAX = 6
LYRICS_DIR = 'data/lyrics'

def _lyrics_key(query):
    return re.sub('[^a-z0-9]+', '-', query.lower()).strip('-')


def _slugify(name, existing_ids = None):
    slug = re.sub('[^a-z0-9]+', '-', name.lower()).strip('-')
    if not existing_ids or slug not in existing_ids:
        return slug
    n = 2
    if f'''{slug}-{n}''' in existing_ids:
        n += 1
        if f'''{slug}-{n}''' in existing_ids:
            pass
    return f'''{slug}-{n}'''


def _lyrics_path(key):
    return os.path.join(LYRICS_DIR, f'''{key}.json''')


def _load_lyrics(path, hint_number = None, hint_title = None):
    """Load a lyrics JSON file. Migrates old plain-array format to the new
    object format {hymn_number, title, stanzas} on first access.
    Returns the data dict (always has a 'stanzas' key)."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        hymn_number = hint_number
        hymn_title = hint_title
        if not hymn_number:
            key = os.path.splitext(os.path.basename(path))[0]
            if key.isdigit():
                hymn_number = int(key)
            else:
                m = re.match('^[a-z]+-(\\d+)$', key)
                if m:
                    hymn_number = int(m.group(1))
        if hymn_number and not hymn_title:
            db = get_by_number(hymn_number)
            if db:
                hymn_title = db['title']
        data = {
            'stanzas': data }
        if hymn_number:
            data['hymn_number'] = hymn_number
        if hymn_title:
            data['title'] = hymn_title
        atomic_write_json(path, data)
    return data

DEFAULT_PROGRAM = {
    'church': '',
    'date': '',
    'pianist': '',
    'song_leader': '',
    'service_programs': [
        {
            'id': 'sample-program',
            'name': 'Sample Program',
            'time': '',
            'items': [
                {
                    'item_id': 'sp-001',
                    'type': 'participant',
                    'title': 'Opening Prayer',
                    'part': 'Opening Prayer',
                    'participant': '' },
                {
                    'item_id': 'sp-002',
                    'type': 'song',
                    'title': 'Opening Song',
                    'hymn_number': '' },
                {
                    'item_id': 'sp-003',
                    'type': 'media',
                    'title': 'Welcome',
                    'media_type': 'image',
                    'url': '/media/images/leiturgia-welcome.png' },
                {
                    'item_id': 'sp-004',
                    'type': 'media',
                    'title': 'Sample Video',
                    'media_type': 'video',
                    'url': '',
                    'autoplay': True,
                    'loop': False,
                    'mute': False },
                {
                    'item_id': 'sp-005',
                    'type': 'content',
                    'title': 'Announcements',
                    'content': '' }] }],
    'service_team': [] }

def _migrate_item(item, item_id = ''):
    """Convert a legacy-schema item (with 'participants') to the new typed schema."""
    if 'type' in item:
        return item
    parts = item.get('participants', [])
    p_name = parts[0].get('name', '') if parts else ''
    if 'hymn_number' in item:
        if not item.get('lyrics_key'):
            # unsupported DICT_UPDATE/DICT_MERGE
            return {
                'item_id': item_id,
                'type': 'song',
                'title': item.get('title', ''),
                'hymn_number': item.get('hymn_number', ''),
                'hymn_lang': item.get('hymn_lang', 'en') }
        # unsupported DICT_UPDATE/DICT_MERGE
        return {
            'item_id': item_id,
            'type': 'song',
            'title': item.get('title', ''),
            'hymn_number': item.get('hymn_number', ''),
            'hymn_lang': item.get('hymn_lang', 'en') }
    if not item.get('subtitle', ''):
        item.get('subtitle', '')
    return {
        'item_id': item_id,
        'type': 'participant',
        'title': item.get('title', ''),
        'part': item.get('subtitle', ''),
        'participant': p_name }
# WARNING: Decompyle incomplete


def _migrate_items(items, prefix = 'item'):
    
    try:
        for i, it in enumerate(items):
            pass
    it = enumerate(items)
    i = it

    it = it
    i = i
    return []
    
    try:
        for i, it in enumerate(items):
            pass
    it = enumerate(items)
    i = it

# WARNING: Decompyle incomplete


def load_program():
    if os.path.exists(DATA_FILE):
        data = None
        for attempt in range(3):
            
            try:
                with open(DATA_FILE) as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                if attempt == 2:
                    raise
                logger.warning('program.json read failed (attempt %d/3), retrying', attempt + 1)
                time.sleep(0.1)

            range(3)
        if 'sabbath_school' in data and 'divine_service' in data:
            ss = data['sabbath_school']
            ds = data['divine_service']
            ss_items = ss.get('items', [])
            if ss_items and 'type' not in ss_items[0]:
                ss_items = _migrate_items(ss_items, 'ss')
            ds_items = []
            for sub in ds.get('subsections', []):
                items = sub.get('items', [])
                if items and 'type' not in items[0]:
                    items = _migrate_items(items, 'ds')
                ds_items.extend(items)
            data = {
                'church': data.get('church', ''),
                'date': data.get('date', ''),
                'pianist': data.get('pianist', ''),
                'song_leader': data.get('song_leader', ''),
                'service_programs': [
                    {
                        'id': 'sabbath-school',
                        'name': 'Sabbath School',
                        'time': ss.get('time', '9:00 a.m.'),
                        'items': ss_items },
                    {
                        'id': 'divine-service',
                        'name': 'Divine Service',
                        'time': ds.get('time', '10:30 a.m.'),
                        'items': ds_items }],
                'service_team': data.get('service_team', []) }
        for sp in data.get('service_programs', []):
            items = sp.get('items', [])
            if items and 'type' not in items[0]:
                sp['items'] = _migrate_items(items, sp['id'][:2])
            for item in sp.get('items', []):
                if not item.get('type') == 'content':
                    continue
                if not 'participant' in item:
                    continue
                item['type'] = 'participant'
        return data
    return copy.deepcopy(DEFAULT_PROGRAM)


def _ensure_item_ids(program):
    '''Assign a unique item_id to any item that is missing one.'''
    for sp in program.get('service_programs', []):
        for item in sp.get('items', []):
            if item.get('item_id'):
                continue
            item['item_id'] = str(uuid.uuid4())


def save_program(data):
    _ensure_item_ids(data)
    atomic_write_json(DATA_FILE, data)
    logger.info('program saved (%d program(s))', len(data.get('service_programs', [])))


def _broadcast_order_of_service(program):
    state = timer.get_full_state('timer')['state']
    payload = oos.get_display(program, state)
    for ch in roles.get_channels('order_of_service'):
        socketio.emit('order_of_service:update', payload, room = ch)


def save_history(program):
    '''Append a snapshot of the current program to history (capped at HISTORY_MAX).'''
    history = []
    if os.path.exists(HISTORY_FILE):
        
        try:
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        except Exception:
            logger.warning('history file unreadable, starting empty', exc_info = True)
            history = []

    
    try:
        for sp in program.get('service_programs', []):
            pass
    sp = None

    sp = sp
    snapshot = {
        'saved_at': datetime.now().isoformat(),
        'church': program.get('church', ''),
        'date': program.get('date', ''),
        'service_programs': [] }
    history.insert(0, snapshot)
    history = history[:HISTORY_MAX]
    atomic_write_json(HISTORY_FILE, history)
    return None
    
    try:
        for sp in program.get('service_programs', []):
            pass
    sp = None

# WARNING: Decompyle incomplete


def _prepare_lyrics(items):
    '''Load lyrics from cache for song items.'''
    for item in items:
        if item.get('type') != 'song':
            continue
        if item.get('lyrics_key'):
            path = _lyrics_path(item['lyrics_key'])
            if not os.path.exists(path):
                continue
            data = _load_lyrics(path, hint_number = item.get('hymn_number'), hint_title = item.get('title'))
            item['lyrics'] = data['stanzas']
            continue
        if not item.get('hymn_number'):
            continue
        if item.get('lyrics'):
            continue
        hymn_lang = item.get('hymn_lang', 'en')
        result = get_by_number(int(item['hymn_number']), lang = hymn_lang)
        if not result:
            continue
        item['lyrics'] = result['stanzas']


def operator_required(f):
    decorated = (lambda : if not session.get('operator'):
if request.is_json or request.path.startswith('/api/'):
(jsonify({
'status': 'error',
'message': 'Unauthorized' }), 401)redirect(f'''/login?next={request.path}''')f(*args, **{
**kwargs }))()
    return decorated

login = (lambda : if request.method == 'POST':
if not request.get_json():
request.get_json()data = request.get_json()if not data.get('pin'):
data.get('pin')pin = str(data.get('pin')).strip()if hashlib.sha256(pin.encode()).hexdigest() == _get_pin_hash():
session.permanent = Truesession['operator'] = Truejsonify({
'status': 'ok' })(jsonify({
'status': 'error',
'message': 'Incorrect PIN' }), 401)render_template('login.html'))()()
logout = (lambda : session.clear()redirect('/login'))()

def _server_ip():
    import socket as _sock
    
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


index = (lambda : program = load_program()render_template('index.html', program = program, server_ip = _server_ip()))()()
health = (lambda : checks = { }healthy = Truetry:
load_program()checks['program'] = Trueexcept Exception:
logger.warning('health check: load_program failed', exc_info = True)checks['program'] = Falsehealthy = Falsetry:
roles.to_dict()checks['roles'] = Trueexcept Exception:
logger.warning('health check: roles manager failed', exc_info = True)checks['roles'] = Falsehealthy = Falsechecks['cloud'] = cloud_agent.statusbody = {
'status': 'ok' if healthy else 'error',
'version': get_version(),
'checks': checks }if healthy:
(jsonify(body), 200)(jsonify(body), 503))()
get_program = (lambda : jsonify(load_program()))()()
save_program_route = (lambda : data = request.get_json()save_program(data)save_history(data)cloud_agent.notify_program_saved(data)_broadcast_order_of_service(data)jsonify({
'status': 'saved' }))()()
get_history = (lambda : if not os.path.exists(HISTORY_FILE):
jsonify([])try:
f = open(HISTORY_FILE)jsonify(json.load(f))(None, None)Noneexcept Exception:
logger.warning('history file unreadable', exc_info = True)jsonify([])# WARNING: Decompyle incomplete
)()()
fetch_hymn = (lambda number: lang = request.args.get('lang', 'en')result = get_by_number(number, lang = lang)if not result:
(jsonify({
'status': 'error',
'message': 'Hymn not found' }), 404)jsonify({
'status': 'ok',
'stanzas': result['stanzas'],
'lang': lang }))()()
fetch_lyrics_route = (lambda : q = request.args.get('q', '').strip()if not q:
(jsonify({
'status': 'error',
'message': 'No query provided' }), 400)try:
lang = request.args.get('lang', 'en')hymn_number = Nonehymn_title = Noneif q.isdigit():
key = f'''{lang}-{q}'''hymn_number = int(q)else:
db_result = get_by_title(q, lang = lang)if db_result:
key = f'''{lang}-{db_result['number']}'''hymn_number = db_result['number']hymn_title = db_result['title']else:
key = _lyrics_key(q)path = _lyrics_path(key)if os.path.exists(path):
data = _load_lyrics(path, hint_number = hymn_number, hint_title = hymn_title)stanzas = data['stanzas']if not hymn_number:
hymn_numberhymn_number = hymn_numberif not hymn_title:
hymn_titlehymn_title = hymn_titleresp = {
'status': 'ok',
'key': key,
'count': len(stanzas),
'source': 'cache',
'lang': lang }if hymn_number:
resp['hymn_number'] = hymn_numberif hymn_title:
resp['title'] = hymn_titlejsonify(resp)result = get_by_number(hymn_number, lang = lang) if hymn_number else get_by_title(q, lang = lang)if not result or not result.get('stanzas'):
jsonify({
'status': 'error',
'message': 'No lyrics found' })stanzas = result['stanzas']if not hymn_number:
hymn_numberhymn_number = hymn_numberif not hymn_title:
hymn_titlehymn_title = hymn_titlelyrics_data = {
'stanzas': stanzas,
'lang': lang }if hymn_number:
lyrics_data['hymn_number'] = hymn_numberif hymn_title:
lyrics_data['title'] = hymn_titleatomic_write_json(path, lyrics_data)resp = {
'status': 'ok',
'key': key,
'count': len(stanzas),
'source': 'db',
'lang': lang }if hymn_number:
resp['hymn_number'] = hymn_numberif hymn_title:
resp['title'] = hymn_titlejsonify(resp)except Exception as e:
logger.exception('lyrics fetch failed: %s', q)(jsonify({
'status': 'error',
'message': str(e) }), 500)# WARNING: Decompyle incomplete
)()()
get_lyrics = (lambda key: path = _lyrics_path(key)if not os.path.exists(path):
(jsonify({
'status': 'error',
'message': 'Lyrics file not found' }), 404)data = _load_lyrics(path)jsonify({
'status': 'ok',
'stanzas': data['stanzas'],
'hymn_number': data.get('hymn_number'),
'title': data.get('title') }))()()
hymnal_search = (lambda : q = request.args.get('q', '').strip()lang = request.args.get('lang', 'en')if not q:
jsonify([])if q.isdigit():
results = search_by_number_prefix(q, limit = 8, lang = lang)else:
results = search_titles(q, limit = 8, lang = lang)for r in results:
r['lang'] = langjsonify(results))()()
LANG_LABELS = {
    'en': 'English',
    'tl': 'Tagalog',
    'ceb': 'Cebuano',
    'ilo': 'Ilocano' }
hymnal_languages = (lambda : import globpattern = os.path.join(os.path.dirname(__file__), 'data', 'hymns_*.db')langs = []for path in sorted(glob.glob(pattern)):
code = os.path.basename(path)[len('hymns_'):-len('.db')]langs.append({
'code': code,
'label': LANG_LABELS.get(code, code.upper()) })jsonify(langs))()
add_program = (lambda : data = request.get_json()if not data.get('name'):
data.get('name')name = data.get('name').strip()if not name:
(jsonify({
'status': 'error',
'message': 'Name is required' }), 400)program = load_program()try:
for sp in program.get('service_programs', []):
passsp = program.get('service_programs', [])existing_ids = []sp = sppid = _slugify(name, existing_ids)program['service_programs'].append({
'id': pid,
'name': name,
'time': '',
'items': [] })save_program(program)save_history(program)_broadcast_order_of_service(program)jsonify({
'status': 'ok',
'id': pid })try:
for sp in program.get('service_programs', []):
passsp = program.get('service_programs', [])# WARNING: Decompyle incomplete
)()()
get_projection_state = (lambda : jsonify(proj._state))()()
delete_program = (lambda program_id: program = load_program()programs = program.get('service_programs', [])if len(programs) <= 1:
(jsonify({
'error': 'cannot delete last program' }), 400)try:
for p in programs:
if not p['id'] != program_id:
continuep = programsp = pprogram['service_programs'] = []save_program(program)_broadcast_order_of_service(program)jsonify({
'ok': True,
'selected': program['service_programs'][0]['id'] })try:
for p in programs:
if not p['id'] != program_id:
continuep = programs# WARNING: Decompyle incomplete
)()()

def _item_to_slide_state(item):
    '''Build the first-slide projection state for a program item.'''
    t = item.get('type', 'participant')
    if not t == 'video':
        t == 'video'
        if t == 'media':
            t == 'media'
    is_video = t == 'video'
    if not t == 'image':
        t == 'image'
        if t == 'media':
            t == 'media'
    is_image = t == 'image'
    is_live = t == 'live'
    if is_live:
        return {
            'type': 'live',
            'data': {
                'device_id': item.get('device_id', '') },
            'theme_id': 'default' }
    if is_video:
        return {
            'type': 'video',
            'data': {
                'url': item.get('url', ''),
                'autoplay': item.get('autoplay', False),
                'loop': item.get('loop', False),
                'mute': item.get('mute', False) },
            'theme_id': 'default' }
    if is_image:
        return {
            'type': 'image',
            'data': {
                'url': item.get('url', '') },
            'theme_id': 'default' }
    if t == 'song':
        return {
            'type': 'text',
            'data': {
                'title': item.get('title', ''),
                'part': item.get('part', ''),
                'stanza': '' },
            'theme_id': 'default' }
    if t == 'content':
        full = item.get('content', '')
        
        try:
            for p in full.split('\n\n'):
                if not p.strip():
                    continue
        p = None

        paras = []
        p = p
        first_para = paras[0] if paras else full
        return {
            'type': 'text',
            'data': {
                'title': item.get('title', ''),
                'body': first_para,
                'part': item.get('part', ''),
                'is_content_para': True },
            'theme_id': 'default' }
    name = item.get('participant', '')
    part = item.get('part', '')
    return {
        'type': 'text',
        'data': {
            'title': item.get('title', ''),
            'part': part,
            'participants': [
                {
                    'role': part,
                    'name': name }] if name else [] },
        'theme_id': 'default' }
    
    try:
        for p in full.split('\n\n'):
            if not p.strip():
                continue
    p = None

# WARNING: Decompyle incomplete


def _next_sequence_slide(program, item_id, slide_url = None, program_id = None):
    '''Return the first-slide state for the sequence item immediately after item_id.

    slide_url and program_id disambiguate when multiple items share the same item_id.
    '''
    for sp in program.get('service_programs', []):
        if program_id and sp.get('id') != program_id:
            continue
        items = sp.get('items', [])
        for i, it in enumerate(items):
            if it['item_id'] != item_id:
                continue
            if slide_url and it.get('url') and it['url'] != slide_url:
                continue
            for nxt in items[i + 1:]:
                if not nxt.get('enabled', True):
                    continue
                items[i + 1:]
                enumerate(items)
                return _item_to_slide_state(nxt)
            return None


def roles_channel_map():
    '''Return {channel: role} from roles.to_dict() which is {role: [channels]}.'''
    result = { }
    for role, channels in roles.to_dict().items():
        for ch in channels:
            result[ch] = role
    return result


def build_remote_sync():
    state = proj.get_state('ch1')
    data = state.get('data', { }) if state else { }
    next_stanza = data.get('next_stanza')
    next_slide_data = None
    if next_stanza:
        next_slide_data = {
            'type': 'text',
            'data': {
                'stanza': next_stanza,
                'title': data.get('title', ''),
                'part': data.get('part', '') },
            'theme_id': state.get('theme_id', 'default') }
    elif data.get('is_content_para'):
        if not data.get('item_id'):
            data.get('item_id')
        item_id = data.get('item_id')
        para_idx = data.get('para_idx', 0)
        if item_id:
            program = load_program()
            item = (lambda .0: for sp in .0:
for it in sp.get('items', []):
if it['item_id'] == item_id:
itsp.get('items', []))(program.get('service_programs', [])(), None)
            if item:
                full = item.get('content', '')
                
                try:
                    for p in full.split('\n\n'):
                        if not p.strip():
                            continue
                p = None

                paras = []
                p = p
                if para_idx + 1 < len(paras):
                    next_slide_data = {
                        'type': 'text',
                        'data': {
                            'body': paras[para_idx + 1],
                            'part': data.get('part', ''),
                            'title': data.get('title', ''),
                            'is_content_para': True },
                        'theme_id': state.get('theme_id', 'default') }
                else:
                    program_id = _active_item.get('program_id')
                    next_slide_data = _next_sequence_slide(program, item_id, program_id = program_id)
            elif not data.get('item_id'):
                data.get('item_id')
            item_id = full.split('\n\n')
            if not data.get('url'):
                data.get('url')
            slide_url = data.get('url')
            program_id = _active_item.get('program_id')
            if item_id:
                program = load_program()
                next_slide_data = _next_sequence_slide(program, item_id, slide_url = slide_url, program_id = program_id)
    if not state:
        state
    return {
        'slide_data': state,
        'slide_index': data.get('slide_index', 0),
        'slide_count': data.get('slide_count', 0),
        'item_title': data.get('title', ''),
        'next_slide_data': next_slide_data,
        'assignments': roles_channel_map() }
    
    try:
        for p in full.split('\n\n'):
            if not p.strip():
                continue
    p = None

# WARNING: Decompyle incomplete

_ROLE_TEMPLATE = {
    'main': 'projection.html',
    'order_of_service': 'order_of_service.html',
    'timer': 'timer_display.html',
    'announcement': 'announcement.html',
    'custom': 'custom_output.html' }

def _get_projection_aspect(channel):
    """Projection aspect-ratio setting for a channel ('off', 'auto', or 'W:H')."""
    
    try:
        with open('config.json') as f:
            cfg = json.load(f)
        if not cfg.get('projection_aspects', { }).get(channel, 'off'):
            cfg.get('projection_aspects', { }).get(channel, 'off')
        return str(cfg.get('projection_aspects', { }).get(channel, 'off'))
    except Exception:
        return 'off'


projection_channel = (lambda n: channel = f'''ch{n}'''if not roles.get_role(channel):
roles.get_role(channel)role = roles.get_role(channel)template = _ROLE_TEMPLATE.get(role, 'projection.html')program = load_program()timer_fs = timer.get_full_state('timer')oos_data = oos.get_display(program, timer_fs['state'])_ct = _custom_theme_state()render_template(template, channel = channel, role = role, order_of_service = oos_data, timer_state = timer_fs, active_item = _active_item, announcement = _announcement_text, custom_theme = _ct, aspect = _get_projection_aspect(channel)))()
remote = (lambda : render_template('remote.html'))()()
from flask import send_from_directory
_THEMES = [
    {
        'id': 'default',
        'name': 'Default (Navy/Gold)' },
    {
        'id': 'midnight',
        'name': 'Midnight' },
    {
        'id': 'dawn',
        'name': 'Dawn' },
    {
        'id': 'forest',
        'name': 'Forest' },
    {
        'id': 'slate',
        'name': 'Slate' },
    {
        'id': 'ivory',
        'name': 'Ivory (Light)' },
    {
        'id': 'ocean',
        'name': 'Ocean' },
    {
        'id': 'ember',
        'name': 'Ember' },
    {
        'id': 'pearl',
        'name': 'Pearl' },
    {
        'id': 'royal',
        'name': 'Royal' },
    {
        'id': 'custom',
        'name': 'Custom (Background Image)' }]
serve_theme = (lambda filename: themes_dir = os.path.join(app.root_path, 'templates', 'themes')send_from_directory(themes_dir, filename))()
api_themes = (lambda : jsonify(_THEMES))()()
_CUSTOM_THEME_DIR = os.path.join(os.getcwd(), 'media', 'themes', 'custom')
_CUSTOM_THEME_FILE = os.path.join(os.getcwd(), 'data', 'custom_theme.json')
_CUSTOM_SLOTS = 4

def _custom_theme_state():
    '''Load custom theme state: { active: int, slots: [url|null x4] }.'''
    default = {
        'active': 0,
        'slots': [
            None] * _CUSTOM_SLOTS }
    
    try:
        with open(_CUSTOM_THEME_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default

    if not isinstance(data, dict):
        return default
    slots = data.get('slots', default['slots'])
    if not isinstance(slots, list) or len(slots) != _CUSTOM_SLOTS:
        slots = [
            None] * _CUSTOM_SLOTS
    active = data.get('active', default['active'])
    
    try:
        active = int(active)
    except (TypeError, ValueError):
        active = default['active']

    if active < 0 or active >= _CUSTOM_SLOTS:
        active = 0
    return {
        'active': active,
        'slots': slots }


def _save_custom_theme_state(state):
    os.makedirs(os.path.dirname(_CUSTOM_THEME_FILE), exist_ok = True)
    atomic_write_json(_CUSTOM_THEME_FILE, {
        'active': state.get('active', 0),
        'slots': state.get('slots', [
            None] * _CUSTOM_SLOTS) })

api_themes_custom = (lambda : state = _custom_theme_state()jsonify({
'active': state['active'],
'slots': state['slots'],
'count': _CUSTOM_SLOTS }))()()
api_themes_custom_upload = (lambda : from werkzeug.utils import secure_filenameif not request.form.get('slot'):
request.form.get('slot')if not request.args.get('slot'):
request.args.get('slot')slot_raw = request.form.get('slot')try:
slot = int(slot_raw)except (TypeError, ValueError):
(jsonify({
'status': 'error',
'message': 'Invalid slot' }), 400)if slot < 0 or slot >= _CUSTOM_SLOTS:
(jsonify({
'status': 'error',
'message': f'''Slot must be 0-{_CUSTOM_SLOTS - 1}''' }), 400)if 'file' not in request.files:
(jsonify({
'status': 'error',
'message': 'No file provided' }), 400)f = request.files['file']if not f.filename:
(jsonify({
'status': 'error',
'message': 'Empty filename' }), 400)ext = os.path.splitext(f.filename)[1].lower()if ext not in _IMAGE_EXTS:
(jsonify({
'status': 'error',
'message': f'''Unsupported image type: {ext}''' }), 400)state = _custom_theme_state()prev = state['slots'][slot]if prev:
_delete_custom_bg_file(prev)os.makedirs(_CUSTOM_THEME_DIR, exist_ok = True)safe = secure_filename(f.filename)if not _sanitize_filename(safe):
_sanitize_filename(safe)base = _sanitize_filename(safe)(stem, ext) = os.path.splitext(base)filename = f'''{stem}_{slot}_{uuid.uuid4().hex[:8]}{ext}'''save_path = os.path.join(_CUSTOM_THEME_DIR, filename)f.save(save_path)url = f'''/media/themes/custom/{_url_quote(filename, safe = '')}'''state['slots'][slot] = url_save_custom_theme_state(state)logger.info('custom theme: uploaded background to slot %d (%s)', slot, filename)jsonify({
'status': 'ok',
'url': url,
'slot': slot,
'active': state['active'],
'slots': state['slots'] }))()()
api_themes_custom_active = (lambda : if not request.get_json(silent = True):
request.get_json(silent = True)data = request.get_json(silent = True)try:
slot = int(data.get('slot', request.form.get('slot', '')))except (TypeError, ValueError):
(jsonify({
'status': 'error',
'message': 'Invalid slot' }), 400)if slot < 0 or slot >= _CUSTOM_SLOTS:
(jsonify({
'status': 'error',
'message': f'''Slot must be 0-{_CUSTOM_SLOTS - 1}''' }), 400)state = _custom_theme_state()state['active'] = slot_save_custom_theme_state(state)logger.info('custom theme: active background set to slot %d', slot)jsonify({
'status': 'ok',
'active': state['active'] }))()()
api_themes_custom_delete = (lambda slot: if slot < 0 or slot >= _CUSTOM_SLOTS:
(jsonify({
'status': 'error',
'message': f'''Slot must be 0-{_CUSTOM_SLOTS - 1}''' }), 400)state = _custom_theme_state()url = state['slots'][slot]if not url:
jsonify({
'status': 'ok',
'slots': state['slots'] })_delete_custom_bg_file(url)state['slots'][slot] = Nonetry:
for i, u in enumerate(state['slots']):
if not u:
continueu = enumerate(state['slots'])i = uhave_any = []i = iu = uif state['active'] == slot:
state['active'] = have_any[0] if have_any else 0_save_custom_theme_state(state)logger.info('custom theme: deleted background from slot %d', slot)jsonify({
'status': 'ok',
'active': state['active'],
'slots': state['slots'] })try:
for i, u in enumerate(state['slots']):
if not u:
continueu = enumerate(state['slots'])i = u# WARNING: Decompyle incomplete
)()()

def _delete_custom_bg_file(url):
    '''Best-effort removal of a served custom-theme background file by URL.'''
    
    try:
        name = os.path.basename(url.rstrip('/'))
        candidate = os.path.join(_CUSTOM_THEME_DIR, name)
        if os.path.isfile(candidate):
            os.remove(candidate)
            return None
    except OSError:
        logger.warning('custom theme: failed to remove background file for %s', url, exc_info = True)
        return None


serve_custom_theme_bg = (lambda filename: send_from_directory(_CUSTOM_THEME_DIR, filename))()
on_connect = (lambda : logger_socket.debug('connect: sid=%s', request.sid))()
on_disconnect = (lambda : logger_socket.debug('disconnect: sid=%s', request.sid))()
on_join = (lambda data: channel = data.get('channel', 'ch1')join_room(channel)role = roles.get_role(channel)logger_socket.info('join: sid=%s channel=%s role=%s', request.sid, channel, role)if role == 'order_of_service':
program = load_program()timer_fs = timer.get_full_state('timer')payload = oos.get_display(program, timer_fs['state'])emit('order_of_service:update', payload)Noneif role == 'timer':
fs = timer.get_full_state('timer')emit('timer:tick', {
'remaining': fs['remaining'],
'total': fs['total'],
'state': fs['state'],
'label': fs['label'],
'overtime': fs['overtime'] })Noneif role == 'announcement':
if _announcement_text:
emit('announcement:update', _ann_payload())NoneNoneif role == 'custom':
if _custom_text:
emit('custom:update', _custom_payload())NoneNone)()
on_remote_join = (lambda : if not session.get('operator'):
disconnect()Nonejoin_room('remote-clients')logger_socket.info('join: sid=%s channel=remote-clients role=remote', request.sid)emit('remote:sync', build_remote_sync()))()
on_console_join = (lambda : if not session.get('operator'):
disconnect()Nonejoin_room('console')join_room('ch1')logger_socket.info('join: sid=%s channel=console role=operator', request.sid))()
on_console_watch = (lambda data: if not session.get('operator'):
disconnect()Noneold_ch = data.get('old', 'ch1')new_ch = data.get('new', 'ch1')valid = ('ch1', 'ch2', 'ch3', 'ch4', 'ch5')if old_ch in valid:
leave_room(old_ch)if new_ch in valid:
join_room(new_ch)None)()
on_remote_next = (lambda : if not session.get('operator'):
disconnect()Nonesocketio.emit('remote:next', { }, room = 'console'))()
on_remote_prev = (lambda : if not session.get('operator'):
disconnect()Nonesocketio.emit('remote:prev', { }, room = 'console'))()
on_remote_blank = (lambda : if not session.get('operator'):
disconnect()Nonesocketio.emit('remote:blank', { }, room = 'console'))()
on_state_restore = (lambda data: channel = data.get('channel', 'ch1')state = proj.get_state(channel)if state.get('type') == 'blank' and roles.get_role(channel) == 'main':
for ch in roles.get_channels('main'):
if not ch != channel:
continues = proj.get_state(ch)if not s.get('type') != 'blank':
continuestate = sroles.get_channels('main')if state.get('type') != 'blank':
emit('slide:show', state)None)()
on_slide_show = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state = {
'type': 'text',
'data': data,
'theme_id': data.get('theme_id', 'default') }if not roles.get_role(channel):
roles.get_role(channel)for ch in roles.get_channels(roles.get_role(channel)):
proj.set_state(ch, state)socketio.emit('slide:show', data, room = ch)socketio.emit('remote:sync', build_remote_sync(), room = 'remote-clients'))()
on_slide_blank = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state = {
'type': 'blank',
'data': { },
'theme_id': 'default' }if not roles.get_role(channel):
roles.get_role(channel)for ch in roles.get_channels(roles.get_role(channel)):
proj.set_state(ch, state)socketio.emit('slide:blank', state, room = ch)socketio.emit('remote:sync', build_remote_sync(), room = 'remote-clients'))()
on_slide_edit = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state = {
'type': 'text',
'data': data,
'theme_id': data.get('theme_id', 'default') }if not roles.get_role(channel):
roles.get_role(channel)for ch in roles.get_channels(roles.get_role(channel)):
proj.set_state(ch, state)socketio.emit('slide:edit', data, room = ch))()
on_theme_apply = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')theme_id = data.get('theme_id', 'default')custom_bg = data.get('custom_bg')if not roles.get_role(channel):
roles.get_role(channel)for ch in roles.get_channels(roles.get_role(channel)):
socketio.emit('theme:apply', {
'theme_id': theme_id,
'custom_bg': custom_bg }, room = ch))()
on_media_image = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state = {
'type': 'image',
'data': data,
'theme_id': 'default' }if not roles.get_role(channel):
roles.get_role(channel)for ch in roles.get_channels(roles.get_role(channel)):
proj.set_state(ch, state)socketio.emit('media:image', data, room = ch)socketio.emit('remote:sync', build_remote_sync(), room = 'remote-clients'))()
on_media_video = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state = {
'type': 'video',
'data': data,
'theme_id': 'default' }if not roles.get_role(channel):
roles.get_role(channel)for ch in roles.get_channels(roles.get_role(channel)):
proj.set_state(ch, state)socketio.emit('media:video', data, room = ch)socketio.emit('remote:sync', build_remote_sync(), room = 'remote-clients'))()
on_media_live = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state = {
'type': 'live',
'data': data,
'theme_id': 'default' }if not roles.get_role(channel):
roles.get_role(channel)for ch in roles.get_channels(roles.get_role(channel)):
proj.set_state(ch, state)socketio.emit('media:live', data, room = ch)socketio.emit('remote:sync', build_remote_sync(), room = 'remote-clients'))()
on_media_status = (lambda data: channel = data.get('channel', 'ch1')emit('media:status', data, to = channel))()
on_media_blocked = (lambda data: channel = data.get('channel', 'ch1')emit('media:blocked', data, to = channel))()
on_announcement = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state = {
'type': 'announcement',
'data': data,
'theme_id': 'default' }proj.set_state(channel, state)emit('announcement', data, to = channel))()
on_timer_show = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state_d = timer.show(channel, int(data.get('seconds', 0)), data.get('label', ''))state_d.update({
'channel': channel,
'type': 'timer' })proj.set_state(channel, {
'type': 'timer',
'data': state_d,
'theme_id': 'default' })emit('timer:show', state_d, to = channel))()
on_timer_start = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')secs = data.get('seconds')label = data.get('label')state_d = timer.start(channel, int(secs) if secs is None else None, label)state_d.update({
'channel': channel,
'type': 'timer' })proj.set_state(channel, {
'type': 'timer',
'data': state_d,
'theme_id': 'default' })emit('timer:start', state_d, to = channel))()
on_timer_pause = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')state_d = timer.pause(channel)state_d.update({
'channel': channel })emit('timer:pause', state_d, to = channel))()
on_timer_reset = (lambda data: if not session.get('operator'):
disconnect()Nonechannel = data.get('channel', 'ch1')secs = data.get('seconds')state_d = timer.reset(channel, int(secs) if secs is None else None)state_d.update({
'channel': channel,
'type': 'timer' })proj.set_state(channel, {
'type': 'timer',
'data': state_d,
'theme_id': 'default' })emit('timer:reset', state_d, to = channel))()
_VALID_ROLES = ('main', 'order_of_service', 'timer', 'announcement', 'custom')

def _existing_channels():
    '''All valid channels = the defaults plus any channels added dynamically.'''
    chs = list(roles.get_existing_channels())
    for c in ('ch1', 'ch2', 'ch3', 'ch4'):
        if not c not in chs:
            continue
        chs.append(c)
    return chs


def _sorted_channels():
    return sorted(_existing_channels(), key = (lambda c: (not c[2:].isdigit(), int(c[2:])) if c[2:].isdigit() else (not c[2:].isdigit(), 0)))

on_roles_assign = (lambda data: if not session.get('operator'):
disconnect()Nonerole = data.get('role', '')channels = data.get('channels', [])valid = _existing_channels()if role not in _VALID_ROLES:
emit('error', {
'message': f'''Invalid role: {role}''' })Noneif not channels or not all(( ch in valid for ch in channels )):
emit('error', {
'message': 'Invalid or empty channels list' })Noneroles.assign(channels, role)socketio.emit('roles:updated', {
'assignments': roles_channel_map() }))()
api_roles_get = (lambda : jsonify({
'assignments': roles.to_dict() }))()()
api_roles_post = (lambda : if not request.get_json():
request.get_json()data = request.get_json()role = data.get('role', '')channels = data.get('channels', [])valid = _existing_channels()if role not in _VALID_ROLES:
(jsonify({
'status': 'error',
'message': f'''Invalid role: {role}''' }), 400)if not channels or not all(( ch in valid for ch in channels )):
(jsonify({
'status': 'error',
'message': 'Invalid or empty channels list' }), 400)roles.assign(channels, role)ch_map = roles_channel_map()socketio.emit('roles:updated', {
'assignments': ch_map })jsonify({
'assignments': ch_map }))()()
api_channels_get = (lambda : ch_map = roles_channel_map()channels = _sorted_channels()try:
with open('config.json') as f:
cfg = json.load(f)if not cfg.get('projection_aspects', { }):
cfg.get('projection_aspects', { })aspects = cfg.get('projection_aspects', { })except Exception:
aspects = { }try:
for ch in channels:
if not aspects.get(ch, 'off'):
aspects.get(ch, 'off')ch = Noneaspects_map = chch = Nonejsonify({
'channels': channels,
'assignments': ch_map,
'aspects': aspects_map })try:
for ch in channels:
if not aspects.get(ch, 'off'):
aspects.get(ch, 'off')ch = None# WARNING: Decompyle incomplete
)()()
api_channels_post = (lambda : if not request.get_json():
request.get_json()data = request.get_json()role = data.get('role', '')if role not in _VALID_ROLES:
role = 'main'new_ch = roles.add_channel(role)ch_map = roles_channel_map()socketio.emit('roles:updated', {
'assignments': ch_map })channels = _sorted_channels()jsonify({
'status': 'ok',
'channel': new_ch,
'channels': channels,
'assignments': ch_map }))()()
api_channel_delete = (lambda channel: if channel == 'ch1':
(jsonify({
'status': 'error',
'message': 'Cannot delete the main console channel' }), 400)if channel not in _existing_channels():
(jsonify({
'status': 'error',
'message': 'Invalid channel' }), 404)roles.remove_channel(channel)ch_map = roles_channel_map()socketio.emit('roles:updated', {
'assignments': ch_map })channels = _sorted_channels()jsonify({
'status': 'ok',
'channel': channel,
'channels': channels,
'assignments': ch_map }))()()
_DEFAULT_ALLOTTED = {
    'song': 4,
    'prayer': 3,
    'content': 5,
    'participant': 5,
    'media': 5,
    'live': 5 }
on_program_item_set = (lambda data: if not session.get('operator'):
disconnect()Noneprogram_id = data.get('program_id', '')item_id = data.get('item_id', '')program = load_program()item = Nonefor sp in program.get('service_programs', []):
if not sp['id'] == program_id:
continuefor it in sp.get('items', []):
if not it['item_id'] == item_id:
continueitem = itsp.get('items', [])if item is not None:
emit('error', {
'message': 'Item not found' })Noneif not item.get('enabled', True):
emit('error', {
'message': 'Item is disabled' })Noneis_timed = item.get('timed', True)if not item.get('allotted_minutes'):
item.get('allotted_minutes')allotted_mins = item.get('allotted_minutes')allotted_secs = int(allotted_mins) * 60_active_item = {
'program_id': program_id,
'item_id': item_id,
'allotted_seconds': allotted_secs if is_timed else 0,
'title': item.get('title', ''),
'participant': item.get('participant', ''),
'timed': is_timed }oos.set_active(program_id, item_id)if is_timed:
timer.reset('timer', allotted_secs)timer.start('timer')timer_state = timer.get_full_state('timer')['state']else:
timer.pause('timer')timer_state = 'normal'for ch in roles.get_channels('timer'):
socketio.emit('timer:idle', { }, room = ch)oos_payload = oos.get_display(program, timer_state)for ch in roles.get_channels('order_of_service'):
socketio.emit('order_of_service:update', oos_payload, room = ch)slide_state = proj.get_state(roles.get_channels('main')[0] if roles.get_channels('main') else 'ch1')for ch in roles.get_channels('main'):
socketio.emit('state:update', {
'item': _active_item }, room = ch)item_update = {
'title': _active_item['title'],
'participant': _active_item['participant'] }for ch in roles.get_channels('timer'):
socketio.emit('active:item:updated', item_update, room = ch))()
api_active_item = (lambda : jsonify({
'item': _active_item }) if _active_item['item_id'] else jsonify({
'item': None }))()()

def _ann_payload():
    return {
        'text': _announcement_text,
        'font_family': _announcement_font,
        'text_bold': _announcement_bold,
        'text_italic': _announcement_italic,
        'text_color': _announcement_color }


def _custom_payload():
    return {
        'text': _custom_text,
        'font_family': _custom_font,
        'text_bold': _custom_bold,
        'text_italic': _custom_italic,
        'text_color': _custom_color }

on_announcement_push = (lambda data: if not session.get('operator'):
disconnect()None_announcement_text = data.get('text', '')_announcement_font = data.get('font_family', 'default')_announcement_bold = data.get('text_bold', False)_announcement_italic = data.get('text_italic', False)_announcement_color = data.get('text_color', '')for ch in roles.get_channels('announcement'):
socketio.emit('announcement:update', _ann_payload(), room = ch))()
on_announcement_blank = (lambda data: if not session.get('operator'):
disconnect()None_announcement_text = ''for ch in roles.get_channels('announcement'):
socketio.emit('announcement:blank', { }, room = ch))()
api_announcement_push = (lambda : if not request.get_json():
request.get_json()data = request.get_json()_announcement_text = data.get('text', '')_announcement_font = data.get('font_family', 'default')_announcement_bold = data.get('text_bold', False)_announcement_italic = data.get('text_italic', False)_announcement_color = data.get('text_color', '')for ch in roles.get_channels('announcement'):
socketio.emit('announcement:update', _ann_payload(), room = ch)jsonify({
'status': 'pushed' }))()()
api_announcement_blank = (lambda : _announcement_text = ''for ch in roles.get_channels('announcement'):
socketio.emit('announcement:blank', { }, room = ch)jsonify({
'status': 'blanked' }))()()
on_custom_update = (lambda data: if not session.get('operator'):
disconnect()None_custom_text = data.get('text', '')_custom_font = data.get('font_family', 'default')_custom_bold = data.get('text_bold', False)_custom_italic = data.get('text_italic', False)_custom_color = data.get('text_color', '')for ch in roles.get_channels('custom'):
socketio.emit('custom:update', _custom_payload(), room = ch))()
on_custom_blank = (lambda data = None: if not session.get('operator'):
disconnect()None_custom_text = ''for ch in roles.get_channels('custom'):
socketio.emit('custom:blank', { }, room = ch))()
api_custom_push = (lambda : if not request.get_json():
request.get_json()data = request.get_json()_custom_text = data.get('text', '')_custom_font = data.get('font_family', 'default')_custom_bold = data.get('text_bold', False)_custom_italic = data.get('text_italic', False)_custom_color = data.get('text_color', '')for ch in roles.get_channels('custom'):
socketio.emit('custom:update', _custom_payload(), room = ch)jsonify({
'status': 'pushed' }))()()
api_custom_blank = (lambda : _custom_text = ''for ch in roles.get_channels('custom'):
socketio.emit('custom:blank', { }, room = ch)jsonify({
'status': 'blanked' }))()()
_IMAGE_EXTS = {
    '.gif',
    '.jpg',
    '.png',
    '.jpeg',
    '.webp'}
_VIDEO_EXTS = {
    '.mov',
    '.webm',
    '.mp4'}
api_media = (lambda : data = list_media()data['usage'] = media_manager.usage()data['in_use'] = media_manager.referenced_media()jsonify(data))()()
delete_media_file = (lambda media_type, filename: if media_type not in ('images', 'videos'):
(jsonify({
'status': 'error',
'message': 'Invalid media type' }), 400)safe = os.path.basename(filename)if not safe or safe != filename:
(jsonify({
'status': 'error',
'message': 'Invalid filename' }), 400)type_dir = media_manager.videos_dir() if media_type == 'videos' else os.path.join(app.root_path, 'media', 'images')path = os.path.join(type_dir, safe)if not os.path.exists(path):
(jsonify({
'status': 'error',
'message': 'File not found' }), 404)used_by = media_manager.referenced_media().get(safe)if used_by:
(jsonify({
'status': 'error',
'code': 'media_in_use',
'message': f'''"{safe}" is used by a saved program item and cannot be deleted.''',
'used_by': used_by }), 409)try:
os.remove(path)jsonify({
'status': 'ok' })except OSError as e:
logger.exception('media delete failed: %s', path)(jsonify({
'status': 'error',
'message': str(e) }), 500)# WARNING: Decompyle incomplete
)()()
delete_media_videos_bulk = (lambda : if not request.get_json():
request.get_json()data = request.get_json()filenames = data.get('filenames')if not isinstance(filenames, list) or not filenames:
(jsonify({
'status': 'error',
'message': 'No filenames provided' }), 400)in_use = media_manager.referenced_media()videos_dir = media_manager.videos_dir()failed = []deleted = []for filename in filenames:
if not isinstance(filename, str):
failed.append({
'name': str(filename),
'reason': 'invalid_filename' })continuesafe = os.path.basename(filename)if not safe or safe != filename:
failed.append({
'name': filename,
'reason': 'invalid_filename' })continueused_by = in_use.get(safe)if used_by:
failed.append({
'name': safe,
'reason': 'in_use',
'used_by': used_by })continuepath = os.path.join(videos_dir, safe)if not os.path.exists(path):
failed.append({
'name': safe,
'reason': 'not_found' })continuetry:
os.remove(path)deleted.append(safe)except OSError as e:
logger.exception('media bulk delete failed: %s', path)failed.append({
'name': safe,
'reason': str(e) })jsonify({
'deleted': deleted,
'failed': failed,
'usage': media_manager.usage() }))()()
api_media_usb_targets = (lambda : jsonify(media_manager.usb_targets()))()()

def _video_dir_status():
    '''Shape shared by GET and POST responses for /api/settings/video-dir.'''
    vdir = media_manager.videos_dir()
    usage = media_manager.usage()
    return {
        'status': 'ok',
        'location': 'internal' if vdir == media_manager.VIDEOS_DIR else 'external',
        'path': os.path.abspath(vdir),
        'label': usage.get('location_label', 'Internal'),
        'usage': usage,
        'videos_unavailable': usage.get('videos_unavailable', False) }

api_settings_video_dir = (lambda : if request.method == 'GET':
jsonify(_video_dir_status())if not request.get_json():
request.get_json()data = request.get_json()if not data.get('dir'):
data.get('dir')requested = data.get('dir').strip()previous_path = media_manager.videos_dir()if not requested:
new_dir = media_manager.VIDEOS_DIRelif not os.path.isabs(requested):
(jsonify({
'status': 'error',
'message': 'Path must be absolute.' }), 400)try:
for t in media_manager.usb_targets():
passt = Nonetexcept:
media_manager.usb_targets()mounted_roots = tt = Nonetry:
real_requested = os.path.realpath(requested)except (OSError, ValueError):
real_requested = requestedif real_requested in mounted_roots:
candidate = os.path.join(requested.rstrip('/'), 'leiturgia-videos')else:
candidate = requestedresolved = media_manager.resolve_export_target(candidate)if not resolved:
(jsonify({
'status': 'error',
'message': 'Path must be on a mounted, writable removable drive (/media, /mnt, or /run/media).' }), 400)if not os.path.exists(resolved) or not os.path.isdir(resolved):
(jsonify({
'status': 'error',
'message': 'Path exists and is not a directory.' }), 400)try:
os.makedirs(resolved, exist_ok = True)except OSError as e:
media_manager.usb_targets()if not os.access(resolved, os.W_OK):
(jsonify({
'status': 'error',
'message': 'Path is not writable.' }), 400)new_dir = resolvedwith open('config.json') as f:
cfg = json.load(f)cfg['media_video_dir'] = '' if new_dir == media_manager.VIDEOS_DIR else new_diratomic_write_json('config.json', cfg)status = _video_dir_status()status['previous_path'] = previous_pathlogger_media.info('video storage location changed: %s -> %s', previous_path, status['path'])jsonify(status)# WARNING: Decompyle incomplete
)()()
api_yt_title = (lambda : url = request.args.get('url', '').strip()if not url:
jsonify({
'title': None })try:
r = requests.get('https://www.youtube.com/oembed', params = {
'url': url,
'format': 'json' }, timeout = 5)if r.ok:
jsonify({
'title': r.json().get('title') })except Exception:
logger.debug('yt title fetch failed for %s', url, exc_info = True)jsonify({
'title': None }))()()
api_yt_cache = (lambda : if not os.path.exists(_YT_CACHE_PATH):
jsonify({ })f = open(_YT_CACHE_PATH)jsonify(json.load(f))(None, None)None# WARNING: Decompyle incomplete
)()()
api_settings_pin = (lambda : if not request.get_json():
request.get_json()data = request.get_json()if not data.get('pin'):
data.get('pin')pin = str(data.get('pin')).strip()if pin.isdigit():
if not (4 <= len(pin)) or not (len(pin) <= 6):
(jsonify({
'status': 'error',
'message': 'PIN must be 4ΓÇô6 digits' }), 400)with open('config.json') as f:
cfg = json.load(f)cfg.pop('pin', None)cfg['pin_hash'] = hashlib.sha256(pin.encode()).hexdigest()atomic_write_json('config.json', cfg)jsonify({
'status': 'ok' }))()()
api_settings_update_url = (lambda : with open('config.json') as f:
cfg = json.load(f)if request.method == 'POST':
if not request.get_json():
request.get_json()data = request.get_json()if not data.get('url'):
data.get('url')url = str(data.get('url')).strip()if not url.startswith('http://') and not url.startswith('https://'):
(jsonify({
'status': 'error',
'message': 'URL must start with http(s)://' }), 400)cfg['update_url'] = urlatomic_write_json('config.json', cfg)jsonify({
'status': 'ok',
'update_url': url })jsonify({
'update_url': cfg.get('update_url', '') }))()()
api_settings_projection_get = (lambda : channels = roles.get_existing_channels()try:
with open('config.json') as f:
cfg = json.load(f)if not cfg.get('projection_aspects', { }):
cfg.get('projection_aspects', { })aspects = cfg.get('projection_aspects', { })except Exception:
aspects = { }try:
for ch in channels:
if not roles.get_role(ch):
roles.get_role(ch)if not aspects.get(ch, 'off'):
aspects.get(ch, 'off')ch = Nonech = chjsonify({
'channels': [] })try:
for ch in channels:
if not roles.get_role(ch):
roles.get_role(ch)if not aspects.get(ch, 'off'):
aspects.get(ch, 'off')ch = None# WARNING: Decompyle incomplete
)()()
api_settings_projection_post = (lambda : if not request.get_json():
request.get_json()data = request.get_json()if not data.get('channel'):
data.get('channel')channel = str(data.get('channel')).strip()if not data.get('projection_aspect'):
data.get('projection_aspect')aspect = str(data.get('projection_aspect')).strip()existing = roles.get_existing_channels()if channel not in existing:
(jsonify({
'status': 'error',
'message': 'Unknown channel.' }), 400)if aspect not in ('off', 'auto'):
m = re.match('^\\s*(\\d+)\\s*[:xX]\\s*(\\d+)\\s*$', aspect)if not m:
(jsonify({
'status': 'error',
'message': 'Aspect must be "off", "auto", or "W:H" (e.g. 16:9, 4:3).' }), 400)aspect = f'''{int(m.group(1))}:{int(m.group(2))}'''with open('config.json') as f:
cfg = json.load(f)aspects = cfg.get('projection_aspects', { })if not isinstance(aspects, dict):
aspects = { }aspects[channel] = aspectcfg['projection_aspects'] = aspectsatomic_write_json('config.json', cfg)socketio.emit('aspect:update', {
'aspect': aspect }, room = channel)jsonify({
'status': 'ok',
'channel': channel,
'projection_aspect': aspect }))()()
_user32 = ctypes.windll.user32

class _RECT(ctypes.Structure):
    _fields_ = [
        ('left', ctypes.c_long),
        ('top', ctypes.c_long),
        ('right', ctypes.c_long),
        ('bottom', ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_ulong),
        ('rcMonitor', _RECT),
        ('rcWork', _RECT),
        ('dwFlags', ctypes.c_ulong)]


def _get_monitors():
    '''Enumerate physical displays and their screen coordinates (pixels).'''
    out = []
    MONITORINFOF_PRIMARY = 1
    cb = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_void_p)((lambda hmon, hdc, lprc, data: True))
    
    @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_void_p)
    def _cb(hmon, hdc, lprc, data):
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        _user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r = mi.rcMonitor
        out.append({
            'index': len(out),
            'x': r.left,
            'y': r.top,
            'width': r.right - r.left,
            'height': r.bottom - r.top,
            'primary': bool(mi.dwFlags & MONITORINFOF_PRIMARY),
            'label': 'Monitor {}'.format(len(out) + 1) })
        return True

    _user32.EnumDisplayMonitors(0, 0, _cb, 0)
    if not out:
        out.append({
            'index': 0,
            'x': 0,
            'y': 0,
            'width': 1920,
            'height': 1080,
            'primary': True,
            'label': 'Monitor 1' })
    return out


def _find_edge():
    candidates = [
        os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)') + '\\Microsoft\\Edge\\Application\\msedge.exe',
        os.environ.get('ProgramFiles', 'C:\\Program Files') + '\\Microsoft\\Edge\\Application\\msedge.exe',
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Edge', 'Application', 'msedge.exe')]
    for c in candidates:
        if not c:
            continue
        if not os.path.exists(c):
            continue
        return c


def _edge_profile_dir(channel):
    base = os.path.join(os.environ.get('TEMP', tempfile.gettempdir()), 'leitur-edge')
    return os.path.join(base, 'ch-' + re.sub('[^A-Za-z0-9]', '', channel).lower())

api_output_monitors = (lambda : jsonify({
'monitors': _get_monitors(),
'edge': bool(_find_edge()) }))()()
api_output_push = (lambda : if not request.get_json():
request.get_json()data = request.get_json()if not data.get('channel'):
data.get('channel')channel = str(data.get('channel')).strip().lower()if not data.get('monitor', 0):
data.get('monitor', 0)monitor_i = int(data.get('monitor', 0))if not channel or channel not in _existing_channels():
(jsonify({
'status': 'error',
'message': 'Unknown channel.' }), 400)edge = _find_edge()if not edge:
(jsonify({
'status': 'error',
'message': 'Microsoft Edge not found.' }), 500)mons = _get_monitors()if not mons:
(jsonify({
'status': 'error',
'message': 'No display detected.' }), 500)mon = next(( m for m in mons if m['index'] == monitor_i ), mons[0])url = f'''http://{request.host}/{channel}?output=1'''profile = _edge_profile_dir(channel)args = [
edge,
f'''--app={url}''',
'--kiosk',
f'''--window-position={mon['x']},{mon['y']}''',
f'''--window-size={mon['width']},{mon['height']}''',
f'''--user-data-dir={profile}''',
'--no-first-run',
'--no-default-browser-check',
'--disable-features=Translate']try:
subprocess.Popen(args, stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL)except Exception:
(jsonify({
'status': 'error',
'message': 'Failed to launch Edge.' }), 500)jsonify({
'status': 'ok',
'channel': channel,
'monitor': mon['index'],
'url': url,
'position': [
mon['x'],
mon['y']],
'size': [
mon['width'],
mon['height']] }))()()
api_output_close = (lambda : if not request.get_json():
request.get_json()if not request.form:
request.formdata = request.get_json()if not data.get('channel'):
data.get('channel')channel = str(data.get('channel')).strip().lower()if not channel:
(jsonify({
'status': 'error',
'message': 'No channel.' }), 400)profile = _edge_profile_dir(channel)killed = _kill_profile_processes(profile)jsonify({
'status': 'ok' if killed else 'noop',
'channel': channel,
'killed': killed }))()

def _kill_profile_processes(profile):
    if os.name != 'nt':
        return False
    marker = os.path.basename(profile)
    script = 'Get-CimInstance Win32_Process -Filter "Name=\'msedge.exe\'" | Where-Object { $_.CommandLine -like \'*' + marker + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    
    try:
        import base64 as _b64
        enc = _b64.b64encode(script.encode('utf-16-le')).decode('ascii')
        p = subprocess.Popen([
            'powershell',
            '-NoProfile',
            '-NonInteractive',
            '-EncodedCommand',
            enc], stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL)
        p.communicate(timeout = 20)
        return True
    except Exception:
        return False


settings = (lambda : cfg = cloud_agent._load_config()render_template('settings.html', enable_self_update = cfg.get('enable_self_update', False), update_url = cfg.get('update_url', '')))()()
api_cloud_status = (lambda : with open('config.json') as f:
cfg = json.load(f)jsonify({
'status': cloud_agent.status,
'linked': cloud_agent.linked,
'cloud_url': cfg.get('cloud_url', ''),
'cloud_token': cfg.get('cloud_token', '') }))()()
api_cloud_link = (lambda : if not request.get_json():
request.get_json()data = request.get_json()if not data.get('cloud_url'):
data.get('cloud_url')cloud_url = data.get('cloud_url').strip().rstrip('/')if not data.get('cloud_token'):
data.get('cloud_token')cloud_token = data.get('cloud_token').strip()if not cloud_url or not cloud_token:
(jsonify({
'status': 'error',
'message': 'cloud_url and cloud_token are required' }), 400)try:
resp = requests.post(f'''https://{cloud_url}/api/v1/devices/register''', headers = {
'Authorization': f'''Bearer {cloud_token}''' }, timeout = 10)except requests.exceptions.RequestException as exc:
(jsonify({
'status': 'error',
'message': f'''Could not reach cloud: {exc}''' }), 502)if resp.status_code == 200:
church_name = resp.json().get('church_name', '')with open('config.json') as f:
cfg = json.load(f)cfg['cloud_enabled'] = Truecfg['cloud_url'] = cloud_urlcfg['cloud_token'] = cloud_tokenatomic_write_json('config.json', cfg)cloud_agent.restart()jsonify({
'status': 'linked',
'church_name': church_name })if resp.status_code == 401:
msg = 'Invalid token ΓÇö not recognised by the cloud.'elif resp.status_code == 403:
msg = 'Device limit reached on the cloud account.'else:
msg = f'''Cloud returned {resp.status_code}.'''(jsonify({
'status': 'error',
'message': msg }), 400)# WARNING: Decompyle incomplete
)()()
api_cloud_unlink = (lambda : with open('config.json') as f:
cfg = json.load(f)cfg['cloud_enabled'] = Falsecfg['cloud_token'] = ''cfg['cloud_url'] = ''atomic_write_json('config.json', cfg)jsonify({
'status': 'ok' }))()()
api_cloud_sync_status = (lambda : try:
with open(DATA_FILE) as f:
local = json.load(f)sps = local.get('service_programs', [])pi_info = {
'has_data': len(sps) > 0,
'count': len(sps) }except Exception:
logger.warning('cloud sync status: failed to read local program', exc_info = True)pi_info = {
'has_data': False,
'count': 0 }cfg = cloud_agent._load_config()if not (cfg.get('cloud_enabled') and cfg.get('cloud_url')) or not cfg.get('cloud_token'):
jsonify({
'linked': False,
'pi': pi_info,
'cloud': None })cloud_url = cfg['cloud_url'].strip().rstrip('/')cloud_token = cfg['cloud_token'].strip()try:
resp = requests.get(f'''https://{cloud_url}/api/v1/programs/device-meta''', headers = {
'Authorization': f'''Bearer {cloud_token}''' }, timeout = 10)resp.raise_for_status()cloud_info = resp.json()except Exception as exc:
logger.warning('cloud sync status: cloud request failed: %s', exc)jsonify({
'linked': True,
'pi': pi_info,
'cloud': None,
'error': str(exc) })jsonify({
'linked': True,
'pi': pi_info,
'cloud': cloud_info })# WARNING: Decompyle incomplete
)()()
api_cloud_sync = (lambda : if not request.get_json():
request.get_json()data = request.get_json()direction = data.get('direction')if direction not in ('pi_to_cloud', 'cloud_to_pi'):
(jsonify({
'ok': False,
'error': 'invalid direction' }), 400)cfg = cloud_agent._load_config()cloud_url = cfg.get('cloud_url', '').strip().rstrip('/')cloud_token = cfg.get('cloud_token', '').strip()if direction == 'pi_to_cloud':
try:
with open(DATA_FILE) as f:
local = json.load(f)except Exception as exc:
logger.exception('cloud sync: failed to read local program')(jsonify({
'ok': False,
'error': str(exc) }), 500)cloud_agent.force_push_program(local)jsonify({
'ok': True })try:
resp = requests.get(f'''https://{cloud_url}/api/v1/programs/device-current''', headers = {
'Authorization': f'''Bearer {cloud_token}''' }, timeout = 10)resp.raise_for_status()program_data = resp.json()except Exception as exc:
logger.warning('cloud sync: failed to fetch from cloud: %s', exc)(jsonify({
'ok': False,
'error': str(exc) }), 502)try:
atomic_write_json(DATA_FILE, program_data)logger.info('cloud applied program update')cloud_agent._pending_ui_notify = Trueexcept Exception as exc:
logger.exception('cloud-apply program write failed')(jsonify({
'ok': False,
'error': str(exc) }), 500)jsonify({
'ok': True })# WARNING: Decompyle incomplete
)()()

def _origin_reachable():
    '''Timeout-bounded reachability probe to `origin` (TDD ┬º6.4, D5).

    Some church Pis have no internet at all; the preflight must fail fast and
    cleanly (no lock, no request, no destructive action) rather than let a
    `git fetch`/checkout start and hang or half-complete offline.
    '''
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    
    try:
        result = subprocess.run([
            'git',
            'ls-remote',
            '--heads',
            'origin'], cwd = repo_dir, capture_output = True, text = True, timeout = 5)
        return result.returncode == 0
    except Exception:
        return False



def _update_config():
    '''Read config.json fresh (update_url / enable_self_update are runtime
    settings that may change between requests).'''
    
    try:
        _f = open('config.json')
        json.load(_f)(None, None)
        return None
    except Exception:
        return { }

# WARNING: Decompyle incomplete


def _update_install_dir():
    '''The app runs with its working directory set to the install folder
    (LeiturgiaServer.exe / Leiturgia.exe / config.json / license.dat / updater.exe
    all live side-by-side).'''
    return os.getcwd()


def _write_update_status(payload):
    
    try:
        d = os.path.join('data', 'update')
        os.makedirs(d, exist_ok = True)
        with open(os.path.join(d, 'status.json'), 'w') as _f:
            json.dump(payload, _f)
        return None
    except Exception:
        logger.warning('update status write failed', exc_info = True)
        return None


api_update_check = (lambda : cfg = _update_config()update_url = cfg.get('update_url', '')if not update_url:
(jsonify({
'status': 'error',
'message': 'no update_url configured' }), 400)try:
info = updater.check_for_update(update_url, get_version())jsonify({
'current': get_version(),
'latest': info.get('latest'),
'available': info.get('available', False) })except Exception:
logger.warning('update check failed', exc_info = True)(jsonify({
'status': 'error',
'current': get_version(),
'latest': None }), 503))()()
api_update_start = (lambda : cfg = _update_config()update_url = cfg.get('update_url', '')if not update_url:
(jsonify({
'status': 'error',
'message': 'no update_url configured' }), 400)current = get_version()try:
info = updater.check_for_update(update_url, current)except Exception:
logger.warning('update check before start failed', exc_info = True)(jsonify({
'status': 'error',
'message': 'cannot reach update server' }), 503)if not info.get('available'):
(jsonify({
'status': 'error',
'message': 'already up to date',
'current': current,
'latest': info.get('latest') }), 409)lock_path = os.path.join('data', 'update', 'lock')try:
fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)os.close(fd)except FileExistsError:
(jsonify({
'status': 'error',
'message': 'update already in progress' }), 409)stage_dir = os.path.join(tempfile.gettempdir(), 'leiturgia_update_stage')try:
shutil.rmtree(stage_dir, ignore_errors = True)updater.download_bundle(info['manifest'], stage_dir, update_url)manifest_path = os.path.join(stage_dir, 'manifest.json')with open(manifest_path, 'w') as _f:
json.dump(info['manifest'], _f)except Exception:
try:
os.unlink(lock_path)except OSError:
passexcept:
passexcept:
logger.exception('update download failed')(jsonify({
'status': 'error',
'message': 'download failed' }), 500)try:
subprocess.Popen([
applier,
'apply',
_update_install_dir(),
stage_dir,
manifest_path], stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL, creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))except Exception:
try:
os.unlink(lock_path)except OSError:
passexcept:
passexcept:
logger.exception('failed to launch updater.exe')(jsonify({
'status': 'error',
'message': 'failed to launch updater' }), 500)applier = os.path.join(_update_install_dir(), 'updater.exe')try:
subprocess.Popen([
applier,
'apply',
_update_install_dir(),
stage_dir,
manifest_path], stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL, creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))except Exception:
try:
os.unlink(lock_path)except OSError:
passexcept:
passexcept:
logger.exception('failed to launch updater.exe')(jsonify({
'status': 'error',
'message': 'failed to launch updater' }), 500)_write_update_status({
'status': 'applying',
'current': current,
'target_version': info['latest'],
'ts': time.time(),
'note': 'Application will restart when finished.' })(jsonify({
'status': 'started',
'target_version': info['latest'] }), 202)try:
shutil.rmtree(stage_dir, ignore_errors = True)updater.download_bundle(info['manifest'], stage_dir, update_url)manifest_path = os.path.join(stage_dir, 'manifest.json')with open(manifest_path, 'w') as _f:
json.dump(info['manifest'], _f)except Exception:
try:
os.unlink(lock_path)except OSError:
passexcept:
passexcept:
logger.exception('update download failed')(jsonify({
'status': 'error',
'message': 'download failed' }), 500)try:
subprocess.Popen([
applier,
'apply',
_update_install_dir(),
stage_dir,
manifest_path], stdout = subprocess.DEVNULL, stderr = subprocess.DEVNULL, creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))except Exception:
try:
os.unlink(lock_path)except OSError:
passexcept:
passexcept:
logger.exception('failed to launch updater.exe')(jsonify({
'status': 'error',
'message': 'failed to launch updater' }), 500))()()
api_update_status = (lambda : status_path = os.path.join('data', 'update', 'status.json')try:
_f = open(status_path)jsonify(json.load(_f))(None, None)Noneexcept Exception:
jsonify({
'status': 'idle' })# WARNING: Decompyle incomplete
)()()

def _sanitize_filename(name):
    (stem, ext) = os.path.splitext(name)
    stem = stem.replace('-', '_')
    stem = re.sub('_+', '_', stem).strip('_')
    return stem + ext


def _effective_remaining_bytes(usage, media_type):
    """Effective remaining budget for 'video' or 'image', honoring the shared
    filesystem reserve (min(budget - used, fs_room)) per the storage-budget TDD."""
    fs_room = usage['fs_free_bytes'] - usage['reserve_bytes']
    if media_type == 'video':
        return usage['remaining_bytes']
    images = usage['images']
    if images['budget_bytes'] == 0:
        return fs_room
    return min(images['budget_bytes'] - images['used_bytes'], fs_room)

_MEDIA_BUDGET_MESSAGES = {
    'video': 'Video storage is full. Delete unused videos or export them to a USB drive to free up space.',
    'image': 'Image storage is full. Delete unused images to free up space.' }

def _media_budget_error(media_type):
    return (jsonify({
        'status': 'error',
        'code': 'media_budget_exceeded',
        'message': _MEDIA_BUDGET_MESSAGES[media_type] }), 413)

upload_media = (lambda : from werkzeug.utils import secure_filenameif 'file' not in request.files:
(jsonify({
'status': 'error',
'message': 'No file provided' }), 400)f = request.files['file']if not f.filename:
(jsonify({
'status': 'error',
'message': 'Empty filename' }), 400)ext = os.path.splitext(f.filename)[1].lower()if ext in _IMAGE_EXTS:
media_type = 'image'subdir = 'images'elif ext in _VIDEO_EXTS:
media_type = 'video'subdir = 'videos'else:
(jsonify({
'status': 'error',
'message': f'''Unsupported file type: {ext}''' }), 400)if media_type == 'video' and media_manager.videos_unavailable():
(jsonify({
'status': 'error',
'code': 'video_storage_unavailable',
'message': 'Video storage is unavailable ΓÇö check the drive connection.' }), 503)usage_before = media_manager.usage()remaining_before = _effective_remaining_bytes(usage_before, media_type)if request.content_length is None and request.content_length > max(remaining_before, 0):
_media_budget_error(media_type)filename = _sanitize_filename(secure_filename(f.filename))save_dir = media_manager.videos_dir() if subdir == 'videos' else os.path.join(app.root_path, 'media', 'images')os.makedirs(save_dir, exist_ok = True)save_path = os.path.join(save_dir, filename)f.save(save_path)usage_after = media_manager.usage()over_budget = usage_after['full'] if media_type == 'video' else usage_after['images']['full']if over_budget:
try:
os.remove(save_path)except OSError:
logger_media.warning('failed to remove over-budget upload: %s', save_path, exc_info = True)_media_budget_error(media_type)_media_budget_error(media_type)url = f'''/media/{subdir}/{_url_quote(filename, safe = '')}'''jsonify({
'status': 'ok',
'url': url,
'media_type': media_type }))()()
serve_media = (lambda subdir, filename: if subdir not in ('images', 'videos'):
('Not found', 404)media_dir = media_manager.videos_dir() if subdir == 'videos' else os.path.join(app.root_path, 'media', 'images')send_from_directory(media_dir, filename))()
import shutil as _shutil
_FFMPEG = _shutil.which('ffmpeg')
_QUALITY_MERGE = {
    'best': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    '1080p': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]',
    '720p': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
    '480p': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]',
    '360p': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]',
    'audio': 'bestaudio[ext=m4a]/bestaudio' }
_QUALITY_NOFFMPEG = {
    'best': 'best[ext=mp4]/best',
    '1080p': 'best[height<=1080][ext=mp4]/best[height<=1080]',
    '720p': 'best[height<=720][ext=mp4]/best[height<=720]',
    '480p': 'best[height<=480][ext=mp4]/best[height<=480]',
    '360p': 'best[height<=360][ext=mp4]/best[height<=360]',
    'audio': 'bestaudio[ext=m4a]/bestaudio' }

def _get_format(quality):
    table = _QUALITY_MERGE if _FFMPEG else _QUALITY_NOFFMPEG
    return table.get(quality, table['best'])

_ANSI_RE = re.compile('\\x1b\\[[0-9;]*m')
_YT_CACHE_PATH = os.path.join('data', 'yt_cache.json')
_YT_ID_RE = re.compile('(?:youtube\\.com/(?:watch\\?v=|shorts/)|youtu\\.be/)([A-Za-z0-9_-]{11})')

def _strip_ansi(s):
    return _ANSI_RE.sub('', s).strip()


def _yt_progress_hook(d, item_id, sid):
    status = d.get('status')
    if status == 'downloading':
        if not d.get('downloaded_bytes'):
            d.get('downloaded_bytes')
        downloaded = d.get('downloaded_bytes')
        if not d.get('total_bytes'):
            d.get('total_bytes')
            if not d.get('total_bytes_estimate'):
                d.get('total_bytes_estimate')
        total = d.get('total_bytes')
        if total:
            percent = min(100, (downloaded / total) * 100)
        else:
            raw = _strip_ansi(d.get('_percent_str', '0%'))
            
            try:
                percent = float(raw.replace('%', ''))
            except ValueError:
                percent = 0

        speed_raw = _strip_ansi(d.get('_speed_str', ''))
        socketio.emit('yt:progress', {
            'item_id': item_id,
            'status': 'downloading',
            'percent': percent,
            'speed': speed_raw,
            'eta': d.get('eta', 0) }, room = sid)
        eventlet.sleep(0)
        return None
    if status == 'finished':
        socketio.emit('yt:progress', {
            'item_id': item_id,
            'status': 'processing',
            'percent': 100,
            'speed': '',
            'eta': 0 }, room = sid)
        eventlet.sleep(0)
        return None


def _yt_cache_write(source_url, filename, local_url):
    m = _YT_ID_RE.search(source_url)
    key = m.group(1) if m else source_url
    
    try:
        cache = { }
        if os.path.exists(_YT_CACHE_PATH):
            with open(_YT_CACHE_PATH) as f:
                cache = json.load(f)
        cache[key] = {
            'filename': filename,
            'local_url': local_url,
            'source_url': source_url }
        atomic_write_json(_YT_CACHE_PATH, cache)
        return None
    except Exception:
        logger.warning('yt_cache write failed', exc_info = True)
        return None



def _yt_budget_error(item_id, sid):
    socketio.emit('yt:error', {
        'item_id': item_id,
        'message': _MEDIA_BUDGET_MESSAGES['video'] }, room = sid)


def _yt_download_task(url, quality, item_id, sid):
    import yt_dlp
    if media_manager.videos_unavailable():
        socketio.emit('yt:error', {
            'item_id': item_id,
            'message': 'Video storage is unavailable ΓÇö check the drive connection.' }, room = sid)
        return None
    videos_dir = media_manager.videos_dir()
    os.makedirs(videos_dir, exist_ok = True)
    usage_before = media_manager.usage()
    remaining_before = _effective_remaining_bytes(usage_before, 'video')
    if remaining_before <= 0:
        _yt_budget_error(item_id, sid)
        return None
    ydl_opts = {
        'format': _get_format(quality),
        'outtmpl': os.path.join(videos_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [
            (lambda d: _yt_progress_hook(d, item_id, sid))],
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'restrictfilenames': True }
    _cookies_path = os.path.join(app.root_path, 'data', 'yt_cookies.txt')
    if os.path.isfile(_cookies_path):
        ydl_opts['cookiefile'] = _cookies_path
    if _FFMPEG:
        ydl_opts['merge_output_format'] = 'mp4'
    
    try:
        
        try:
            for k, v in ydl_opts.items():
                if not k != 'progress_hooks':
                    continue
        v = None
        k = None
        except Exception:
            logger_media.warning('yt-dlp pre-flight size estimate failed for %s', url, exc_info = True)

        preflight_opts = k
        k = v
        v = None
        preflight_opts['progress_hooks'] = []
        with yt_dlp.YoutubeDL(preflight_opts) as ydl_probe:
            info_probe = ydl_probe.extract_info(url, download = False)
        if not info_probe.get('filesize'):
            info_probe.get('filesize')
        estimate = info_probe.get('filesize')
        if estimate and estimate > remaining_before:
            _yt_budget_error(item_id, sid)
            return None
        if remaining_before > 0:
            ydl_opts['max_filesize'] = remaining_before
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download = True)
                raw_name = os.path.basename(ydl.prepare_filename(info))
                if _FFMPEG:
                    final = os.path.splitext(raw_name)[0] + '.mp4'
                else:
                    base = os.path.splitext(raw_name)[0]
                    found = next(( f for f in os.listdir(videos_dir) if f.startswith(base) ), raw_name)
                    final = found
                sanitized = _sanitize_filename(final)
                if sanitized != final:
                    os.rename(os.path.join(videos_dir, final), os.path.join(videos_dir, sanitized))
                    final = sanitized
                final_path = os.path.join(videos_dir, final)
                final_url = f'''/media/videos/{_url_quote(final, safe = '')}'''
            if os.path.exists(final_path):
                usage_after = media_manager.usage()
                if usage_after['full']:
                    
                    try:
                        os.remove(final_path)
                    except OSError:
                        logger_media.warning('failed to remove over-budget download: %s', final_path, exc_info = True)

                    _yt_budget_error(item_id, sid)
                    return None
            _yt_cache_write(url, final, final_url)
            logger_media.info('media download complete: item_id=%s file=%s', item_id, final)
            socketio.emit('yt:done', {
                'item_id': item_id,
                'url': final_url,
                'filename': final }, room = sid)
        except Exception as exc:
            logger_media.exception('yt download failed: %s', url)
            socketio.emit('yt:error', {
                'item_id': item_id,
                'message': str(exc) }, room = sid)
            return None

        return None

# WARNING: Decompyle incomplete

on_yt_download_start = (lambda data: if not session.get('operator'):
disconnect()Noneif not data.get('url'):
data.get('url')url = data.get('url').strip()quality = data.get('quality', 'best')item_id = data.get('item_id', '')sid = request.sidif not url.startswith(('http://', 'https://')):
emit('yt:error', {
'item_id': item_id,
'message': 'Invalid URL ΓÇö must start with http:// or https://' })Nonelogger_media.info('media download start: item_id=%s quality=%s url=%s', item_id, quality, url)socketio.start_background_task(_yt_download_task, url, quality, item_id, sid))()
_EXPORT_CHUNK_SIZE = 4194304

def _export_copy_file(src_path, dst_path, size, filename, sid):
    '''Chunked manual copy (not one blocking shutil.copy2 call) so the
    eventlet loop stays live during multi-GB copies ΓÇö mirrors the yt-dlp
    progress-hook pattern. Emits media:export:progress per chunk. Raises
    OSError (including ENOSPC) on a write failure; the caller cleans up the
    partial target file.'''
    copied = 0
    with open(src_path, 'rb') as fsrc:
        fdst = open(dst_path, 'wb')
        chunk = fsrc.read(_EXPORT_CHUNK_SIZE)
        if not chunk:
            pass
        else:
            fdst.write(chunk)
            copied += len(chunk)
            socketio.emit('media:export:progress', {
                'filename': filename,
                'bytes': copied,
                'total': size }, room = sid)
            eventlet.sleep(0)
        None(None, None)
    
    try:
        _shutil.copystat(src_path, dst_path)
        return None
    except OSError:
        return None



def _media_export_task(filenames, target, move, sid):
    videos_dir = media_manager.videos_dir()
    resolved_target = media_manager.resolve_usb_target(target)
    if not resolved_target:
        socketio.emit('media:export:error', {
            'code': 'invalid_target',
            'message': 'USB target is no longer available ΓÇö insert the drive and refresh.' }, room = sid)
        return None
    safe_names = []
    for name in filenames:
        if not isinstance(name, str):
            continue
        safe = os.path.basename(name)
        if not safe or safe != name:
            continue
        if not os.path.isfile(os.path.join(videos_dir, safe)):
            continue
        safe_names.append(safe)
    if not safe_names:
        socketio.emit('media:export:error', {
            'code': 'no_files',
            'message': 'No valid files to export.' }, room = sid)
        return None
    total_size = sum(( os.path.getsize(os.path.join(videos_dir, n)) for n in safe_names ))
    
    try:
        target_free = _shutil.disk_usage(resolved_target).free
    except OSError:
        target_free = 0

    if total_size > target_free:
        socketio.emit('media:export:error', {
            'code': 'usb_target_full',
            'message': 'Not enough free space on the USB drive.',
            'need_label': media_manager._fmt_size(total_size),
            'free_label': media_manager._fmt_size(target_free) }, room = sid)
        return None
    in_use = media_manager.referenced_media()
    (moved, copied, kept_local, failed) = ([], [], [], [])
    for name in safe_names:
        src_path = os.path.join(videos_dir, name)
        dst_path = os.path.join(resolved_target, name)
        
        try:
            size = os.path.getsize(src_path)
        except OSError:
            failed.append({
                'name': name,
                'reason': 'not_found' })

        
        try:
            _export_copy_file(src_path, dst_path, size, name, sid)
        except OSError:
            
            try:
                if os.path.exists(dst_path):
                    os.remove(dst_path)
            except OSError:
                logger_media.warning('failed to clean up partial export file: %s', dst_path, exc_info = True)
            except:
                pass

        except:
            logger_media.warning('media export write failed for %s', name, exc_info = True)
            
            try:
                free_now = _shutil.disk_usage(resolved_target).free
            except OSError:
                free_now = 0
            except:
                pass

        except:
            socketio.emit('media:export:error', {
                'code': 'usb_target_full',
                'message': f'''"{name}" did not fit on the USB drive ΓÇö export stopped.''',
                'name': name,
                'need_label': media_manager._fmt_size(size),
                'free_label': media_manager._fmt_size(free_now) }, room = sid)
            safe_names
            return None

        
        try:
            dst_size = os.path.getsize(dst_path)
        except OSError:
            dst_size = -1

        if dst_size != size:
            failed.append({
                'name': name,
                'reason': 'verify_failed' })
            
            try:
                os.remove(dst_path)
            except OSError:
                pass

            continue
        used_by = in_use.get(name)
        if move and used_by:
            kept_local.append({
                'name': name,
                'note': 'in_use_kept_local',
                'used_by': used_by })
            continue
        if move:
            
            try:
                os.remove(src_path)
                moved.append(name)
            except OSError:
                logger_media.warning('failed to remove local original after export: %s', src_path, exc_info = True)
                failed.append({
                    'name': name,
                    'reason': 'delete_failed' })

            continue
        copied.append(name)
    logger_media.info('media export done: target=%s moved=%d copied=%d kept_local=%d failed=%d', resolved_target, len(moved), len(copied), len(kept_local), len(failed))
    socketio.emit('media:export:done', {
        'moved': moved,
        'copied': copied,
        'kept_local': kept_local,
        'failed': failed,
        'usage': media_manager.usage() }, room = sid)
    return None
    
    try:
        _export_copy_file(src_path, dst_path, size, name, sid)
    except OSError:
        
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except OSError:
            logger_media.warning('failed to clean up partial export file: %s', dst_path, exc_info = True)
        except:
            pass

    except:
        logger_media.warning('media export write failed for %s', name, exc_info = True)
        
        try:
            free_now = _shutil.disk_usage(resolved_target).free
        except OSError:
            free_now = 0
        except:
            pass

    except:
        socketio.emit('media:export:error', {
            'code': 'usb_target_full',
            'message': f'''"{name}" did not fit on the USB drive ΓÇö export stopped.''',
            'name': name,
            'need_label': media_manager._fmt_size(size),
            'free_label': media_manager._fmt_size(free_now) }, room = sid)
        safe_names
        return None


on_media_export_start = (lambda data: if not session.get('operator'):
disconnect()Noneif not data.get('filenames'):
data.get('filenames')filenames = data.get('filenames')if not data.get('target'):
data.get('target')target = data.get('target').strip()move = bool(data.get('move'))sid = request.sidif not isinstance(filenames, list) or not filenames:
emit('media:export:error', {
'code': 'no_files',
'message': 'No files selected.' })Noneif not target:
emit('media:export:error', {
'code': 'invalid_target',
'message': 'No USB target selected.' })Nonelogger_media.info('media export start: sid=%s target=%s move=%s files=%d', sid, target, move, len(filenames))socketio.start_background_task(_media_export_task, filenames, target, move, sid))()

def _video_dir_migrate_task(from_dir, sid):
    to_dir = media_manager.videos_dir()
    if not from_dir == media_manager.VIDEOS_DIR:
        from_dir == media_manager.VIDEOS_DIR
    valid_from = from_dir == media_manager.VIDEOS_DIR
    if not valid_from or not os.path.isdir(from_dir):
        socketio.emit('media:export:error', {
            'code': 'invalid_target',
            'message': 'Previous video location is not available ΓÇö nothing to migrate.' }, room = sid)
        return None
    if os.path.realpath(from_dir) == os.path.realpath(to_dir):
        socketio.emit('media:export:done', {
            'moved': [],
            'copied': [],
            'kept_local': [],
            'failed': [],
            'usage': media_manager.usage() }, room = sid)
        return None
    os.makedirs(to_dir, exist_ok = True)
    safe_names = sorted(( n for n in os.listdir(from_dir) if os.path.splitext(n)[1].lower() in media_manager.VIDEO_EXTS and os.path.isfile(os.path.join(from_dir, n)) ))
    if not safe_names:
        socketio.emit('media:export:done', {
            'moved': [],
            'copied': [],
            'kept_local': [],
            'failed': [],
            'usage': media_manager.usage() }, room = sid)
        return None
    in_use = media_manager.referenced_media()
    failed = []
    kept_local = []
    moved = []
    for name in safe_names:
        src_path = os.path.join(from_dir, name)
        dst_path = os.path.join(to_dir, name)
        
        try:
            size = os.path.getsize(src_path)
        except OSError:
            failed.append({
                'name': name,
                'reason': 'not_found' })

        
        try:
            _export_copy_file(src_path, dst_path, size, name, sid)
        except OSError:
            
            try:
                if os.path.exists(dst_path):
                    os.remove(dst_path)
            except OSError:
                logger_media.warning('failed to clean up partial migration file: %s', dst_path, exc_info = True)
            except:
                pass

        except:
            logger_media.warning('video-dir migration write failed for %s', name, exc_info = True)
            failed.append({
                'name': name,
                'reason': 'write_failed' })

        
        try:
            dst_size = os.path.getsize(dst_path)
        except OSError:
            dst_size = -1

        if dst_size != size:
            failed.append({
                'name': name,
                'reason': 'verify_failed' })
            
            try:
                os.remove(dst_path)
            except OSError:
                pass

            continue
        used_by = in_use.get(name)
        if used_by:
            kept_local.append({
                'name': name,
                'note': 'in_use_kept_local',
                'used_by': used_by })
            continue
        
        try:
            os.remove(src_path)
            moved.append(name)
        except OSError:
            logger_media.warning('failed to remove source after migration: %s', src_path, exc_info = True)
            failed.append({
                'name': name,
                'reason': 'delete_failed' })

    logger_media.info('video-dir migration done: from=%s to=%s moved=%d kept_local=%d failed=%d', from_dir, to_dir, len(moved), len(kept_local), len(failed))
    socketio.emit('media:export:done', {
        'moved': moved,
        'copied': [],
        'kept_local': kept_local,
        'failed': failed,
        'usage': media_manager.usage() }, room = sid)

on_media_migrate_start = (lambda data: if not session.get('operator'):
disconnect()Noneif not data.get('from'):
data.get('from')from_dir = data.get('from').strip()sid = request.sidif not from_dir:
emit('media:export:error', {
'code': 'invalid_target',
'message': 'No previous location to migrate from.' })Nonelogger_media.info('video-dir migration start: sid=%s from=%s', sid, from_dir)socketio.start_background_task(_video_dir_migrate_task, from_dir, sid))()

def _timer_tick_loop():
    socketio.sleep(1)
    fs = timer.get_full_state('timer')
    if not fs['running'] and not fs['overtime']:
        pass
    payload = {
        'remaining': fs['remaining'],
        'total': fs['total'],
        'state': fs['state'],
        'label': fs['label'],
        'overtime': fs['overtime'] }
    for ch in roles.get_channels('timer'):
        socketio.emit('timer:tick', payload, room = ch)
    for ch in roles.get_channels('order_of_service'):
        socketio.emit('timer:tick', payload, room = ch)

socketio.start_background_task(_timer_tick_loop)
_handle_unexpected_error = (lambda exc: if isinstance(exc, HTTPException):
exclogger.exception('unhandled exception: %s %s', request.method, request.path)(jsonify({
'error': 'internal server error' }), 500))()
_handle_socketio_error = (lambda exc: logger.exception('unhandled socket.io error'))()

def _cloud_update_pump():
    '''Poll cloud_agent flag from eventlet green thread ΓÇö safe to call socketio.emit here.'''
    if cloud_agent._pending_ui_notify:
        cloud_agent._pending_ui_notify = False
        socketio.emit('program:cloud:update', { }, namespace = '/')
    socketio.sleep(0.2)

socketio.start_background_task(_cloud_update_pump)
cloud_agent.start()
if __name__ == '__main__':
    os.makedirs('data', exist_ok = True)
    os.makedirs('data/update', exist_ok = True)
    os.makedirs(LYRICS_DIR, exist_ok = True)
    os.makedirs('output', exist_ok = True)
    os.makedirs('media/images', exist_ok = True)
    os.makedirs('media/videos', exist_ok = True)
    for _p in glob.glob(os.path.join(os.path.dirname(DATA_FILE), '.tmp-*.json')):
        
        try:
            os.unlink(_p)
        except OSError:
            pass

    socketio.run(app, host = '0.0.0.0', port = 5001, debug = False)
glob.glob(os.path.join(os.path.dirname(DATA_FILE), '.tmp-*.json'))
socketio.on_error_default
app.errorhandler(Exception)

