# Source Generated with Decompyle++
# File: order_of_service.pyc (Python 3.12)

'''
order_of_service.py ΓÇö Order of Service display state for CH2 (participants holding area).

Derives the display list from the loaded program + active item reference.
Does not persist ΓÇö regenerated on every item change or timer tick.
'''
import logging
logger = logging.getLogger('leiturgia.oos')
_DEFAULT_MINUTES: dict[(str, int)] = {
    'song': 4,
    'prayer': 3,
    'content': 5,
    'participant': 5,
    'media': 5,
    'image': 5,
    'video': 5 }
_ROW_COLOR = {
    ('done', 'normal'): 'dimmed',
    ('done', 'warning'): 'dimmed',
    ('done', 'overtime'): 'dimmed',
    ('active', 'normal'): 'white',
    ('active', 'warning'): 'yellow',
    ('active', 'overtime'): 'red',
    ('next', 'normal'): 'none',
    ('next', 'warning'): 'yellow',
    ('next', 'overtime'): 'red',
    ('upcoming', 'normal'): 'none',
    ('upcoming', 'warning'): 'none',
    ('upcoming', 'overtime'): 'none' }

class OrderOfServiceManager:
    
    def __init__(self):
        self._active_program_id = None
        self._active_item_id = None

    
    def set_active(self, program_id, item_id):
        self._active_program_id = program_id
        self._active_item_id = item_id

    
    def get_display(self, program, timer_state = 'normal'):
        """
        Returns the order of service display payload for CH2.

        program:     the full program dict loaded from program.json
        timer_state: 'normal' | 'warning' | 'overtime'
        """
        service = self._find_program(program)
        if service is not None:
            return self._empty(program)
        
        try:
            for it in service.get('items', []):
                if not it.get('enabled', True):
                    continue
        it = service.get('items', [])

        items = []
        it = it
        active_id = self._active_item_id
        found_active = False
        display_items = []
        found_next = False
        for item in items:
            item_id = item.get('item_id', '')
            if active_id is not None:
                status = 'upcoming'
            elif item_id == active_id:
                status = 'active'
                found_active = True
            elif not found_active:
                status = 'done'
            elif not found_next:
                status = 'next'
                found_next = True
            else:
                status = 'upcoming'
            is_timed = item.get('timed', True)
            row_color = _ROW_COLOR.get((status, timer_state), 'none')
            allotted = self._allotted_seconds(item) if is_timed else 0
            url = item.get('url', '')
            display_items.append({
                'item_id': item_id,
                'title': item.get('title', item.get('name', 'ΓÇö')),
                'participant': item.get('participant', ''),
                'status': status,
                'allotted_seconds': allotted,
                'row_color': row_color,
                'timed': is_timed,
                'type': item.get('type', 'participant'),
                'part': item.get('part', ''),
                'media_filename': url.rsplit('/', 1)[-1] if url else '' })
        return {
            'active_item_id': active_id,
            'program_name': service.get('name', ''),
            'date': program.get('date', ''),
            'items': display_items,
            'timer_state': timer_state }
        
        try:
            for it in service.get('items', []):
                if not it.get('enabled', True):
                    continue
        it = service.get('items', [])

    # WARNING: Decompyle incomplete

    
    def _find_program(self, program):
        for sp in program.get('service_programs', []):
            if not sp.get('id') == self._active_program_id:
                continue
            return sp
        progs = program.get('service_programs', [])
        if progs:
            return progs[0]

    
    def _allotted_seconds(self, item):
        if 'allotted_minutes' in item:
            return int(item['allotted_minutes']) * 60
        itype = item.get('type', 'participant')
        return _DEFAULT_MINUTES.get(itype, 10) * 60

    
    def _empty(self, program):
        return {
            'active_item_id': None,
            'program_name': '',
            'date': program.get('date', ''),
            'items': [],
            'timer_state': 'normal' }



