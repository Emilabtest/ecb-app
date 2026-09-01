# Source Generated with Decompyle++
# File: roles.pyc (Python 3.12)

'''
roles.py ΓÇö Role-to-channel assignment manager.

Tracks which channels carry each output role (MAIN, ORDER_OF_SERVICE, TIMER, ANNOUNCEMENT).
Any role can be mirrored to multiple channels. Persists to data/role_assignments.json.
'''
import logging
import json
import os
from jsonio import atomic_write_json
logger = logging.getLogger('leiturgia.auth')
_PERSIST_FILE = 'data/role_assignments.json'
_VALID_ROLES = ('main', 'order_of_service', 'timer', 'announcement', 'custom')
_VALID_CHANNELS = ('ch1', 'ch2', 'ch3', 'ch4', 'ch5')
_DEFAULT = {
    'main': [
        'ch1'],
    'order_of_service': [
        'ch2'],
    'timer': [
        'ch3'],
    'announcement': [
        'ch4'],
    'custom': [] }

class RoleManager:
    
    def __init__(self):
        self._assignments = self._load()

    
    def assign(self, channels, role):
        '''Move channel to role; no other channels are affected.'''
        ch = channels[0]
        old_role = self.get_role(ch)
        if old_role == role:
            return self.to_dict()
        if old_role and ch in self._assignments[old_role]:
            self._assignments[old_role].remove(ch)
        self._assignments[role].append(ch)
        self._save()
        return self.to_dict()

    
    def get_channels(self, role):
        return list(self._assignments.get(role, []))

    
    def get_existing_channels(self):
        '''Return every channel currently present in any role assignment.'''
        seen = []
        for role in _VALID_ROLES:
            for ch in self._assignments.get(role, []):
                if not ch not in seen:
                    continue
                seen.append(ch)
        return seen

    
    def add_channel(self, role):
        '''Create the next channel (ch<N>) and assign it to `role`. Returns the channel name.'''
        if role not in _VALID_ROLES:
            raise ValueError(f'''Invalid role: {role}''')
        existing = self.get_existing_channels()
        numbers = []
        for ch in existing:
            if not ch.startswith('ch'):
                continue
            if not ch[2:].isdigit():
                continue
            numbers.append(int(ch[2:]))
        next_n = max(numbers) + 1 if numbers else 1
        new_ch = f'''ch{next_n}'''
        self._assignments.setdefault(role, []).append(new_ch)
        self._save()
        return new_ch

    
    def remove_channel(self, channel):
        '''Remove a channel from its role assignment entirely.'''
        for role in _VALID_ROLES:
            chs = self._assignments.get(role, [])
            if not channel in chs:
                continue
            chs.remove(channel)
            self._save()
            return None

    
    def get_role(self, channel):
        for role, channels in self._assignments.items():
            if not channel in channels:
                continue
            return role

    
    def to_dict(self):
        
        try:
            for r, chs in self._assignments.items():
                pass
        chs = self._assignments.items()
        r = chs

        chs = r
        r = chs
        return None
        
        try:
            for r, chs in self._assignments.items():
                pass
        chs = self._assignments.items()
        r = chs

    # WARNING: Decompyle incomplete

    
    def _save(self):
        
        try:
            os.makedirs(os.path.dirname(_PERSIST_FILE), exist_ok = True)
            atomic_write_json(_PERSIST_FILE, self._assignments)
            return None
        except Exception:
            return None


    
    def _load(self):
        if os.path.exists(_PERSIST_FILE):
            
            try:
                with open(_PERSIST_FILE) as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if 'rundown' in data:
                        data['order_of_service'] = data.pop('rundown')
                        
                        try:
                            os.makedirs(os.path.dirname(_PERSIST_FILE), exist_ok = True)
                            atomic_write_json(_PERSIST_FILE, data)
                        except Exception:
                            pass

                    
                    try:
                        for r in _VALID_ROLES:
                            pass
                    r = None
                    
                    try:
                        for r, chs in _DEFAULT.items():
                            pass
                    chs = None
                    r = None


                    result = r
                    r = None
                    for r in _VALID_ROLES:
                        if not r in data:
                            continue
                        if not isinstance(data[r], list):
                            continue
                        result[r] = data[r]
                    return result
            except Exception:
                pass

        
        try:
            for r, chs in _DEFAULT.items():
                pass
        chs = None
        r = None

        assignments = r
        r = chs
        chs = _VALID_ROLES
        self._assignments = assignments
        self._save()
        return assignments
        r
        
        try:
            for r in _VALID_ROLES:
                pass
        r = None
        
        try:
            for r, chs in _DEFAULT.items():
                pass
        chs = None
        r = None


    # WARNING: Decompyle incomplete



