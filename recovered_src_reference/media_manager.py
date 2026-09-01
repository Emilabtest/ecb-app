# Source Generated with Decompyle++
# File: media_manager.pyc (Python 3.12)

'''
media_manager.py ΓÇö Enumerate media files in media/images/ and media/videos/,
and compute storage-budget usage against them.

Public: list_media(), usage(), referenced_media(), usb_targets(),
resolve_usb_target(), videos_dir(), videos_unavailable(), resolve_export_target().
'''
import json
import logging
import os
import re
import shutil
from urllib.parse import quote as _quote, unquote as _unquote
logger = logging.getLogger('leiturgia.media')

try:
    from mutagen.mp4 import MP4 as _MP4
    _MUTAGEN_OK = True
except ImportError:
    _MUTAGEN_OK = False

MEDIA_ROOT = 'media'
IMAGES_DIR = os.path.join(MEDIA_ROOT, 'images')
VIDEOS_DIR = os.path.join(MEDIA_ROOT, 'videos')
IMAGE_EXTS = {
    '.bmp',
    '.gif',
    '.jpg',
    '.png',
    '.jpeg',
    '.webp'}
VIDEO_EXTS = {
    '.avi',
    '.mov',
    '.ogg',
    '.webm',
    '.mp4'}
CONFIG_FILE = 'config.json'
DATA_FILE = os.path.join('data', 'program.json')

def videos_dir():
    '''Resolve the physical video storage directory (TDD ┬º5.6): `media_video_dir`
    from config if set, else the built-in `media/videos` path. Every video-path
    consumer (list/scan, usage, upload, yt-dlp, serve_media, export) must call
    this rather than hard-coding the videos directory.'''
    cfg = _load_config()
    if not cfg.get('media_video_dir'):
        cfg.get('media_video_dir')
    configured = cfg.get('media_video_dir').strip()
    if configured:
        return configured
    return VIDEOS_DIR


def videos_unavailable():
    """True only when an *externally configured* video dir (not the built-in
    default) is missing/unmounted right now ΓÇö e.g. a USB drive got unplugged.
    The built-in dir simply not existing yet (fresh install, nothing uploaded)
    is normal and is NOT reported as unavailable. See TDD ┬º5.6 'Drive-disconnected
    degradation'."""
    vdir = videos_dir()
    if vdir != VIDEOS_DIR:
        vdir != VIDEOS_DIR
    return vdir != VIDEOS_DIR


def _location_label(vdir):
    """Human label for where videos currently live ΓÇö 'Internal' for the
    built-in dir, else the matching USB target's label, else the basename of
    the configured dir. Feeds `usage()['location_label']` (TDD ┬º5.2)."""
    if vdir == VIDEOS_DIR:
        return 'Internal'
    
    try:
        real = os.path.realpath(vdir)
    except (OSError, ValueError):
        real = vdir

    for entry in usb_targets():
        
        try:
            entry_real = os.path.realpath(entry['path'])
        except (OSError, ValueError):
            pass

        if not (real == entry_real) and not real.startswith(entry_real.rstrip('/') + '/'):
            continue
        return entry['label']
    if not os.path.basename(vdir.rstrip('/')):
        os.path.basename(vdir.rstrip('/'))
    return os.path.basename(vdir.rstrip('/'))


def list_media():
    '''Return { "images": [...], "videos": [...], "videos_unavailable": bool }
    with filename, URL, and metadata. When the configured video dir is
    disconnected, "videos" comes back empty and "videos_unavailable" is True
    instead of raising (TDD ┬º5.6).'''
    vdir = videos_dir()
    unavailable = videos_unavailable()
    if unavailable:
        return {
            'images': _scan(IMAGES_DIR, IMAGE_EXTS, 'images'),
            'videos': [],
            'videos_unavailable': unavailable }
    return {
        'images': _scan(IMAGES_DIR, IMAGE_EXTS, 'images'),
        'videos': _scan(vdir, VIDEO_EXTS, 'videos'),
        'videos_unavailable': unavailable }


def _fmt_size(n):
    for unit in ('KB', 'MB', 'GB'):
        n /= 1024
        if not n < 1024:
            continue
        return f'''{n:.1f} {unit}'''
    return f'''{n:.1f} GB'''


def _fmt_duration(s):
    (m, sec) = divmod(int(s), 60)
    return f'''{m}:{sec:02d}'''


def _file_meta(path):
    size = os.path.getsize(path)
    duration = None
    duration_label = None
    if _MUTAGEN_OK and path.lower().endswith(('.mp4', '.m4v')):
        
        try:
            duration = _MP4(path).info.length
            duration_label = _fmt_duration(duration)
        except Exception:
            pass

    return {
        'size': size,
        'size_label': _fmt_size(size),
        'duration': duration,
        'duration_label': duration_label }


def _scan(directory, allowed_exts, subdir):
    if not os.path.isdir(directory):
        return []
    files = []
    for name in sorted(os.listdir(directory)):
        ext = os.path.splitext(name)[1].lower()
        if not ext in allowed_exts:
            continue
        full_path = os.path.join(directory, name)
        entry = {
            'name': name,
            'url': f'''/media/{subdir}/{_quote(name, safe = '')}''' }
        entry.update(_file_meta(full_path))
        files.append(entry)
    return files


def _load_config():
    '''Ad-hoc config.json read, same convention app.py uses elsewhere (no caching,
    changes apply without restart). Missing file/keys degrade to defaults.'''
    
    try:
        f = open(CONFIG_FILE)
        json.load(f)(None, None)
        return None
    except (OSError, ValueError):
        return { }

# WARNING: Decompyle incomplete


def _dir_used_bytes(directory):
    if not os.path.isdir(directory):
        return 0
    return sum(( e.stat().st_size for e in os.scandir(directory) if e.is_file() ))


def usage():
    '''Compute video/image storage usage against the configured budgets and the
    hard filesystem reserve. See development/tdd/modules/media-storage-budget.md
    ┬º5.2 for the full spec.'''
    cfg = _load_config()
    video_budget_bytes = int(float(cfg.get('media_video_budget_gb', 2)) * 1073741824)
    image_budget_bytes = int(float(cfg.get('media_image_budget_gb', 1)) * 1073741824)
    reserve_bytes = int(float(cfg.get('media_disk_reserve_gb', 1)) * 1073741824)
    warn_percent = float(cfg.get('media_warn_percent', 80))
    vdir = videos_dir()
    unavailable = videos_unavailable()
    used_bytes = 0 if unavailable else _dir_used_bytes(vdir)
    if os.path.isdir(vdir):
        pass
    elif os.path.isdir(MEDIA_ROOT):
        pass
    
    du_path = '.'
    fs_free_bytes = shutil.disk_usage(du_path).free
    fs_room = fs_free_bytes - reserve_bytes
    if video_budget_bytes == 0:
        remaining_bytes = fs_room
        percent = _safe_percent(used_bytes, used_bytes + fs_room)
        fs_reserve_binding = False
    else:
        remaining_bytes = min(video_budget_bytes - used_bytes, fs_room)
        percent = _safe_percent(used_bytes, video_budget_bytes)
        fs_reserve_binding = fs_room < video_budget_bytes - used_bytes
    full = remaining_bytes <= 0
    if not full:
        full
        if not percent >= warn_percent:
            percent >= warn_percent
    warn = full
    images_used_bytes = _dir_used_bytes(IMAGES_DIR)
    if image_budget_bytes == 0:
        images_remaining = fs_room
    else:
        images_remaining = min(image_budget_bytes - images_used_bytes, fs_room)
    images = {
        'used_bytes': images_used_bytes,
        'budget_bytes': image_budget_bytes,
        'full': images_remaining <= 0,
        'used_label': _fmt_size(images_used_bytes),
        'budget_label': 'Unlimited' if image_budget_bytes == 0 else _fmt_size(image_budget_bytes) }
    return {
        'used_bytes': used_bytes,
        'budget_bytes': video_budget_bytes,
        'remaining_bytes': remaining_bytes,
        'percent': percent,
        'fs_free_bytes': fs_free_bytes,
        'reserve_bytes': reserve_bytes,
        'warn': warn,
        'full': full,
        'used_label': _fmt_size(used_bytes),
        'budget_label': 'Unlimited' if video_budget_bytes == 0 else _fmt_size(video_budget_bytes),
        'images': images,
        'location_label': _location_label(vdir),
        'videos_unavailable': unavailable }


def _safe_percent(part, whole):
    if whole <= 0:
        return 0
    return round((part / whole) * 100, 1)


def referenced_media():
    '''Scan data/program.json for items whose url points at a media/{videos,images}
    file, mapping basename -> [{program, item}, ...]. Read-only informational scan ΓÇö
    a plain json.load is fine here (no migration/retry logic needed).
    See development/tdd/modules/media-storage-budget.md ┬º5.3a.'''
    if not os.path.exists(DATA_FILE):
        return { }
    
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        logger.warning('referenced_media: could not read %s', DATA_FILE, exc_info = True)
        return { }

    refs = { }
    for sp in data.get('service_programs', []):
        program_label = sp.get('name', sp.get('id', ''))
        for item in sp.get('items', []):
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
            if not is_video and not is_image:
                continue
            url = item.get('url', '')
            if not url:
                continue
            basename = _unquote(os.path.basename(url))
            item_label = item.get('title', item.get('part', ''))
            refs.setdefault(basename, []).append({
                'program': program_label,
                'item': item_label })
    return refs

USB_MOUNT_ROOTS = ('/media/', '/mnt/', '/run/media/')
_MOUNT_OCTAL_RE = re.compile('\\\\([0-7]{3})')

def _unescape_mount_field(s):
    '''/proc/mounts octal-escapes spaces/tabs/newlines/backslashes in paths
    (e.g. a space becomes \\040) ΓÇö undo that so mount points compare/display
    correctly.'''
    return _MOUNT_OCTAL_RE.sub((lambda m: chr(int(m.group(1), 8))), s)


def usb_targets():
    '''List writable removable-looking mounts for USB export, per TDD ┬º5.4:
    parse /proc/mounts, keep mount points under the allowlisted roots, require
    os.access(W_OK). Returns [{path, label, free_bytes, free_label, fs_type,
    fat32}, ...]. Linux-only (/proc/mounts); returns [] elsewhere.'''
    targets = []
    
    try:
        with open('/proc/mounts') as f:
            lines = f.readlines()
    except OSError:
        return targets

    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = _unescape_mount_field(parts[1])
        fs_type = parts[2]
        if not any(( mount_point.startswith(root) for root in USB_MOUNT_ROOTS )):
            continue
        if not os.path.isdir(mount_point) or not os.access(mount_point, os.W_OK):
            continue
        
        try:
            free_bytes = shutil.disk_usage(mount_point).free
        except OSError:
            pass

        if not os.path.basename(mount_point.rstrip('/')):
            os.path.basename(mount_point.rstrip('/'))
        label = os.path.basename(mount_point.rstrip('/'))
        targets.append({
            'path': mount_point,
            'label': label,
            'free_bytes': free_bytes,
            'free_label': _fmt_size(free_bytes),
            'fs_type': fs_type,
            'fat32': fs_type.lower() in ('vfat', 'fat32', 'fat', 'msdos') })
    return targets


def resolve_usb_target(target):
    '''Validate a client-supplied export target against a *fresh* rescan of
    /proc/mounts (never trust a stale client-supplied path) ΓÇö the target must
    resolve (realpath) to a mount point currently listed by usb_targets().
    Returns the canonical mount path, or None if invalid/not currently
    mounted/writable. See TDD ┬º5.4 "Export security".'''
    if not target:
        return None
    
    try:
        real = os.path.realpath(target)
    except (OSError, ValueError):
        return None

    for entry in usb_targets():
        if not os.path.realpath(entry['path']) == real:
            continue
        return entry['path']


def resolve_export_target(target):
    '''Broader sibling of resolve_usb_target(): validates a client-supplied
    path against a *fresh* /proc/mounts rescan, accepting the path if its
    realpath sits AT or BELOW a currently-mounted, writable, allowlisted root
    ΓÇö not just equal to it. Used by the configurable video storage location
    (TDD ┬º5.6), whose target is typically `<mount>/leiturgia-videos`, a
    subdirectory of the mount root rather than the root itself. Returns the
    resolved absolute path, or None if invalid/not currently mounted/writable.
    See TDD ┬º5.6 "Validation (server, on POST)".'''
    if not target or not os.path.isabs(target):
        return None
    
    try:
        real = os.path.realpath(target)
    except (OSError, ValueError):
        return None

    for entry in usb_targets():
        
        try:
            entry_real = os.path.realpath(entry['path'])
        except (OSError, ValueError):
            pass

        if not (real == entry_real) and not real.startswith(entry_real.rstrip('/') + '/'):
            continue
        return real


