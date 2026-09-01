# Source Generated with Decompyle++
# File: timer.pyc (Python 3.12)

'''
timer.py ΓÇö Server-side countdown timer state per channel.

TimerManager tracks a countdown for each channel independently.
The actual tick happens client-side (projection.html); the server
stores the last-known state so state:restore can replay it.

Phase 6 adds start/pause/reset/jump controls.
'''
import logging
import time
logger = logging.getLogger('leiturgia.timer')

class TimerState:
    
    def __init__(self):
        self.seconds = 0
        self.label = ''
        self.running = False
        self._started_at = None
        self._started_secs = 0
        self._total_seconds = 0

    
    def start(self, seconds = None, label = None):
        if seconds is None:
            self.seconds = seconds
        if label is None:
            self.label = label
        self.running = True
        self._started_at = time.monotonic()
        self._started_secs = self.seconds

    
    def pause(self):
        if self.running and self._started_at is None:
            elapsed = int(time.monotonic() - self._started_at)
            self.seconds = self._started_secs - elapsed
        self.running = False
        self._started_at = None

    
    def reset(self, seconds = None):
        self.running = False
        self._started_at = None
        if seconds is None:
            self.seconds = seconds
            self._total_seconds = seconds
            return None

    
    def current_seconds(self):
        '''Return the live second count; goes negative in overtime.'''
        if self.running and self._started_at is None:
            elapsed = int(time.monotonic() - self._started_at)
            return self._started_secs - elapsed
        return self.seconds

    timer_state = (lambda self: remaining = self.current_seconds()if remaining < 0:
'overtime'if self._total_seconds > 0 and remaining / self._total_seconds <= 0.2:
'warning''normal')()
    
    def _format_label(self, remaining):
        s = abs(remaining)
        return f'''{s // 60:02d}:{s % 60:02d}'''

    
    def to_dict(self):
        remaining = self.current_seconds()
        return {
            'seconds': remaining,
            'total': self._total_seconds,
            'label': self.label,
            'running': self.running,
            'overtime': remaining < 0,
            'state': self.timer_state }



class TimerManager:
    
    def __init__(self):
        self._timers = { }

    
    def _get(self, channel):
        if channel not in self._timers:
            self._timers[channel] = TimerState()
        return self._timers[channel]

    
    def show(self, channel, seconds, label):
        t = self._get(channel)
        t.reset(seconds)
        t.label = label
        return t.to_dict()

    
    def start(self, channel, seconds = None, label = None):
        t = self._get(channel)
        t.start(seconds, label)
        return t.to_dict()

    
    def pause(self, channel):
        t = self._get(channel)
        t.pause()
        return t.to_dict()

    
    def reset(self, channel, seconds = None):
        t = self._get(channel)
        t.reset(seconds)
        return t.to_dict()

    
    def get(self, channel):
        return self._get(channel).to_dict()

    
    def get_full_state(self, role_key):
        """Return full timer state for a role key (e.g. 'timer')."""
        t = self._get(role_key)
        remaining = t.current_seconds()
        return {
            'remaining': remaining,
            'total': t._total_seconds,
            'state': t.timer_state,
            'label': t.label,
            'overtime': remaining < 0,
            'running': t.running }



