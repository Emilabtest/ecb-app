# eventlet monkey-patch MUST be the very first import
import eventlet
eventlet.monkey_patch()

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger('eventlet.wsgi.server').setLevel(logging.ERROR)

logger        = logging.getLogger('leiturgia.program')
logger_socket = logging.getLogger('leiturgia.socket')
logger_media  = logging.getLogger('leiturgia.media')

from flask import Flask, render_template, request, jsonify, send_file, session, redirect
from werkzeug.exceptions import HTTPException
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json, os, copy, re, requests, uuid, time, glob, subprocess
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

# --- Windows build additions (our code) ---
import tempfile
import ctypes
import shutil
import hashlib
import updater

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024   # 200 MB upload limit

with open('config.json') as _f:
    _config = json.load(_f)
_log_level = getattr(logging, _config.get('log_level', 'INFO').upper(), logging.INFO)
logging.getLogger().setLevel(_log_level)
app.secret_key = _config['session_secret']
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=_config.get('session_timeout_hours', 8))

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')
limiter  = Limiter(get_remote_address, app=app, default_limits=[])
proj     = ProjectionStateManager()
timer    = TimerManager()
roles    = RoleManager()
oos      = OrderOfServiceManager()

_active_item = {
    'program_id':       None,
    'item_id':          None,
    'allotted_seconds': 0,
    'title':            '',
    'participant':      '',
}
_announcement_text = ''

DATA_FILE    = "data/program.json"
HISTORY_FILE = "data/history.json"
HISTORY_MAX  = 6
LYRICS_DIR   = "data/lyrics"


def _lyrics_key(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")


def _slugify(name: str, existing_ids: list = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not existing_ids or slug not in existing_ids:
        return slug
    n = 2
    while f"{slug}-{n}" in existing_ids:
        n += 1
    return f"{slug}-{n}"


def _lyrics_path(key: str) -> str:
    return os.path.join(LYRICS_DIR, f"{key}.json")


def _load_lyrics(path, hint_number=None, hint_title=None):
    """Load a lyrics JSON file. Migrates old plain-array format to the new
    object format {hymn_number, title, stanzas} on first access.
    Returns the data dict (always has a 'stanzas' key)."""
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, list):
        # Old format — build metadata and re-save
        hymn_number = hint_number
        hymn_title  = hint_title
        if not hymn_number:
            key = os.path.splitext(os.path.basename(path))[0]
            if key.isdigit():
                hymn_number = int(key)
            else:
                m = re.match(r'^[a-z]+-(\d+)$', key)
                if m:
                    hymn_number = int(m.group(1))
        if hymn_number and not hymn_title:
            db = get_by_number(hymn_number)
            if db:
                hymn_title = db["title"]
        data = {"stanzas": data}
        if hymn_number: data["hymn_number"] = hymn_number
        if hymn_title:  data["title"]       = hymn_title
        atomic_write_json(path, data)

    return data


# ── Default program template ─────────────────────────────────────────────────
DEFAULT_PROGRAM = {
    "church":      "",
    "date":        "",
    "pianist":     "",
    "song_leader": "",

    "service_programs": [
        {
            "id":    "program",
            "name":  "Program",
            "time":  "",
            "items": [
                {"item_id": "sp-001", "type": "participant", "title": "Opening Prayer", "part": "Opening Prayer", "participant": ""},
                {"item_id": "sp-002", "type": "song",        "title": "Opening Song",   "hymn_number": ""},
                {"item_id": "sp-003", "type": "media",       "title": "Welcome",        "media_type": "image",    "url": "/media/images/leiturgia-welcome.png"},
                {"item_id": "sp-004", "type": "media",       "title": "Video",   "media_type": "video",    "url": "", "autoplay": True, "loop": False, "mute": False},
                {"item_id": "sp-005", "type": "content",     "title": "Announcements",  "content": ""},
                {"item_id": "sp-006", "type": "bible",       "title": "John 3:16",      "bible_ref": "John 3:16", "bible_lang": "en"},
            ],
        },
    ],

    "service_team": [],
}


def _migrate_item(item, item_id=""):
    """Convert a legacy-schema item (with 'participants') to the new typed schema."""
    if "type" in item:
        return item
    parts  = item.get("participants", [])
    p_name = parts[0].get("name", "") if parts else ""
    if "hymn_number" in item:
        return {
            "item_id":     item_id,
            "type":        "song",
            "title":       item.get("title", ""),
            "hymn_number": item.get("hymn_number", ""),
            "hymn_lang":   item.get("hymn_lang", "en"),
            **({} if not item.get("lyrics_key") else {"lyrics_key": item["lyrics_key"]}),
        }
    return {
        "item_id":     item_id,
        "type":        "participant",
        "title":       item.get("title", ""),
        "part":        item.get("subtitle", "") or item.get("title", ""),
        "participant": p_name,
    }


def _migrate_items(items, prefix="item"):
    return [_migrate_item(it, item_id=it.get("item_id", f"{prefix}-{i+1:03d}"))
            for i, it in enumerate(items)]


def load_program():
    if os.path.exists(DATA_FILE):
        data = None
        for attempt in range(3):
            try:
                with open(DATA_FILE) as f:
                    data = json.load(f)
                break
            except json.JSONDecodeError:
                if attempt == 2:
                    raise
                logger.warning("program.json read failed (attempt %d/3), retrying", attempt + 1)
                time.sleep(0.1)

        # ── Migrate old schema (sabbath_school / divine_service keys) ──────────
        if "sabbath_school" in data and "divine_service" in data:
            ss = data["sabbath_school"]
            ds = data["divine_service"]

            ss_items = ss.get("items", [])
            if ss_items and "type" not in ss_items[0]:
                ss_items = _migrate_items(ss_items, "ss")

            ds_items = []
            for sub in ds.get("subsections", []):
                items = sub.get("items", [])
                if items and "type" not in items[0]:
                    items = _migrate_items(items, "ds")
                ds_items.extend(items)

            data = {
                "church":      data.get("church", ""),
                "date":        data.get("date", ""),
                "pianist":     data.get("pianist", ""),
                "song_leader": data.get("song_leader", ""),
                "service_programs": [
                    {
                        "id":    "sabbath-school",
                        "name":  "Sabbath School",
                        "time":  ss.get("time", "9:00 a.m."),
                        "items": ss_items,
                    },
                    {
                        "id":    "divine-service",
                        "name":  "Divine Service",
                        "time":  ds.get("time", "10:30 a.m."),
                        "items": ds_items,
                    },
                ],
                "service_team": data.get("service_team", []),
            }

        # ── Migrate items within new schema if they still use legacy shape ──────
        for sp in data.get("service_programs", []):
            items = sp.get("items", [])
            if items and "type" not in items[0]:
                sp["items"] = _migrate_items(items, sp["id"][:2])
            # ── Rename old "content" participant items → "participant" ──────────
            for item in sp.get("items", []):
                if item.get("type") == "content" and "participant" in item:
                    item["type"] = "participant"

        return data
    return copy.deepcopy(DEFAULT_PROGRAM)


def _ensure_item_ids(program: dict) -> None:
    """Assign a unique item_id to any item that is missing one."""
    for sp in program.get("service_programs", []):
        for item in sp.get("items", []):
            if not item.get("item_id"):
                item["item_id"] = str(uuid.uuid4())


def save_program(data):
    _ensure_item_ids(data)
    atomic_write_json(DATA_FILE, data)
    logger.info("program saved (%d program(s))", len(data.get("service_programs", [])))


def _broadcast_order_of_service(program):
    state = timer.get_full_state('timer')['state']
    payload = oos.get_display(program, state)
    for ch in roles.get_channels('order_of_service'):
        socketio.emit('order_of_service:update', payload, room=ch)


def save_history(program):
    """Append a snapshot of the current program to history (capped at HISTORY_MAX)."""
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        except Exception:
            logger.warning("history file unreadable, starting empty", exc_info=True)
            history = []

    snapshot = {
        "saved_at":        datetime.now().isoformat(),
        "church":          program.get("church", ""),
        "date":            program.get("date", ""),
        "service_programs": [
            {
                "id":    sp["id"],
                "name":  sp["name"],
                "items": sp.get("items", []),
            }
            for sp in program.get("service_programs", [])
        ],
    }
    history.insert(0, snapshot)
    history = history[:HISTORY_MAX]
    atomic_write_json(HISTORY_FILE, history)


def _prepare_lyrics(items):
    """Load lyrics from cache for song items."""
    for item in items:
        if item.get("type") != "song":
            continue
        if item.get("lyrics_key"):
            path = _lyrics_path(item["lyrics_key"])
            if os.path.exists(path):
                data = _load_lyrics(path,
                                    hint_number=item.get("hymn_number"),
                                    hint_title=item.get("title"))
                item["lyrics"] = data["stanzas"]
        elif item.get("hymn_number") and not item.get("lyrics"):
            hymn_lang = item.get("hymn_lang", "en")
            result = get_by_number(int(item["hymn_number"]), lang=hymn_lang)
            if result:
                item["lyrics"] = result["stanzas"]


# ── Auth ─────────────────────────────────────────────────────────────────────
def operator_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('operator'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
            return redirect(f'/login?next={request.path}')
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == 'POST':
        data = request.get_json() or {}
        pin  = str(data.get('pin') or '').strip()
        with open('config.json') as f:
            cfg = json.load(f)
        if pin == str(cfg['pin']):
            session.permanent = True
            session['operator'] = True
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'error', 'message': 'Incorrect PIN'}), 401
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ── Routes ───────────────────────────────────────────────────────────────────
def _server_ip() -> str:
    import socket as _sock
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


@app.route("/")
@operator_required
def index():
    program = load_program()
    return render_template("index.html", program=program, server_ip=_server_ip())


@app.route("/studio")
@operator_required
def studio():
    return render_template("studio.html")


_BROADCAST_FILE = "data/broadcast.json"
_BROADCAST_DEFAULTS = {
    "destination": "facebook",
    "rtmp_url": "",
    "stream_key": "",
    "title": "Saturday Worship Service",
    "state": "idle",
    "started_at": None,
}


def _load_broadcast():
    if os.path.isfile(_BROADCAST_FILE):
        try:
            with open(_BROADCAST_FILE, "r", encoding="utf-8") as _f:
                data = json.load(_f)
            if isinstance(data, dict):
                merged = dict(_BROADCAST_DEFAULTS)
                merged.update(data)
                return merged
        except Exception:
            logger.warning("broadcast config unreadable", exc_info=True)
    return dict(_BROADCAST_DEFAULTS)


def _save_broadcast(data):
    atomic_write_json(_BROADCAST_FILE, data)


@app.route("/api/broadcast/config", methods=["GET"])
@operator_required
def api_broadcast_config():
    c = _load_broadcast()
    return jsonify({
        "destination":   c["destination"],
        "rtmp_url":      c["rtmp_url"],
        "title":         c["title"],
        "stream_key_set": bool(c["stream_key"]),
        "key_tail":      (c["stream_key"][-4:] if c["stream_key"] else ""),
    })


@app.route("/api/broadcast/config", methods=["POST"])
@operator_required
def api_broadcast_config_save():
    body = request.get_json(silent=True) or {}
    c = _load_broadcast()
    dest = body.get("destination")
    if dest in ("facebook", "youtube"):
        c["destination"] = dest
    if isinstance(body.get("rtmp_url"), str):
        c["rtmp_url"] = body["rtmp_url"].strip()
    if isinstance(body.get("stream_key"), str):
        c["stream_key"] = body["stream_key"].strip()
    if isinstance(body.get("title"), str):
        c["title"] = body["title"].strip()
    _save_broadcast(c)
    return jsonify({"ok": True})


@app.route("/api/broadcast/start", methods=["POST"])
@operator_required
def api_broadcast_start():
    c = _load_broadcast()
    c["state"] = "live"
    c["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_broadcast(c)
    return jsonify({"ok": True, "state": c["state"]})


@app.route("/api/broadcast/stop", methods=["POST"])
@operator_required
def api_broadcast_stop():
    c = _load_broadcast()
    c["state"] = "idle"
    c["started_at"] = None
    _save_broadcast(c)
    return jsonify({"ok": True, "state": c["state"]})


@app.route("/api/broadcast/status")
@operator_required
def api_broadcast_status():
    c = _load_broadcast()
    return jsonify({
        "state":       c["state"],
        "destination": c["destination"],
        "started_at":  c["started_at"],
        "simulated":   True,
    })


@app.route("/api/health")
def health():
    checks = {}
    healthy = True

    try:
        load_program()
        checks["program"] = True
    except Exception:
        logger.warning("health check: load_program failed", exc_info=True)
        checks["program"] = False
        healthy = False

    try:
        roles.to_dict()
        checks["roles"] = True
    except Exception:
        logger.warning("health check: roles manager failed", exc_info=True)
        checks["roles"] = False
        healthy = False

    # Soft signal: cloud is LAN-only by design, so an offline cloud must not flip the box unhealthy.
    checks["cloud"] = cloud_agent.status

    body = {"status": "ok" if healthy else "error", "version": get_version(), "checks": checks}
    return jsonify(body), 200 if healthy else 503


@app.route("/api/program", methods=["GET"])
@operator_required
def get_program():
    return jsonify(load_program())


@app.route("/api/program", methods=["POST"])
@operator_required
def save_program_route():
    data = request.get_json()
    save_program(data)
    save_history(data)
    cloud_agent.notify_program_saved(data)
    _broadcast_order_of_service(data)
    return jsonify({"status": "saved"})


@app.route("/api/history")
@operator_required
def get_history():
    if not os.path.exists(HISTORY_FILE):
        return jsonify([])
    try:
        with open(HISTORY_FILE) as f:
            return jsonify(json.load(f))
    except Exception:
        logger.warning("history file unreadable", exc_info=True)
        return jsonify([])


@app.route("/api/fetch-hymn/<int:number>")
@operator_required
def fetch_hymn(number):
    lang = request.args.get("lang", "en")
    result = get_by_number(number, lang=lang)
    if not result:
        return jsonify({"status": "error", "message": "Hymn not found"}), 404
    return jsonify({"status": "ok", "stanzas": result["stanzas"], "lang": lang})


@app.route("/api/fetch-lyrics")
@operator_required
def fetch_lyrics_route():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"status": "error", "message": "No query provided"}), 400
    try:
        lang        = request.args.get("lang", "en")
        hymn_number = None
        hymn_title  = None

        if q.isdigit():
            key = f"{lang}-{q}"
            hymn_number = int(q)
        else:
            # Resolve title → hymn number via local DB so key is always numeric
            db_result = get_by_title(q, lang=lang)
            if db_result:
                key         = f"{lang}-{db_result['number']}"
                hymn_number = db_result["number"]
                hymn_title  = db_result["title"]
            else:
                key = _lyrics_key(q)

        path = _lyrics_path(key)
        if os.path.exists(path):
            data    = _load_lyrics(path, hint_number=hymn_number, hint_title=hymn_title)
            stanzas = data["stanzas"]
            hymn_number = hymn_number or data.get("hymn_number")
            hymn_title  = hymn_title  or data.get("title")
            resp = {"status": "ok", "key": key, "count": len(stanzas), "source": "cache", "lang": lang}
            if hymn_number: resp["hymn_number"] = hymn_number
            if hymn_title:  resp["title"]       = hymn_title
            return jsonify(resp)

        result = get_by_number(hymn_number, lang=lang) if hymn_number else get_by_title(q, lang=lang)
        if not result or not result.get("stanzas"):
            return jsonify({"status": "error", "message": "No lyrics found"})
        stanzas     = result["stanzas"]
        hymn_number = hymn_number or result.get("number")
        hymn_title  = hymn_title  or result.get("title")
        lyrics_data = {"stanzas": stanzas, "lang": lang}
        if hymn_number: lyrics_data["hymn_number"] = hymn_number
        if hymn_title:  lyrics_data["title"]       = hymn_title
        atomic_write_json(path, lyrics_data)
        resp = {"status": "ok", "key": key, "count": len(stanzas), "source": "db", "lang": lang}
        if hymn_number: resp["hymn_number"] = hymn_number
        if hymn_title:  resp["title"]       = hymn_title
        return jsonify(resp)
    except Exception as e:
        logger.exception("lyrics fetch failed: %s", q)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/lyrics/<key>")
@operator_required
def get_lyrics(key):
    path = _lyrics_path(key)
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": "Lyrics file not found"}), 404
    data = _load_lyrics(path)
    return jsonify({"status": "ok", "stanzas": data["stanzas"],
                    "hymn_number": data.get("hymn_number"),
                    "title": data.get("title")})


@app.route("/api/hymnal/search")
@operator_required
def hymnal_search():
    q    = request.args.get("q", "").strip()
    lang = request.args.get("lang", "en")
    if not q:
        return jsonify([])
    if q.isdigit():
        results = search_by_number_prefix(q, limit=8, lang=lang)
    else:
        results = search_titles(q, limit=8, lang=lang)
    for r in results:
        r["lang"] = lang
    return jsonify(results)


LANG_LABELS = {"en": "English", "tl": "Tagalog", "ceb": "Cebuano", "ilo": "Ilocano"}

@app.route("/api/hymnal/languages")
def hymnal_languages():
    import glob
    pattern = os.path.join(os.path.dirname(__file__), "data", "hymns_*.db")
    langs = []
    for path in sorted(glob.glob(pattern)):
        code = os.path.basename(path)[len("hymns_"):-len(".db")]
        langs.append({"code": code, "label": LANG_LABELS.get(code, code.upper())})
    return jsonify(langs)


@app.route("/api/program/add", methods=["POST"])
@operator_required
def add_program():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "Name is required"}), 400
    program = load_program()
    existing_ids = [sp["id"] for sp in program.get("service_programs", [])]
    pid = _slugify(name, existing_ids)
    program["service_programs"].append({"id": pid, "name": name, "time": "", "items": []})
    save_program(program)
    save_history(program)
    _broadcast_order_of_service(program)
    return jsonify({"status": "ok", "id": pid})



@app.route("/api/projection-state", methods=["GET"])
@operator_required
def get_projection_state():
    return jsonify(proj._state)


@app.route("/api/programs/<program_id>", methods=["DELETE"])
@operator_required
def delete_program(program_id):
    program = load_program()
    programs = program.get("service_programs", [])
    if len(programs) <= 1:
        return jsonify({"error": "cannot delete last program"}), 400
    program["service_programs"] = [p for p in programs if p["id"] != program_id]
    save_program(program)
    _broadcast_order_of_service(program)
    return jsonify({"ok": True, "selected": program["service_programs"][0]["id"]})



# ── Remote sync helper ───────────────────────────────────────────────────────
def _item_to_slide_state(item: dict) -> dict:
    """Build the first-slide projection state for a program item."""
    t = item.get('type', 'participant')
    # Items may use type='media' + media_type, or direct type='image'/'video'
    is_video = (t == 'video') or (t == 'media' and item.get('media_type') == 'video')
    is_image = (t == 'image') or (t == 'media' and item.get('media_type') != 'video')
    if is_video:
        return {
            'type': 'video',
            'data': {
                'url':      item.get('url', ''),
                'autoplay': item.get('autoplay', False),
                'loop':     item.get('loop', False),
                'mute':     item.get('mute', False),
            },
            'theme_id': 'default',
        }
    if is_image:
        return {
            'type': 'image',
            'data': {'url': item.get('url', '')},
            'theme_id': 'default',
        }
    if t == 'song':
        manual = item.get('manual_lyrics', '')
        if manual:
            stanzas = [b.strip() for b in manual.split('\n\n') if b.strip()]
            first_lines = stanzas[0].split('\n') if stanzas else []
            first_lines = [l.strip() for l in first_lines if l.strip()]
            return {
                'type': 'text',
                'data': {'title': item.get('title', ''), 'part': item.get('part', ''),
                         'stanza': {'lines': first_lines}},
                'theme_id': 'default',
            }
        return {
            'type': 'text',
            'data': {'title': item.get('title', ''), 'part': item.get('part', ''), 'stanza': ''},
            'theme_id': 'default',
        }
    if t == 'content':
        full = item.get('content', '')
        paras = [p.strip() for p in full.split('\n\n') if p.strip()]
        first_para = paras[0] if paras else full
        return {
            'type': 'text',
            'data': {'title': item.get('title', ''), 'body': first_para, 'part': item.get('part', ''), 'is_content_para': True},
            'theme_id': 'default',
        }
    # participant (default)
    name = item.get('participant', '')
    part = item.get('part', '')
    return {
        'type': 'text',
        'data': {
            'title':        item.get('title', ''),
            'part':         part,
            'participants': [{'role': part, 'name': name}] if name else [],
        },
        'theme_id': 'default',
    }


def _next_sequence_slide(program: dict, item_id: str,
                          slide_url: str | None = None,
                          program_id: str | None = None) -> dict | None:
    """Return the first-slide state for the sequence item immediately after item_id.

    slide_url and program_id disambiguate when multiple items share the same item_id.
    """
    for sp in program.get('service_programs', []):
        if program_id and sp.get('id') != program_id:
            continue
        items = sp.get('items', [])
        for i, it in enumerate(items):
            if it['item_id'] != item_id:
                continue
            # Skip duplicate item_ids that don't match by URL
            if slide_url and it.get('url') and it['url'] != slide_url:
                continue
            for nxt in items[i + 1:]:
                if nxt.get('enabled', True):
                    return _item_to_slide_state(nxt)
            return None
    return None


def roles_channel_map() -> dict:
    """Return {channel: role} from roles.to_dict() which is {role: [channels]}."""
    result = {}
    for role, channels in roles.to_dict().items():
        for ch in channels:
            result[ch] = role
    return result


def build_remote_sync() -> dict:
    state = proj.get_state('ch1')
    data  = state.get('data', {}) if state else {}
    next_stanza = data.get('next_stanza')
    next_slide_data = None
    if next_stanza:
        # Mid-song: show the next stanza
        next_slide_data = {
            'type':     'text',
            'data':     {
                'stanza': next_stanza,
                'title':  data.get('title', ''),
                'part':   data.get('part', ''),
            },
            'theme_id': state.get('theme_id', 'default'),
        }
    elif data.get('is_content_para'):
        # Mid-content: show next paragraph of the same content item
        item_id = data.get('item_id') or _active_item.get('item_id')
        para_idx = data.get('para_idx', 0)
        if item_id:
            program = load_program()
            item = next(
                (it for sp in program.get('service_programs', [])
                 for it in sp.get('items', []) if it['item_id'] == item_id),
                None
            )
            if item:
                full = item.get('content', '')
                paras = [p.strip() for p in full.split('\n\n') if p.strip()]
                if para_idx + 1 < len(paras):
                    next_slide_data = {
                        'type': 'text',
                        'data': {
                            'body': paras[para_idx + 1],
                            'part': data.get('part', ''),
                            'title': data.get('title', ''),
                            'is_content_para': True,
                        },
                        'theme_id': state.get('theme_id', 'default'),
                    }
                else:
                    # Last paragraph — show first slide of next sequence item
                    program_id = _active_item.get('program_id')
                    next_slide_data = _next_sequence_slide(
                        program, item_id, program_id=program_id
                    )
    else:
        # Non-song or last stanza: show first slide of the next sequence item
        item_id   = data.get('item_id') or _active_item.get('item_id')
        slide_url = data.get('url') or data.get('src')
        program_id = _active_item.get('program_id')
        if item_id:
            program = load_program()
            next_slide_data = _next_sequence_slide(
                program, item_id, slide_url=slide_url, program_id=program_id
            )
    return {
        'slide_data':      state or {},
        'slide_index':     data.get('slide_index', 0),
        'slide_count':     data.get('slide_count', 0),
        'item_title':      data.get('title', ''),
        'next_slide_data': next_slide_data,
        'assignments':     roles_channel_map(),
    }


# ── Projection routes ────────────────────────────────────────────────────────
_ROLE_TEMPLATE = {
    'main':              'projection.html',
    'order_of_service':  'order_of_service.html',
    'timer':             'timer_display.html',
    'announcement':      'announcement.html',
}

@app.route("/ch<int:n>")
def projection_channel(n):
    channel  = f"ch{n}"
    role     = roles.get_role(channel) or 'main'
    template = _ROLE_TEMPLATE.get(role, 'projection.html')
    program  = load_program()
    timer_fs = timer.get_full_state('timer')
    oos_data = oos.get_display(program, timer_fs['state'])
    return render_template(
        template,
        channel=channel,
        role=role,
        order_of_service=oos_data,
        timer_state=timer_fs,
        active_item=_active_item,
        announcement=_announcement_text,
    )


@app.route("/custom")
def custom_output_route():
    return render_template(
        "custom_output.html",
        channel="ch1",
        role="main",
        aspect="auto",
        announcement=_announcement_text,
    )


@app.route("/remote")
@operator_required
def remote():
    return render_template("remote.html")


@app.route("/share")
def share():
    """Presenting PC page: captures the screen and streams it to the server."""
    return render_template("share.html")


# ── Static theme files ───────────────────────────────────────────────────────
from flask import send_from_directory

_THEMES = [
    {"id": "default",  "name": "Default (Navy/Gold)"},
    {"id": "midnight", "name": "Midnight"},
    {"id": "dawn",     "name": "Dawn"},
    {"id": "forest",   "name": "Forest"},
    {"id": "slate",    "name": "Slate"},
    {"id": "ivory",    "name": "Ivory (Light)"},
    {"id": "ocean",    "name": "Ocean"},
    {"id": "ember",    "name": "Ember"},
    {"id": "pearl",    "name": "Pearl"},
    {"id": "royal",    "name": "Royal"},
]

@app.route("/static/themes/<path:filename>")
def serve_theme(filename):
    themes_dir = os.path.join(app.root_path, "templates", "themes")
    return send_from_directory(themes_dir, filename)

@app.route("/api/themes")
@operator_required
def api_themes():
    return jsonify(_THEMES)


# ── SocketIO event handlers ──────────────────────────────────────────────────
@socketio.on('connect')
def on_connect():
    logger_socket.debug("connect: sid=%s", request.sid)


@socketio.on('disconnect')
def on_disconnect(*args):
    logger_socket.debug("disconnect: sid=%s", request.sid)
    _live_remove_source(request.sid)


@socketio.on('join')
def on_join(data):
    channel = data.get('channel', 'ch1')
    join_room(channel)
    role = roles.get_role(channel)
    logger_socket.info("join: sid=%s channel=%s role=%s", request.sid, channel, role)
    if role == 'order_of_service':
        program    = load_program()
        timer_fs   = timer.get_full_state('timer')
        payload    = oos.get_display(program, timer_fs['state'])
        emit('order_of_service:update', payload)
    elif role == 'timer':
        fs = timer.get_full_state('timer')
        emit('timer:tick', {
            'remaining': fs['remaining'],
            'total':     fs['total'],
            'state':     fs['state'],
            'label':     fs['label'],
            'overtime':  fs['overtime'],
        })
    elif role == 'announcement':
        if _announcement_text:
            emit('announcement:update', {'text': _announcement_text})

@socketio.on('remote:join')
def on_remote_join():
    if not session.get('operator'):
        disconnect()
        return
    join_room('remote-clients')
    logger_socket.info("join: sid=%s channel=remote-clients role=remote", request.sid)
    emit('remote:sync', build_remote_sync())

@socketio.on('console:join')
def on_console_join():
    if not session.get('operator'):
        disconnect()
        return
    join_room('console')
    join_room('ch1')  # default channel; switched via console:watch
    logger_socket.info("join: sid=%s channel=console role=operator", request.sid)
    emit('live:sources', _live_sources_payload())
    emit('live:selection', _live_selected_payload())

@socketio.on('console:watch')
def on_console_watch(data):
    if not session.get('operator'):
        disconnect()
        return
    old_ch = data.get('old', 'ch1')
    new_ch = data.get('new', 'ch1')
    valid  = ('ch1', 'ch2', 'ch3', 'ch4', 'ch5')
    if old_ch in valid:
        leave_room(old_ch)
    if new_ch in valid:
        join_room(new_ch)

# ── Remote-live relay ──────────────────────────────────────────────────────────
# Multiple presenting PCs open /share and stream compressed screen frames here.
# The operator (console) picks which source each projection channel shows; the
# server relays that source's latest frame to the matching channel rooms.
#
#   _live_sources[sid]      -> {"name": str, "w": int, "h": int}
#   _live_last_frame[sid]   -> base64 JPEG string (data: prefix stripped)
#   _live_selected[channel] -> sid currently shown on that channel
_live_sources     = {}
_live_last_frame  = {}
_live_selected    = {}

_LIVE_VALID_CH = ('ch1', 'ch2', 'ch3', 'ch4', 'ch5')


def _live_sources_payload():
    return {
        sid: {'name': info['name'], 'w': info['w'], 'h': info['h']}
        for sid, info in _live_sources.items()
    }


def _live_broadcast_sources():
    socketio.emit('live:sources', _live_sources_payload(), room='console')


def _live_selected_payload():
    return {
        ch: sid for ch, sid in _live_selected.items()
        if sid in _live_sources
    }


def _live_broadcast_selection():
    socketio.emit('live:selection', _live_selected_payload(), room='console')


@socketio.on('live:register')
def on_live_register(data):
    data = data or {}
    name = (str(data.get('name') or 'Presenter')).strip()[:40] or 'Presenter'
    _live_sources[request.sid] = {
        'name': name,
        'w': int(data.get('w') or 0),
        'h': int(data.get('h') or 0),
    }
    logger_socket.info("live:register sid=%s name=%s", request.sid, name)
    _live_broadcast_sources()
    emit('live:registered', {'sid': request.sid})


@socketio.on('live:frame')
def on_live_frame(data):
    # Presenter stream frame. data: {"data": <base64>, "w": int, "h": int}
    data = data or {}
    b64 = data.get('data')
    if not b64 or request.sid not in _live_sources:
        return
    _live_last_frame[request.sid] = b64
    if not _live_selected:
        return
    w = int(data.get('w') or 0)
    h = int(data.get('h') or 0)
    payload = {'sid': request.sid, 'data': b64, 'w': w, 'h': h}
    for ch, sid in _live_selected.items():
        if sid == request.sid:
            socketio.emit('live:frame', payload, room=ch)


@socketio.on('live:select')
def on_live_select(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    source  = data.get('source')
    if channel not in _LIVE_VALID_CH:
        return
    if not source or source not in _live_sources:
        return
    _live_selected[channel] = source
    info = _live_sources[source]
    state = {
        'type': 'live',
        'data': {
            'source': source,
            'name': info['name'],
            'w': info['w'],
            'h': info['h'],
        },
        'theme_id': 'default',
    }
    proj.set_state(channel, state)
    socketio.emit('live:start', state['data'], room=channel)
    _live_broadcast_selection()
    # If we already have a frame buffered, push it immediately so the
    # projection isn't blank until the next presenter frame.
    if source in _live_last_frame:
        socketio.emit('live:frame', {
            'sid': source,
            'data': _live_last_frame[source],
            'w': info['w'],
            'h': info['h'],
        }, room=channel)


@socketio.on('live:stop')
def on_live_stop(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    if channel not in _LIVE_VALID_CH:
        return
    if channel not in _live_selected:
        return
    del _live_selected[channel]
    proj.set_state(channel, {'type': 'blank', 'data': {}, 'theme_id': 'default'})
    socketio.emit('live:stop', {'channel': channel}, room=channel)
    socketio.emit('slide:blank', {'type': 'blank', 'data': {}, 'theme_id': 'default'}, room=channel)
    _live_broadcast_selection()


def _live_remove_source(sid):
    if sid not in _live_sources:
        return
    del _live_sources[sid]
    _live_last_frame.pop(sid, None)
    # Any channel showing this source returns to blank.
    for ch in list(_live_selected.keys()):
        if _live_selected.get(ch) == sid:
            del _live_selected[ch]
            proj.set_state(ch, {'type': 'blank', 'data': {}, 'theme_id': 'default'})
            socketio.emit('live:stop', {'channel': ch}, room=ch)
            socketio.emit('slide:blank', {'type': 'blank', 'data': {}, 'theme_id': 'default'}, room=ch)
    _live_broadcast_sources()
    _live_broadcast_selection()

@socketio.on('remote:next')
def on_remote_next():
    if not session.get('operator'):
        disconnect()
        return
    socketio.emit('remote:next', {}, room='console')

@socketio.on('remote:prev')
def on_remote_prev():
    if not session.get('operator'):
        disconnect()
        return
    socketio.emit('remote:prev', {}, room='console')

@socketio.on('remote:blank')
def on_remote_blank():
    if not session.get('operator'):
        disconnect()
        return
    socketio.emit('remote:blank', {}, room='console')

@socketio.on('state:restore')
def on_state_restore(data):
    channel = data.get('channel', 'ch1')
    state   = proj.get_state(channel)
    # If this MAIN channel has no content yet, mirror another MAIN channel that does
    if state.get('type') == 'blank' and roles.get_role(channel) == 'main':
        for ch in roles.get_channels('main'):
            if ch != channel:
                s = proj.get_state(ch)
                if s.get('type') != 'blank':
                    state = s
                    break
    if state.get('type') != 'blank':
        emit('slide:show', state)

@socketio.on('slide:show')
def on_slide_show(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state   = {'type': 'text', 'data': data, 'theme_id': data.get('theme_id', 'default')}
    for ch in roles.get_channels(roles.get_role(channel) or 'main'):
        proj.set_state(ch, state)
        socketio.emit('slide:show', data, room=ch)
    socketio.emit('remote:sync', build_remote_sync(), room='remote-clients')

@socketio.on('slide:blank')
def on_slide_blank(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state   = {'type': 'blank', 'data': {}, 'theme_id': 'default'}
    for ch in roles.get_channels(roles.get_role(channel) or 'main'):
        proj.set_state(ch, state)
        socketio.emit('slide:blank', state, room=ch)
    socketio.emit('remote:sync', build_remote_sync(), room='remote-clients')

@socketio.on('slide:edit')
def on_slide_edit(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state   = {'type': 'text', 'data': data, 'theme_id': data.get('theme_id', 'default')}
    for ch in roles.get_channels(roles.get_role(channel) or 'main'):
        proj.set_state(ch, state)
        socketio.emit('slide:edit', data, room=ch)

@socketio.on('media:image')
def on_media_image(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state   = {'type': 'image', 'data': data, 'theme_id': 'default'}
    for ch in roles.get_channels(roles.get_role(channel) or 'main'):
        proj.set_state(ch, state)
        socketio.emit('media:image', data, room=ch)
    socketio.emit('remote:sync', build_remote_sync(), room='remote-clients')

@socketio.on('media:video')
def on_media_video(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state   = {'type': 'video', 'data': data, 'theme_id': 'default'}
    for ch in roles.get_channels(roles.get_role(channel) or 'main'):
        proj.set_state(ch, state)
        socketio.emit('media:video', data, room=ch)
    socketio.emit('remote:sync', build_remote_sync(), room='remote-clients')

@socketio.on('media:status')
def on_media_status(data):
    channel = data.get('channel', 'ch1')
    emit('media:status', data, to=channel)

@socketio.on('media:blocked')
def on_media_blocked(data):
    channel = data.get('channel', 'ch1')
    emit('media:blocked', data, to=channel)

@socketio.on('announcement')
def on_announcement(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state   = {'type': 'announcement', 'data': data, 'theme_id': 'default'}
    proj.set_state(channel, state)
    emit('announcement', data, to=channel)

@socketio.on('timer:show')
def on_timer_show(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state_d = timer.show(channel, int(data.get('seconds', 0)), data.get('label', ''))
    state_d.update({'channel': channel, 'type': 'timer'})
    proj.set_state(channel, {'type': 'timer', 'data': state_d, 'theme_id': 'default'})
    emit('timer:show', state_d, to=channel)

@socketio.on('timer:start')
def on_timer_start(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    secs    = data.get('seconds')
    label   = data.get('label')
    state_d = timer.start(channel, int(secs) if secs is not None else None, label)
    state_d.update({'channel': channel, 'type': 'timer'})
    proj.set_state(channel, {'type': 'timer', 'data': state_d, 'theme_id': 'default'})
    emit('timer:start', state_d, to=channel)

@socketio.on('timer:pause')
def on_timer_pause(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    state_d = timer.pause(channel)
    state_d.update({'channel': channel})
    emit('timer:pause', state_d, to=channel)

@socketio.on('timer:reset')
def on_timer_reset(data):
    if not session.get('operator'):
        disconnect()
        return
    channel = data.get('channel', 'ch1')
    secs    = data.get('seconds')
    state_d = timer.reset(channel, int(secs) if secs is not None else None)
    state_d.update({'channel': channel, 'type': 'timer'})
    proj.set_state(channel, {'type': 'timer', 'data': state_d, 'theme_id': 'default'})
    emit('timer:reset', state_d, to=channel)


# ── Role assignment ───────────────────────────────────────────────────────────

_VALID_ROLES    = ('main', 'order_of_service', 'timer', 'announcement')
_VALID_CHANNELS = ('ch1', 'ch2', 'ch3', 'ch4', 'ch5')

@socketio.on('roles:assign')
def on_roles_assign(data):
    if not session.get('operator'):
        disconnect()
        return
    role     = data.get('role', '')
    channels = data.get('channels', [])
    if role not in _VALID_ROLES:
        emit('error', {'message': f'Invalid role: {role}'})
        return
    if not channels or not all(ch in _VALID_CHANNELS for ch in channels):
        emit('error', {'message': 'Invalid or empty channels list'})
        return
    roles.assign(channels, role)
    socketio.emit('roles:updated', {'assignments': roles_channel_map()})

@app.route('/api/roles', methods=['GET'])
@operator_required
def api_roles_get():
    return jsonify({'assignments': roles.to_dict()})

@app.route('/api/roles', methods=['POST'])
@operator_required
def api_roles_post():
    data     = request.get_json() or {}
    role     = data.get('role', '')
    channels = data.get('channels', [])
    if role not in _VALID_ROLES:
        return jsonify({'status': 'error', 'message': f'Invalid role: {role}'}), 400
    if not channels or not all(ch in _VALID_CHANNELS for ch in channels):
        return jsonify({'status': 'error', 'message': 'Invalid or empty channels list'}), 400
    roles.assign(channels, role)
    ch_map = roles_channel_map()
    socketio.emit('roles:updated', {'assignments': ch_map})
    return jsonify({'assignments': ch_map})


# ── Active item control ───────────────────────────────────────────────────────

_DEFAULT_ALLOTTED = {'song': 4, 'prayer': 3, 'content': 5, 'participant': 5, 'media': 5}

@socketio.on('program:item:set')
def on_program_item_set(data):
    if not session.get('operator'):
        disconnect()
        return
    global _active_item
    program_id = data.get('program_id', '')
    item_id    = data.get('item_id', '')
    program    = load_program()

    item = None
    for sp in program.get('service_programs', []):
        if sp['id'] == program_id:
            for it in sp.get('items', []):
                if it['item_id'] == item_id:
                    item = it
                    break
    if item is None:
        emit('error', {'message': 'Item not found'})
        return

    if not item.get('enabled', True):
        # Single choke point: this is the only socket handler that looks up an
        # item by id before sending it live. `slide:show`/`media:image`/
        # `media:video` forward pre-assembled slide payloads from a trusted
        # single-operator client and don't perform item lookups — a deliberate
        # scope decision (not an oversight) given this app's LAN-only,
        # single-operator, trusted-client threat model.
        emit('error', {'message': 'Item is disabled'})
        return

    is_timed = item.get('timed', True)
    allotted_mins = item.get('allotted_minutes') or _DEFAULT_ALLOTTED.get(item.get('type', 'participant'), 5)
    allotted_secs = int(allotted_mins) * 60

    _active_item = {
        'program_id':       program_id,
        'item_id':          item_id,
        'allotted_seconds': allotted_secs if is_timed else 0,
        'title':            item.get('title', ''),
        'participant':      item.get('participant', ''),
        'timed':            is_timed,
    }

    oos.set_active(program_id, item_id)

    if is_timed:
        timer.reset('timer', allotted_secs)
        timer.start('timer')
        timer_state = timer.get_full_state('timer')['state']
    else:
        timer.pause('timer')
        timer_state = 'normal'
        for ch in roles.get_channels('timer'):
            socketio.emit('timer:idle', {}, room=ch)

    oos_payload = oos.get_display(program, timer_state)
    for ch in roles.get_channels('order_of_service'):
        socketio.emit('order_of_service:update', oos_payload, room=ch)

    slide_state = proj.get_state(roles.get_channels('main')[0] if roles.get_channels('main') else 'ch1')
    for ch in roles.get_channels('main'):
        socketio.emit('state:update', {'item': _active_item}, room=ch)

    item_update = {'title': _active_item['title'], 'participant': _active_item['participant']}
    for ch in roles.get_channels('timer'):
        socketio.emit('active:item:updated', item_update, room=ch)

@app.route('/api/active-item', methods=['GET'])
@operator_required
def api_active_item():
    return jsonify({'item': _active_item if _active_item['item_id'] else None})


# ── Announcement ──────────────────────────────────────────────────────────────

@socketio.on('announcement:push')
def on_announcement_push(data):
    if not session.get('operator'):
        disconnect()
        return
    global _announcement_text
    _announcement_text = data.get('text', '')
    for ch in roles.get_channels('announcement'):
        socketio.emit('announcement:update', {'text': _announcement_text}, room=ch)

@socketio.on('announcement:blank')
def on_announcement_blank(data):
    if not session.get('operator'):
        disconnect()
        return
    global _announcement_text
    _announcement_text = ''
    for ch in roles.get_channels('announcement'):
        socketio.emit('announcement:blank', {}, room=ch)

@app.route('/api/announcement', methods=['POST'])
@operator_required
def api_announcement_push():
    global _announcement_text
    data = request.get_json() or {}
    _announcement_text = data.get('text', '')
    for ch in roles.get_channels('announcement'):
        socketio.emit('announcement:update', {'text': _announcement_text}, room=ch)
    return jsonify({'status': 'pushed'})

@app.route('/api/announcement/blank', methods=['POST'])
@operator_required
def api_announcement_blank():
    global _announcement_text
    _announcement_text = ''
    for ch in roles.get_channels('announcement'):
        socketio.emit('announcement:blank', {}, room=ch)
    return jsonify({'status': 'blanked'})


# ── Media routes ─────────────────────────────────────────────────────────────
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
_VIDEO_EXTS = {'.mp4', '.webm', '.mov'}

@app.route("/api/media")
@operator_required
def api_media():
    data = list_media()
    data["usage"]  = media_manager.usage()
    data["in_use"] = media_manager.referenced_media()
    return jsonify(data)

@app.route("/api/media/<media_type>/<filename>", methods=["DELETE"])
@operator_required
def delete_media_file(media_type, filename):
    if media_type not in ("images", "videos"):
        return jsonify({"status": "error", "message": "Invalid media type"}), 400
    safe = os.path.basename(filename)
    if not safe or safe != filename:
        return jsonify({"status": "error", "message": "Invalid filename"}), 400
    type_dir = media_manager.videos_dir() if media_type == "videos" else os.path.join(app.root_path, "media", "images")
    path = os.path.join(type_dir, safe)
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": "File not found"}), 404
    # In-use guard (TDD §5.3a) — a file still referenced by the current
    # program.json is never removed from disk by any delete path.
    used_by = media_manager.referenced_media().get(safe)
    if used_by:
        return jsonify({
            "status":  "error",
            "code":    "media_in_use",
            "message": f'"{safe}" is used by a saved program item and cannot be deleted.',
            "used_by": used_by,
        }), 409
    try:
        os.remove(path)
        return jsonify({"status": "ok"})
    except OSError as e:
        logger.exception("media delete failed: %s", path)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/media/videos/delete", methods=["POST"])
@operator_required
def delete_media_videos_bulk():
    """Bulk-delete videos, per media-storage-budget TDD §5.4/§5.3a.
    Body: {filenames: [...]}. Returns {deleted: [...], failed: [{name, reason,
    used_by?}], usage: {...}}. One in-use or missing file never blocks the rest
    of the batch."""
    data = request.get_json() or {}
    filenames = data.get("filenames")
    if not isinstance(filenames, list) or not filenames:
        return jsonify({"status": "error", "message": "No filenames provided"}), 400

    in_use    = media_manager.referenced_media()
    videos_dir = media_manager.videos_dir()
    deleted, failed = [], []

    for filename in filenames:
        if not isinstance(filename, str):
            failed.append({"name": str(filename), "reason": "invalid_filename"})
            continue
        safe = os.path.basename(filename)
        if not safe or safe != filename:
            failed.append({"name": filename, "reason": "invalid_filename"})
            continue
        used_by = in_use.get(safe)
        if used_by:
            failed.append({"name": safe, "reason": "in_use", "used_by": used_by})
            continue
        path = os.path.join(videos_dir, safe)
        if not os.path.exists(path):
            failed.append({"name": safe, "reason": "not_found"})
            continue
        try:
            os.remove(path)
            deleted.append(safe)
        except OSError as e:
            logger.exception("media bulk delete failed: %s", path)
            failed.append({"name": safe, "reason": str(e)})

    return jsonify({
        "deleted": deleted,
        "failed":  failed,
        "usage":   media_manager.usage(),
    })

@app.route("/api/media/usb-targets")
@operator_required
def api_media_usb_targets():
    """List writable USB/removable mounts for the export flow. TDD §5.4."""
    return jsonify(media_manager.usb_targets())


# ── Configurable video storage location (media-storage-budget TDD §5.6) ────

def _video_dir_status() -> dict:
    """Shape shared by GET and POST responses for /api/settings/video-dir."""
    vdir  = media_manager.videos_dir()
    usage = media_manager.usage()
    return {
        "status":             "ok",
        "location":           "internal" if vdir == media_manager.VIDEOS_DIR else "external",
        "path":               os.path.abspath(vdir),
        "label":              usage.get("location_label", "Internal"),
        "usage":              usage,
        "videos_unavailable": usage.get("videos_unavailable", False),
    }


@app.route("/api/settings/video-dir", methods=["GET", "POST"])
@operator_required
def api_settings_video_dir():
    if request.method == "GET":
        return jsonify(_video_dir_status())

    data      = request.get_json() or {}
    requested = (data.get("dir") or "").strip()
    previous_path = media_manager.videos_dir()

    if not requested:
        new_dir = media_manager.VIDEOS_DIR
    else:
        if not os.path.isabs(requested):
            return jsonify({"status": "error", "message": "Path must be absolute."}), 400

        # UI picker sends a bare mount root (from /api/media/usb-targets) —
        # nest under leiturgia-videos/ so videos never land in the drive
        # root (TDD §5.6). A caller supplying an already-nested path (e.g.
        # advanced use) is left as-is, still subject to the checks below.
        mounted_roots = {os.path.realpath(t["path"]): t for t in media_manager.usb_targets()}
        try:
            real_requested = os.path.realpath(requested)
        except (OSError, ValueError):
            real_requested = requested
        if real_requested in mounted_roots:
            candidate = os.path.join(requested.rstrip("/"), "leiturgia-videos")
        else:
            candidate = requested

        resolved = media_manager.resolve_export_target(candidate)
        if not resolved:
            return jsonify({
                "status":  "error",
                "message": "Path must be on a mounted, writable removable drive "
                           "(/media, /mnt, or /run/media).",
            }), 400

        if os.path.exists(resolved):
            if not os.path.isdir(resolved):
                return jsonify({"status": "error", "message": "Path exists and is not a directory."}), 400
        else:
            try:
                os.makedirs(resolved, exist_ok=True)
            except OSError as e:
                return jsonify({"status": "error", "message": f"Could not create directory: {e}"}), 400

        if not os.access(resolved, os.W_OK):
            return jsonify({"status": "error", "message": "Path is not writable."}), 400

        new_dir = resolved

    # Never half-applied: everything above is validated before this write.
    with open("config.json") as f:
        cfg = json.load(f)
    cfg["media_video_dir"] = "" if new_dir == media_manager.VIDEOS_DIR else new_dir
    atomic_write_json("config.json", cfg)

    status = _video_dir_status()
    status["previous_path"] = previous_path
    logger_media.info("video storage location changed: %s -> %s", previous_path, status["path"])
    return jsonify(status)


@app.route("/api/yt-title")
@operator_required
def api_yt_title():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"title": None})
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=5,
        )
        if r.ok:
            return jsonify({"title": r.json().get("title")})
    except Exception:
        logger.debug("yt title fetch failed for %s", url, exc_info=True)
    return jsonify({"title": None})

@app.route("/api/yt-cache")
@operator_required
def api_yt_cache():
    if not os.path.exists(_YT_CACHE_PATH):
        return jsonify({})
    with open(_YT_CACHE_PATH) as f:
        return jsonify(json.load(f))

@app.route("/api/settings/pin", methods=["POST"])
@operator_required
def api_settings_pin():
    data = request.get_json() or {}
    pin  = str(data.get('pin') or '').strip()
    if not pin.isdigit() or not (4 <= len(pin) <= 6):
        return jsonify({'status': 'error', 'message': 'PIN must be 4–6 digits'}), 400
    with open('config.json') as f:
        cfg = json.load(f)
    cfg['pin'] = pin
    atomic_write_json('config.json', cfg)
    return jsonify({'status': 'ok'})


@app.route('/api/settings/update-url', methods=["POST"])
@operator_required
def api_settings_update_url():
    data = request.get_json(force=True, silent=True) or {}
    url  = str(data.get('url') or '').strip()
    if not re.match(r'^https?://', url):
        return jsonify({'status': 'error', 'message': 'Enter a valid http(s):// update server URL.'}), 400
    cfg = _update_config()
    cfg['update_url'] = url
    atomic_write_json('config.json', cfg)
    return jsonify({'status': 'ok'})


@app.route('/settings')
@operator_required
def settings():
    cfg = cloud_agent._load_config()
    return render_template('settings.html',
                           enable_self_update=cfg.get('enable_self_update', False),
                           update_url=cfg.get('update_url', ''))


@app.route('/api/cloud/status')
@operator_required
def api_cloud_status():
    with open('config.json') as f:
        cfg = json.load(f)
    return jsonify({
        'status':      cloud_agent.status,
        'linked':      cloud_agent.linked,
        'cloud_url':   cfg.get('cloud_url', ''),
        'cloud_token': cfg.get('cloud_token', ''),
    })


@app.route('/api/cloud/link', methods=['POST'])
@operator_required
def api_cloud_link():
    data = request.get_json() or {}
    cloud_url   = (data.get('cloud_url') or '').strip().rstrip('/')
    cloud_token = (data.get('cloud_token') or '').strip()
    if not cloud_url or not cloud_token:
        return jsonify({'status': 'error', 'message': 'cloud_url and cloud_token are required'}), 400

    try:
        resp = requests.post(
            f'https://{cloud_url}/api/v1/devices/register',
            headers={'Authorization': f'Bearer {cloud_token}'},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        return jsonify({'status': 'error', 'message': f'Could not reach cloud: {exc}'}), 502

    if resp.status_code == 200:
        church_name = resp.json().get('church_name', '')
        with open('config.json') as f:
            cfg = json.load(f)
        cfg['cloud_enabled'] = True
        cfg['cloud_url']     = cloud_url
        cfg['cloud_token']   = cloud_token
        atomic_write_json('config.json', cfg)
        cloud_agent.restart()
        return jsonify({'status': 'linked', 'church_name': church_name})

    if resp.status_code == 401:
        msg = 'Invalid token — not recognised by the cloud.'
    elif resp.status_code == 403:
        msg = 'Device limit reached on the cloud account.'
    else:
        msg = f'Cloud returned {resp.status_code}.'
    return jsonify({'status': 'error', 'message': msg}), 400


@app.route('/api/cloud/unlink', methods=['POST'])
@operator_required
def api_cloud_unlink():
    with open('config.json') as f:
        cfg = json.load(f)
    cfg['cloud_enabled'] = False
    cfg['cloud_token']   = ''
    cfg['cloud_url']     = ''
    atomic_write_json('config.json', cfg)
    return jsonify({'status': 'ok'})


@app.route('/api/cloud/sync-status')
@operator_required
def api_cloud_sync_status():
    try:
        with open(DATA_FILE) as f:
            local = json.load(f)
        sps = local.get('service_programs', [])
        pi_info = {'has_data': len(sps) > 0, 'count': len(sps)}
    except Exception:
        logger.warning("cloud sync status: failed to read local program", exc_info=True)
        pi_info = {'has_data': False, 'count': 0}

    cfg = cloud_agent._load_config()
    if not cfg.get('cloud_enabled') or not cfg.get('cloud_url') or not cfg.get('cloud_token'):
        return jsonify({'linked': False, 'pi': pi_info, 'cloud': None})

    cloud_url   = cfg['cloud_url'].strip().rstrip('/')
    cloud_token = cfg['cloud_token'].strip()
    try:
        resp = requests.get(
            f'https://{cloud_url}/api/v1/programs/device-meta',
            headers={'Authorization': f'Bearer {cloud_token}'},
            timeout=10,
        )
        resp.raise_for_status()
        cloud_info = resp.json()
    except Exception as exc:
        logger.warning("cloud sync status: cloud request failed: %s", exc)
        return jsonify({'linked': True, 'pi': pi_info, 'cloud': None, 'error': str(exc)})

    return jsonify({'linked': True, 'pi': pi_info, 'cloud': cloud_info})


@app.route('/api/cloud/sync', methods=['POST'])
@operator_required
def api_cloud_sync():
    data      = request.get_json() or {}
    direction = data.get('direction')
    if direction not in ('pi_to_cloud', 'cloud_to_pi'):
        return jsonify({'ok': False, 'error': 'invalid direction'}), 400

    cfg         = cloud_agent._load_config()
    cloud_url   = cfg.get('cloud_url', '').strip().rstrip('/')
    cloud_token = cfg.get('cloud_token', '').strip()

    if direction == 'pi_to_cloud':
        try:
            with open(DATA_FILE) as f:
                local = json.load(f)
        except Exception as exc:
            logger.exception("cloud sync: failed to read local program")
            return jsonify({'ok': False, 'error': str(exc)}), 500
        cloud_agent.force_push_program(local)
        return jsonify({'ok': True})

    # cloud_to_pi
    try:
        resp = requests.get(
            f'https://{cloud_url}/api/v1/programs/device-current',
            headers={'Authorization': f'Bearer {cloud_token}'},
            timeout=10,
        )
        resp.raise_for_status()
        program_data = resp.json()
    except Exception as exc:
        logger.warning("cloud sync: failed to fetch from cloud: %s", exc)
        return jsonify({'ok': False, 'error': str(exc)}), 502

    try:
        atomic_write_json(DATA_FILE, program_data)
        logger.info("cloud applied program update")
        cloud_agent._pending_ui_notify = True
    except Exception as exc:
        logger.exception("cloud-apply program write failed")
        return jsonify({'ok': False, 'error': str(exc)}), 500

    return jsonify({'ok': True})


# --- Windows build: signed self-update system (our code) ---
def _update_config():
    """Read config.json fresh (update_url / enable_self_update are runtime
    settings that may change between requests)."""
    try:
        with open('config.json') as _f:
            return json.load(_f)
    except Exception:
        return {}


def _update_install_dir():
    """Working directory is the install folder (LeiturgiaServer.exe /
    Leiturgia.exe / config.json / license.dat / updater.exe all live
    side-by-side)."""
    return os.getcwd()


def _write_update_status(payload):
    try:
        d = os.path.join('data', 'update')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'status.json'), 'w') as _f:
            json.dump(payload, _f)
    except Exception:
        logger.warning('update status write failed', exc_info=True)


@app.route('/api/update/check', methods=['GET'])
@operator_required
def api_update_check():
    cfg = _update_config()
    update_url = cfg.get('update_url', '')
    if not update_url:
        return jsonify({'status': 'error', 'message': 'no update_url configured'}), 400
    try:
        info = updater.check_for_update(update_url, get_version())
        return jsonify({
            'current': get_version(),
            'latest': info.get('latest'),
            'available': info.get('available', False),
        })
    except Exception:
        logger.warning('update check failed', exc_info=True)
        return jsonify({'status': 'error', 'message': 'update check failed'}), 500


@app.route('/api/update/start', methods=['POST'])
@operator_required
def api_update_start():
    cfg = _update_config()
    update_url = cfg.get('update_url', '')
    if not update_url:
        return jsonify({'status': 'error', 'message': 'no update_url configured'}), 400

    current = get_version()
    try:
        info = updater.check_for_update(update_url, current)
    except Exception:
        logger.warning('update check before start failed', exc_info=True)
        return jsonify({'status': 'error', 'message': 'update check failed'}), 500

    if not info.get('available'):
        return jsonify({
            'status': 'error',
            'message': 'already up to date',
            'current': current,
            'latest': info.get('latest'),
        }), 409

    lock_path = os.path.join('data', 'update', 'lock')
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return jsonify({'status': 'error', 'message': 'update already in progress'}), 409

    try:
        stage_dir = os.path.join(tempfile.gettempdir(), 'leiturgia_update_stage')
        shutil.rmtree(stage_dir, ignore_errors=True)
        updater.download_bundle(info['manifest'], stage_dir, update_url)
        manifest_path = os.path.join(stage_dir, 'manifest.json')
        with open(manifest_path, 'w') as _f:
            json.dump(info['manifest'], _f)

        applier = os.path.join(_update_install_dir(), 'updater.exe')
        subprocess.Popen(
            [applier, 'apply', _update_install_dir(), stage_dir, manifest_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0)
            | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
        )
        _write_update_status({
            'status': 'applying',
            'current': current,
            'target_version': info['latest'],
            'ts': time.time(),
            'note': 'Application will restart when finished.',
        })
        return jsonify({'status': 'started', 'target_version': info['latest']}), 202
    except FileExistsError:
        try:
            os.unlink(lock_path)
        except OSError:
            pass
        return jsonify({'status': 'error', 'message': 'update already in progress'}), 409
    except Exception:
        try:
            os.unlink(lock_path)
        except OSError:
            pass
        logger.exception('update download failed')
        return jsonify({'status': 'error', 'message': 'update download failed'}), 500


@app.route('/api/update/status', methods=['GET'])
@operator_required
def api_update_status():
    status_path = os.path.join('data', 'update', 'status.json')
    try:
        with open(status_path) as f:
            return jsonify(json.load(f))
    except Exception:
        logger.warning('update status read failed', exc_info=True)
        return jsonify({'status': 'idle'})


def _sanitize_filename(name: str) -> str:
    stem, ext = os.path.splitext(name)
    stem = stem.replace('-', '_')
    stem = re.sub(r'_+', '_', stem).strip('_')
    return stem + ext


def _effective_remaining_bytes(usage: dict, media_type: str) -> int:
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
    'video': "Video storage is full. Delete unused videos or export them to a USB drive to free up space.",
    'image': "Image storage is full. Delete unused images to free up space.",
}


def _media_budget_error(media_type: str):
    return jsonify({
        "status":  "error",
        "code":    "media_budget_exceeded",
        "message": _MEDIA_BUDGET_MESSAGES[media_type],
    }), 413


@app.route("/api/media/upload", methods=["POST"])
@operator_required
def upload_media():
    from werkzeug.utils import secure_filename
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file provided"}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({"status": "error", "message": "Empty filename"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext in _IMAGE_EXTS:
        media_type = "image"
        subdir     = "images"
    elif ext in _VIDEO_EXTS:
        media_type = "video"
        subdir     = "videos"
    else:
        return jsonify({"status": "error", "message": f"Unsupported file type: {ext}"}), 400

    # Drive-disconnected degradation (TDD §5.6): refuse video ingest with an
    # actionable error rather than writing into a stale/missing directory.
    if media_type == "video" and media_manager.videos_unavailable():
        return jsonify({
            "status":  "error",
            "code":    "video_storage_unavailable",
            "message": "Video storage is unavailable — check the drive connection.",
        }), 503

    # Pre-check: client-declared content length vs effective remaining budget for
    # this media type. request.content_length can be None on some clients — in
    # that case we can't pre-check and rely on the post-save backstop below.
    usage_before = media_manager.usage()
    remaining_before = _effective_remaining_bytes(usage_before, media_type)
    if request.content_length is not None and request.content_length > max(remaining_before, 0):
        return _media_budget_error(media_type)

    filename  = _sanitize_filename(secure_filename(f.filename))
    save_dir  = media_manager.videos_dir() if subdir == "videos" else os.path.join(app.root_path, "media", "images")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)
    f.save(save_path)

    # Post-save backstop: the declared content-length may have been missing or
    # wrong — recheck actual usage now that the file is on disk.
    usage_after = media_manager.usage()
    over_budget = usage_after['full'] if media_type == 'video' else usage_after['images']['full']
    if over_budget:
        try:
            os.remove(save_path)
        except OSError:
            logger_media.warning("failed to remove over-budget upload: %s", save_path, exc_info=True)
        return _media_budget_error(media_type)

    url = f"/media/{subdir}/{_url_quote(filename, safe='')}"
    return jsonify({"status": "ok", "url": url, "media_type": media_type})

@app.route("/media/<subdir>/<path:filename>")
def serve_media(subdir, filename):
    if subdir not in ("images", "videos"):
        return "Not found", 404
    # videos_dir() may be missing entirely (drive unplugged) — send_from_directory
    # already 404s cleanly on a missing dir/file, no special-casing needed here;
    # the existing projection media-error fallback handles a 404 media URL.
    media_dir = media_manager.videos_dir() if subdir == "videos" else os.path.join(app.root_path, "media", "images")
    return send_from_directory(media_dir, filename)


# ── YouTube / platform download ───────────────────────────────────────────────
import shutil as _shutil
_FFMPEG = _shutil.which('ffmpeg')

# When ffmpeg is available: download best video+audio streams and merge.
# When ffmpeg is absent: fall back to pre-merged progressive streams (≤720p on YouTube).
_QUALITY_MERGE = {
    'best':  'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    '1080p': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]',
    '720p':  'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
    '480p':  'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]',
    '360p':  'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]',
    'audio': 'bestaudio[ext=m4a]/bestaudio',
}
_QUALITY_NOFFMPEG = {
    'best':  'best[ext=mp4]/best',
    '1080p': 'best[height<=1080][ext=mp4]/best[height<=1080]',
    '720p':  'best[height<=720][ext=mp4]/best[height<=720]',
    '480p':  'best[height<=480][ext=mp4]/best[height<=480]',
    '360p':  'best[height<=360][ext=mp4]/best[height<=360]',
    'audio': 'bestaudio[ext=m4a]/bestaudio',
}

def _get_format(quality):
    table = _QUALITY_MERGE if _FFMPEG else _QUALITY_NOFFMPEG
    return table.get(quality, table['best'])

_ANSI_RE      = re.compile(r'\x1b\[[0-9;]*m')
_YT_CACHE_PATH = os.path.join('data', 'yt_cache.json')
_YT_ID_RE      = re.compile(r'(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})')

def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s).strip()

def _yt_progress_hook(d, item_id, sid):
    status = d.get('status')
    if status == 'downloading':
        # yt-dlp embeds ANSI colour codes — strip before parsing
        downloaded = d.get('downloaded_bytes') or 0
        total      = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        if total:
            percent = min(100.0, downloaded / total * 100)
        else:
            raw = _strip_ansi(d.get('_percent_str', '0%'))
            try:
                percent = float(raw.replace('%', ''))
            except ValueError:
                percent = 0.0
        speed_raw = _strip_ansi(d.get('_speed_str', ''))
        socketio.emit('yt:progress', {
            'item_id': item_id,
            'status':  'downloading',
            'percent': percent,
            'speed':   speed_raw,
            'eta':     d.get('eta', 0),
        }, room=sid)
        eventlet.sleep(0)
    elif status == 'finished':
        socketio.emit('yt:progress', {
            'item_id': item_id,
            'status':  'processing',
            'percent': 100.0,
            'speed':   '',
            'eta':     0,
        }, room=sid)
        eventlet.sleep(0)

def _yt_cache_write(source_url, filename, local_url):
    m = _YT_ID_RE.search(source_url)
    key = m.group(1) if m else source_url
    try:
        cache = {}
        if os.path.exists(_YT_CACHE_PATH):
            with open(_YT_CACHE_PATH) as f:
                cache = json.load(f)
        cache[key] = {'filename': filename, 'local_url': local_url, 'source_url': source_url}
        atomic_write_json(_YT_CACHE_PATH, cache)
    except Exception:
        logger.warning("yt_cache write failed", exc_info=True)

def _yt_budget_error(item_id, sid):
    socketio.emit('yt:error', {
        'item_id': item_id,
        'message': _MEDIA_BUDGET_MESSAGES['video'],
    }, room=sid)


def _yt_download_task(url, quality, item_id, sid):
    import yt_dlp

    # Drive-disconnected degradation (TDD §5.6): refuse ingest with an
    # actionable error rather than downloading into a stale/missing directory.
    if media_manager.videos_unavailable():
        socketio.emit('yt:error', {
            'item_id': item_id,
            'message': 'Video storage is unavailable — check the drive connection.',
        }, room=sid)
        return

    videos_dir = media_manager.videos_dir()
    os.makedirs(videos_dir, exist_ok=True)

    usage_before = media_manager.usage()
    remaining_before = _effective_remaining_bytes(usage_before, 'video')
    if remaining_before <= 0:
        _yt_budget_error(item_id, sid)
        return

    ydl_opts = {
        'format':         _get_format(quality),
        'outtmpl':        os.path.join(videos_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: _yt_progress_hook(d, item_id, sid)],
        'quiet':          True,
        'no_warnings':    True,
        'geo_bypass':        True,
        'restrictfilenames': True,
    }
    _cookies_path = os.path.join(app.root_path, 'data', 'yt_cookies.txt')
    if os.path.isfile(_cookies_path):
        ydl_opts['cookiefile'] = _cookies_path
    if _FFMPEG:
        ydl_opts['merge_output_format'] = 'mp4'

    # Pre-flight: check yt-dlp's filesize estimate against effective remaining
    # budget before downloading anything. A missing/failed estimate falls through
    # to the normal download flow — the in-flight max_filesize backstop below
    # covers that case.
    try:
        preflight_opts = {k: v for k, v in ydl_opts.items() if k != 'progress_hooks'}
        preflight_opts['progress_hooks'] = []
        with yt_dlp.YoutubeDL(preflight_opts) as ydl_probe:
            info_probe = ydl_probe.extract_info(url, download=False)
        estimate = info_probe.get('filesize') or info_probe.get('filesize_approx')
        if estimate and estimate > remaining_before:
            _yt_budget_error(item_id, sid)
            return
    except Exception:
        logger_media.warning("yt-dlp pre-flight size estimate failed for %s", url, exc_info=True)

    # In-flight backstop: cap the actual download at the effective remaining
    # budget in case the estimate was missing or wrong.
    if remaining_before > 0:
        ydl_opts['max_filesize'] = remaining_before

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info     = ydl.extract_info(url, download=True)
            raw_name = os.path.basename(ydl.prepare_filename(info))
            # If ffmpeg merged to mp4, the extension will be .mp4 regardless of raw_name
            if _FFMPEG:
                final = os.path.splitext(raw_name)[0] + '.mp4'
            else:
                # Find the actual downloaded file (extension may vary)
                base  = os.path.splitext(raw_name)[0]
                found = next(
                    (f for f in os.listdir(videos_dir) if f.startswith(base)),
                    raw_name
                )
                final = found
            sanitized = _sanitize_filename(final)
            if sanitized != final:
                os.rename(
                    os.path.join(videos_dir, final),
                    os.path.join(videos_dir, sanitized),
                )
                final = sanitized
            final_path = os.path.join(videos_dir, final)
            final_url = f'/media/videos/{_url_quote(final, safe="")}'

        # Post-download backstop: recheck usage now that the file is on disk.
        if os.path.exists(final_path):
            usage_after = media_manager.usage()
            if usage_after['full']:
                try:
                    os.remove(final_path)
                except OSError:
                    logger_media.warning("failed to remove over-budget download: %s", final_path, exc_info=True)
                _yt_budget_error(item_id, sid)
                return

        _yt_cache_write(url, final, final_url)
        logger_media.info("media download complete: item_id=%s file=%s", item_id, final)
        socketio.emit('yt:done', {
            'item_id':  item_id,
            'url':      final_url,
            'filename': final,
        }, room=sid)
    except Exception as exc:
        logger_media.exception("yt download failed: %s", url)
        socketio.emit('yt:error', {
            'item_id': item_id,
            'message': str(exc),
        }, room=sid)

@socketio.on('yt:download:start')
def on_yt_download_start(data):
    if not session.get('operator'):
        disconnect()
        return
    url     = (data.get('url') or '').strip()
    quality = data.get('quality', 'best')
    item_id = data.get('item_id', '')
    sid     = request.sid

    if not url.startswith(('http://', 'https://')):
        emit('yt:error', {'item_id': item_id, 'message': 'Invalid URL — must start with http:// or https://'})
        return

    logger_media.info("media download start: item_id=%s quality=%s url=%s", item_id, quality, url)
    socketio.start_background_task(_yt_download_task, url, quality, item_id, sid)


# ── USB media export (media-storage-budget TDD §5.3a/§5.4) ─────────────────

_EXPORT_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB


def _export_copy_file(src_path, dst_path, size, filename, sid):
    """Chunked manual copy (not one blocking shutil.copy2 call) so the
    eventlet loop stays live during multi-GB copies — mirrors the yt-dlp
    progress-hook pattern. Emits media:export:progress per chunk. Raises
    OSError (including ENOSPC) on a write failure; the caller cleans up the
    partial target file."""
    copied = 0
    with open(src_path, 'rb') as fsrc, open(dst_path, 'wb') as fdst:
        while True:
            chunk = fsrc.read(_EXPORT_CHUNK_SIZE)
            if not chunk:
                break
            fdst.write(chunk)
            copied += len(chunk)
            socketio.emit('media:export:progress', {
                'filename': filename,
                'bytes':    copied,
                'total':    size,
            }, room=sid)
            eventlet.sleep(0)
    try:
        _shutil.copystat(src_path, dst_path)
    except OSError:
        pass


def _media_export_task(filenames, target, move, sid):
    videos_dir = media_manager.videos_dir()

    # Export security (TDD §5.4): target must resolve under an allowlisted
    # mount root AND appear in a fresh /proc/mounts rescan — never trust a
    # stale client-supplied path.
    resolved_target = media_manager.resolve_usb_target(target)
    if not resolved_target:
        socketio.emit('media:export:error', {
            'code':    'invalid_target',
            'message': 'USB target is no longer available — insert the drive and refresh.',
        }, room=sid)
        return

    # Same basename-equality check delete_media_file() uses — no path traversal.
    safe_names = []
    for name in filenames:
        if not isinstance(name, str):
            continue
        safe = os.path.basename(name)
        if not safe or safe != name:
            continue
        if os.path.isfile(os.path.join(videos_dir, safe)):
            safe_names.append(safe)

    if not safe_names:
        socketio.emit('media:export:error', {
            'code':    'no_files',
            'message': 'No valid files to export.',
        }, room=sid)
        return

    # Pre-start target-full check: total selected size vs target free space,
    # before a single byte is copied.
    total_size = sum(os.path.getsize(os.path.join(videos_dir, n)) for n in safe_names)
    try:
        target_free = _shutil.disk_usage(resolved_target).free
    except OSError:
        target_free = 0
    if total_size > target_free:
        socketio.emit('media:export:error', {
            'code':       'usb_target_full',
            'message':    'Not enough free space on the USB drive.',
            'need_label': media_manager._fmt_size(total_size),
            'free_label': media_manager._fmt_size(target_free),
        }, room=sid)
        return

    in_use = media_manager.referenced_media()
    moved, copied, kept_local, failed = [], [], [], []

    for name in safe_names:
        src_path = os.path.join(videos_dir, name)
        dst_path = os.path.join(resolved_target, name)
        try:
            size = os.path.getsize(src_path)
        except OSError:
            failed.append({'name': name, 'reason': 'not_found'})
            continue

        try:
            _export_copy_file(src_path, dst_path, size, name, sid)
        except OSError:
            # Mid-copy failure (e.g. ENOSPC) — delete the partial target file;
            # files already completed (and their move-deletions) stand.
            try:
                if os.path.exists(dst_path):
                    os.remove(dst_path)
            except OSError:
                logger_media.warning("failed to clean up partial export file: %s", dst_path, exc_info=True)
            logger_media.warning("media export write failed for %s", name, exc_info=True)
            try:
                free_now = _shutil.disk_usage(resolved_target).free
            except OSError:
                free_now = 0
            socketio.emit('media:export:error', {
                'code':       'usb_target_full',
                'message':    f'"{name}" did not fit on the USB drive — export stopped.',
                'name':       name,
                'need_label': media_manager._fmt_size(size),
                'free_label': media_manager._fmt_size(free_now),
            }, room=sid)
            return

        # Size-verify before any deletion — a failed verify never deletes the original.
        try:
            dst_size = os.path.getsize(dst_path)
        except OSError:
            dst_size = -1
        if dst_size != size:
            failed.append({'name': name, 'reason': 'verify_failed'})
            try:
                os.remove(dst_path)
            except OSError:
                pass
            continue

        used_by = in_use.get(name)
        if move and used_by:
            # In-use guard (§5.3a): Move degrades to Copy for a referenced file
            # — copied to the target, local original kept.
            kept_local.append({'name': name, 'note': 'in_use_kept_local', 'used_by': used_by})
        elif move:
            try:
                os.remove(src_path)
                moved.append(name)
            except OSError:
                logger_media.warning("failed to remove local original after export: %s", src_path, exc_info=True)
                failed.append({'name': name, 'reason': 'delete_failed'})
        else:
            copied.append(name)

    logger_media.info(
        "media export done: target=%s moved=%d copied=%d kept_local=%d failed=%d",
        resolved_target, len(moved), len(copied), len(kept_local), len(failed),
    )
    socketio.emit('media:export:done', {
        'moved':      moved,
        'copied':     copied,
        'kept_local': kept_local,
        'failed':     failed,
        'usage':      media_manager.usage(),
    }, room=sid)


@socketio.on('media:export:start')
def on_media_export_start(data):
    if not session.get('operator'):
        disconnect()
        return
    filenames = data.get('filenames') or []
    target    = (data.get('target') or '').strip()
    move      = bool(data.get('move'))
    sid       = request.sid

    if not isinstance(filenames, list) or not filenames:
        emit('media:export:error', {'code': 'no_files', 'message': 'No files selected.'})
        return
    if not target:
        emit('media:export:error', {'code': 'invalid_target', 'message': 'No USB target selected.'})
        return

    logger_media.info("media export start: sid=%s target=%s move=%s files=%d", sid, target, move, len(filenames))
    socketio.start_background_task(_media_export_task, filenames, target, move, sid)


# ── Video storage location migration (media-storage-budget TDD §5.6) ───────
# Switching the location (POST /api/settings/video-dir) is a metadata-only,
# instant change; migrating existing videos into the new location is a
# separate, optional, resumable background copy that reuses the Phase 3
# export machinery (_export_copy_file, media:export:* events) rather than a
# second copy engine. The destination is always the server's own current
# videos_dir() (post-switch) — never a client-supplied path — so this can
# only ever copy into the already-validated, already-persisted location.

def _video_dir_migrate_task(from_dir, sid):
    to_dir = media_manager.videos_dir()

    # Never trust a stale/arbitrary client-supplied source path: it must be
    # either the built-in default or a path that still resolves under a
    # currently-mounted allowlisted root (fresh /proc/mounts rescan).
    valid_from = (from_dir == media_manager.VIDEOS_DIR) or bool(media_manager.resolve_export_target(from_dir))
    if not valid_from or not os.path.isdir(from_dir):
        socketio.emit('media:export:error', {
            'code':    'invalid_target',
            'message': 'Previous video location is not available — nothing to migrate.',
        }, room=sid)
        return

    if os.path.realpath(from_dir) == os.path.realpath(to_dir):
        socketio.emit('media:export:done', {
            'moved': [], 'copied': [], 'kept_local': [], 'failed': [],
            'usage': media_manager.usage(),
        }, room=sid)
        return

    os.makedirs(to_dir, exist_ok=True)
    safe_names = sorted(
        n for n in os.listdir(from_dir)
        if os.path.splitext(n)[1].lower() in media_manager.VIDEO_EXTS
        and os.path.isfile(os.path.join(from_dir, n))
    )

    if not safe_names:
        socketio.emit('media:export:done', {
            'moved': [], 'copied': [], 'kept_local': [], 'failed': [],
            'usage': media_manager.usage(),
        }, room=sid)
        return

    in_use = media_manager.referenced_media()
    moved, kept_local, failed = [], [], []

    for name in safe_names:
        src_path = os.path.join(from_dir, name)
        dst_path = os.path.join(to_dir, name)
        try:
            size = os.path.getsize(src_path)
        except OSError:
            failed.append({'name': name, 'reason': 'not_found'})
            continue

        try:
            _export_copy_file(src_path, dst_path, size, name, sid)
        except OSError:
            try:
                if os.path.exists(dst_path):
                    os.remove(dst_path)
            except OSError:
                logger_media.warning("failed to clean up partial migration file: %s", dst_path, exc_info=True)
            logger_media.warning("video-dir migration write failed for %s", name, exc_info=True)
            failed.append({'name': name, 'reason': 'write_failed'})
            continue

        # Size-verify before any deletion — a failed verify never deletes the
        # source, leaving it to retry on a later migration pass.
        try:
            dst_size = os.path.getsize(dst_path)
        except OSError:
            dst_size = -1
        if dst_size != size:
            failed.append({'name': name, 'reason': 'verify_failed'})
            try:
                os.remove(dst_path)
            except OSError:
                pass
            continue

        used_by = in_use.get(name)
        if used_by:
            # In-use guard (§5.3a): keep the local original at the old
            # location instead of deleting it — same rule as USB export.
            kept_local.append({'name': name, 'note': 'in_use_kept_local', 'used_by': used_by})
        else:
            try:
                os.remove(src_path)
                moved.append(name)
            except OSError:
                logger_media.warning("failed to remove source after migration: %s", src_path, exc_info=True)
                failed.append({'name': name, 'reason': 'delete_failed'})

    logger_media.info(
        "video-dir migration done: from=%s to=%s moved=%d kept_local=%d failed=%d",
        from_dir, to_dir, len(moved), len(kept_local), len(failed),
    )
    socketio.emit('media:export:done', {
        'moved':      moved,
        'copied':     [],
        'kept_local': kept_local,
        'failed':     failed,
        'usage':      media_manager.usage(),
    }, room=sid)


@socketio.on('media:migrate:start')
def on_media_migrate_start(data):
    if not session.get('operator'):
        disconnect()
        return
    from_dir = (data.get('from') or '').strip()
    sid      = request.sid

    if not from_dir:
        emit('media:export:error', {'code': 'invalid_target', 'message': 'No previous location to migrate from.'})
        return

    logger_media.info("video-dir migration start: sid=%s from=%s", sid, from_dir)
    socketio.start_background_task(_video_dir_migrate_task, from_dir, sid)


def _timer_tick_loop():
    while True:
        socketio.sleep(1)
        fs = timer.get_full_state('timer')
        if not fs['running'] and not fs['overtime']:
            continue
        payload = {
            'remaining': fs['remaining'],
            'total':     fs['total'],
            'state':     fs['state'],
            'label':     fs['label'],
            'overtime':  fs['overtime'],
        }
        for ch in roles.get_channels('timer'):
            socketio.emit('timer:tick', payload, room=ch)
        for ch in roles.get_channels('order_of_service'):
            socketio.emit('timer:tick', payload, room=ch)

socketio.start_background_task(_timer_tick_loop)


@app.errorhandler(Exception)
def _handle_unexpected_error(exc):
    if isinstance(exc, HTTPException):
        return exc
    logger.exception("unhandled exception: %s %s", request.method, request.path)
    return jsonify({'error': 'internal server error'}), 500


@socketio.on_error_default
def _handle_socketio_error(exc):
    logger.exception("unhandled socket.io error")


def _cloud_update_pump():
    """Poll cloud_agent flag from eventlet green thread — safe to call socketio.emit here."""
    while True:
        if cloud_agent._pending_ui_notify:
            cloud_agent._pending_ui_notify = False
            socketio.emit('program:cloud:update', {}, namespace='/')
        socketio.sleep(0.2)


socketio.start_background_task(_cloud_update_pump)
cloud_agent.start()


if __name__ == "__main__":
    os.makedirs("data",        exist_ok=True)
    os.makedirs("data/update", exist_ok=True)
    os.makedirs(LYRICS_DIR,    exist_ok=True)
    os.makedirs("output",      exist_ok=True)
    os.makedirs("media/images", exist_ok=True)
    os.makedirs("media/videos", exist_ok=True)
    for _p in glob.glob(os.path.join(os.path.dirname(DATA_FILE), ".tmp-*.json")):
        try:
            os.unlink(_p)
        except OSError:
            pass
    socketio.run(app, host="0.0.0.0", port=5001, debug=False)
