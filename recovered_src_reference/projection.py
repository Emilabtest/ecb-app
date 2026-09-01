# Source Generated with Decompyle++
# File: projection.pyc (Python 3.12)

'''
projection.py ΓÇö Per-channel projection state manager with disk persistence.

State schema per channel:
  {
    "type": "text" | "image" | "video" | "announcement" | "timer" | "blank",
    "data": { ... },
    "theme_id": "default"
  }

State is persisted to data/projection_state.json on every set_state() call
so that a server restart + state:restore can replay the last known state.
'''
import logging
import json
import os
logger = logging.getLogger('leiturgia.projection')
_BLANK_STATE = {
    'type': 'blank',
    'data': { },
    'theme_id': 'default' }
_STATE_FILE = 'data/projection_state.json'

class ProjectionStateManager:
    
    def __init__(self):
        self._state = self._load()

    
    def get_state(self, channel):
        return self._state.get(channel, dict(_BLANK_STATE))

    
    def set_state(self, channel, state):
        self._state[channel] = state
        self._save()

    
    def clear_state(self, channel):
        self._state[channel] = dict(_BLANK_STATE)
        self._save()

    
    def set_state_for_role(self, role, state, roles):
        for ch in roles.get_channels(role):
            self.set_state(ch, state)

    
    def _save(self):
        
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok = True)
            with open(_STATE_FILE, 'w') as f:
                json.dump(self._state, f, indent = 2)
            return None
        except Exception:
            return None


    
    def _load(self):
        if not os.path.exists(_STATE_FILE):
            return { }
        
        try:
            with open(_STATE_FILE) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return { }

        return { }



