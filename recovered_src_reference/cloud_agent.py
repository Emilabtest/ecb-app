# Source Generated with Decompyle++
# File: cloud_agent.pyc (Python 3.12)

import asyncio
import json
import logging
import os
import threading
import time
from jsonio import atomic_write_json
import websockets
logger = logging.getLogger('leiturgia.cloud')
CONFIG_FILE = 'config.json'
DATA_FILE = 'data/program.json'
_BACKOFF = [
    2,
    4,
    8,
    16,
    30]
_HEARTBEAT_INTERVAL = 30
_SYNC_DEBOUNCE = 0.8

class CloudAgent:
    '''WebSocket client that maintains the Pi-to-cloud connection.'''
    
    def __init__(self):
        self._status = 'not_linked'
        self._loop = None
        self._ws = None
        self._on_program_update = None
        self._cloud_version = 0
        self._notify_data = None
        self._notify_time = 0
        self._force_data = None
        self._pending_ui_notify = False
        self._restart_event = threading.Event()

    status = (lambda self: self._status)()
    linked = (lambda self: cfg = self._load_config()if cfg.get('cloud_enabled'):
cfg.get('cloud_enabled')if cfg.get('cloud_url'):
cfg.get('cloud_url')bool(cfg.get('cloud_enabled')))()
    
    def set_program_update_callback(self, cb):
        self._on_program_update = cb

    
    def notify_program_saved(self, data):
        '''Called by Flask thread after saving program.json; debounced 800ms before push.'''
        self._notify_data = data
        self._notify_time = time.monotonic()

    
    def force_push_program(self, data):
        '''Send sync:program immediately, bypassing debounce ΓÇö used by manual sync.'''
        self._force_data = data

    
    def start(self):
        '''Start the agent in a real OS thread (asyncio loop inside).'''
        cfg = self._load_config()
        if not cfg.get('cloud_enabled'):
            return None
        
        try:
            from eventlet.patcher import original as _orig
            _Thread = _orig('threading').Thread
        except ImportError:
            import threading as _threading
            _Thread = _threading.Thread

        t = _Thread(target = self._run_loop, daemon = True)
        t.start()

    
    def restart(self):
        '''Reload config and reconnect ΓÇö called after successful /api/cloud/link.'''
        self._restart_event.set()
        self.start()

    
    def _load_config(self):
        
        try:
            f = open(CONFIG_FILE)
            json.load(f)(None, None)
            return None
        except Exception:
            return { }

    # WARNING: Decompyle incomplete

    
    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            self._loop.run_until_complete(self._connect_loop())
        self._loop = None
        self._status = 'not_linked'

        self._loop.close()
        self._loop = None
        self._status = 'not_linked'
        return None
        
        try:
            self._loop.run_until_complete(self._connect_loop())
        self._loop = None
        self._status = 'not_linked'


    
    async def _connect_loop(self):
        backoff_idx = 0
        cfg = self._load_config()
        if not cfg.get('cloud_enabled'):
            self._status = 'not_linked'
            return None
        cloud_url = cfg.get('cloud_url', '').strip().rstrip('/')
        cloud_token = cfg.get('cloud_token', '').strip()
        if not cloud_url or not cloud_token:
            self._status = 'not_linked'
            return None
        ws_url = f'''wss://{cloud_url}/ws/device'''
        self._status = 'connecting'
        
        try:
            # unsupported opcode BEFORE_ASYNC_WITH
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            try:
                # unsupported opcode CLEANUP_THROW

            # unsupported opcode END_SEND
            ws = websockets.connect(ws_url, additional_headers = {
                'Authorization': f'''Bearer {cloud_token}''' }, ping_interval = None)
            self._ws = ws
            self._status = 'connected'
            backoff_idx = 0
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                yield None
            try:
                # unsupported opcode CLEANUP_THROW
            except Exception as exc:
                logger.warning('Cloud WebSocket disconnected: %s', exc)

            try:
                # unsupported opcode CLEANUP_THROW
            except:
                # unsupported opcode GET_AWAITABLE
                # unsupported opcode SEND
                
                try:
                    yield None
                # unsupported opcode CLEANUP_THROW
                # unsupported opcode END_SEND
                self._ws = None
                
                try:
                    yield None
                # unsupported opcode CLEANUP_THROW
                
                try:
                    yield None
                # unsupported opcode CLEANUP_THROW



                
                try:
                    yield None
                # unsupported opcode CLEANUP_THROW
                # unsupported opcode END_SEND
                self._ws = None
                
                try:
                    yield None
                # unsupported opcode CLEANUP_THROW
                
                try:
                    yield None
                # unsupported opcode CLEANUP_THROW




            # unsupported opcode END_SEND
            self._session(ws)
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            try:
                # unsupported opcode CLEANUP_THROW
            except Exception as exc:
                logger.warning('Cloud WebSocket disconnected: %s', exc)

            # unsupported opcode END_SEND
            None(None, None)

        self._ws = None
        if self._restart_event.is_set():
            self._restart_event.clear()
            backoff_idx = 0
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW


            # unsupported opcode END_SEND
            asyncio.sleep(0.5)
        self._status = 'reconnecting'
        delay = _BACKOFF[min(backoff_idx, len(_BACKOFF) - 1)]
        backoff_idx = min(backoff_idx + 1, len(_BACKOFF) - 1)
        # unsupported opcode GET_AWAITABLE
        # unsupported opcode SEND
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW

        # unsupported opcode END_SEND
        asyncio.sleep(delay)
        
        try:
            yield None
        try:
            # unsupported opcode CLEANUP_THROW

        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        try:
            # unsupported opcode CLEANUP_THROW
        except Exception as exc:
            logger.warning('Cloud WebSocket disconnected: %s', exc)

        try:
            # unsupported opcode CLEANUP_THROW
        except:
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            # unsupported opcode END_SEND
            self._ws = None
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW



            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            # unsupported opcode END_SEND
            self._ws = None
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW




    # WARNING: Decompyle incomplete

    
    async def _session(self, ws):
        heartbeat = asyncio.create_task(self._heartbeat(ws))
        poller = asyncio.create_task(self._sync_poller(ws))
        
        try:
            
            try:
                # unsupported opcode SEND
                yield None
                # unsupported opcode END_SEND

            raw = None
            
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                pass

            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                # unsupported opcode CLEANUP_THROW
            # unsupported opcode END_ASYNC_FOR
            poller.cancel()
            for t in (heartbeat, poller):
                
                try:
                    # unsupported opcode GET_AWAITABLE
                    # unsupported opcode SEND
                    
                    try:
                        yield None
                    # unsupported opcode CLEANUP_THROW
                    # unsupported opcode END_SEND
                    continue
                    except asyncio.CancelledError:
                        pass

                    continue

            return None
            heartbeat.cancel()
            poller.cancel()
            for t in (heartbeat, poller):
                
                try:
                    # unsupported opcode GET_AWAITABLE
                    # unsupported opcode SEND
                    
                    try:
                        yield None
                    # unsupported opcode CLEANUP_THROW
                    # unsupported opcode END_SEND
                    continue
                    except asyncio.CancelledError:
                        pass

                    continue



            # unsupported opcode END_SEND
            self._handle_event(msg)
            
            try:
                # unsupported opcode CLEANUP_THROW
            # unsupported opcode END_ASYNC_FOR
            poller.cancel()
            for t in (heartbeat, poller):
                
                try:
                    # unsupported opcode GET_AWAITABLE
                    # unsupported opcode SEND
                    
                    try:
                        yield None
                    # unsupported opcode CLEANUP_THROW
                    # unsupported opcode END_SEND
                    continue
                    except asyncio.CancelledError:
                        pass

                    continue

            return None
            heartbeat.cancel()
            poller.cancel()
            for t in (heartbeat, poller):
                
                try:
                    # unsupported opcode GET_AWAITABLE
                    # unsupported opcode SEND
                    
                    try:
                        yield None
                    # unsupported opcode CLEANUP_THROW
                    # unsupported opcode END_SEND
                    continue
                    except asyncio.CancelledError:
                        pass

                    continue


            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                # unsupported opcode CLEANUP_THROW
            # unsupported opcode END_ASYNC_FOR
            poller.cancel()
            for t in (heartbeat, poller):
                
                try:
                    # unsupported opcode GET_AWAITABLE
                    # unsupported opcode SEND
                    
                    try:
                        yield None
                    # unsupported opcode CLEANUP_THROW
                    # unsupported opcode END_SEND
                    continue
                    except asyncio.CancelledError:
                        pass

                    continue

            return None
            heartbeat.cancel()
            poller.cancel()
            for t in (heartbeat, poller):
                
                try:
                    # unsupported opcode GET_AWAITABLE
                    # unsupported opcode SEND
                    
                    try:
                        yield None
                    # unsupported opcode CLEANUP_THROW
                    # unsupported opcode END_SEND
                    continue
                    except asyncio.CancelledError:
                        pass

                    continue




    # WARNING: Decompyle incomplete

    
    async def _heartbeat(self, ws):
        elapsed = 0
        # unsupported opcode GET_AWAITABLE
        # unsupported opcode SEND
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        try:
            # unsupported opcode CLEANUP_THROW
        except Exception:
            return None

        try:
            # unsupported opcode CLEANUP_THROW
        except:
            pass


        # unsupported opcode END_SEND
        asyncio.sleep(1)
        elapsed += 1
        if self._restart_event.is_set():
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                yield None
            try:
                # unsupported opcode CLEANUP_THROW
            except Exception:
                return None

            try:
                # unsupported opcode CLEANUP_THROW
            except:
                pass

            # unsupported opcode END_SEND
            ws.close()
            return None
        if elapsed >= _HEARTBEAT_INTERVAL:
            elapsed = 0
            
            try:
                # unsupported opcode GET_AWAITABLE
                # unsupported opcode SEND
                
                try:
                    yield None
                try:
                    # unsupported opcode CLEANUP_THROW
                except Exception:
                    return None

                # unsupported opcode END_SEND
                ws.send(json.dumps({
                    'event': 'device:status' }))

        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        try:
            # unsupported opcode CLEANUP_THROW
        except Exception:
            return None

        try:
            # unsupported opcode CLEANUP_THROW
        except:
            pass


    # WARNING: Decompyle incomplete

    
    async def _sync_poller(self, ws):
        '''Poll for outbound sync requests every 100ms; implements debounce for notify.'''
        # unsupported opcode GET_AWAITABLE
        # unsupported opcode SEND
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW



        # unsupported opcode END_SEND
        asyncio.sleep(0.1)
        if self._force_data is None:
            data = self._force_data
            self._force_data = None
            self._notify_data = None
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW


            # unsupported opcode END_SEND
            self._send_payload(ws, data)
        if self._notify_data is None and time.monotonic() - self._notify_time >= _SYNC_DEBOUNCE:
            data = self._notify_data
            self._notify_data = None
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW

            # unsupported opcode END_SEND
            self._send_payload(ws, data)
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW



    # WARNING: Decompyle incomplete

    
    async def _send_payload(self, ws, data):
        
        try:
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            try:
                # unsupported opcode CLEANUP_THROW
            except Exception as exc:
                logger.warning('Failed to send sync:program: %s', exc)
                return None

            # unsupported opcode END_SEND
            ws.send(json.dumps({
                'event': 'sync:program',
                'data': data,
                'version': self._cloud_version }))

        return None
        
        try:
            yield None
        try:
            # unsupported opcode CLEANUP_THROW
        except Exception as exc:
            logger.warning('Failed to send sync:program: %s', exc)
            return None

    # WARNING: Decompyle incomplete

    
    async def _handle_event(self, msg):
        event = msg.get('event')
        data = msg.get('data', { })
        if event == 'sync:program':
            # unsupported opcode GET_AWAITABLE
            # unsupported opcode SEND
            
            try:
                yield None
            # unsupported opcode CLEANUP_THROW

            # unsupported opcode END_SEND
            self._apply_program(data, msg.get('version', 0))
            return None
        if event == 'sync:media:add':
            asyncio.get_event_loop().run_in_executor(None, self._download_media, data)
            return None
        if event == 'sync:media:delete':
            self._delete_media(data)
            return None
        return None
        
        try:
            yield None
        # unsupported opcode CLEANUP_THROW

    # WARNING: Decompyle incomplete

    
    async def _apply_program(self, data, version = 0):
        
        try:
            atomic_write_json(DATA_FILE, data)
            self._cloud_version = version
            logger.info('sync:program applied from cloud (version %s)', version)
        except Exception as exc:
            logger.error('Failed to apply sync:program: %s', exc)
            return None

        self._pending_ui_notify = True

    
    def _download_media(self, data):
        import urllib.request as urllib
        url = data.get('url', '')
        filename = os.path.basename(data.get('filename', ''))
        if not url or not filename:
            return None
        dest_dir = os.path.join('media', 'images')
        os.makedirs(dest_dir, exist_ok = True)
        dest = os.path.join(dest_dir, filename)
        
        try:
            urllib.request.urlretrieve(url, dest)
            logger.info('Downloaded media: %s', filename)
            return None
        except Exception as exc:
            logger.error('Failed to download %s: %s', filename, exc)
            return None


    
    def _delete_media(self, data):
        filename = os.path.basename(data.get('filename', ''))
        if not filename:
            return None
        for subdir in ('images', 'videos'):
            path = os.path.join('media', subdir, filename)
            if not os.path.exists(path):
                continue
            
            try:
                os.remove(path)
                logger.info('Deleted media: %s', filename)
                return None
            except Exception as exc:
                logger.error('Failed to delete %s: %s', filename, exc)
                ('images', 'videos')
                return None



agent = CloudAgent()

