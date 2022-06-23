import collections
import errno
import heapq
import json
import random
import selectors
import socket as _socket
import sys
import time


class EventLoop:
    def __init__(self):
        self._queue = Queue()
        self._time = None

    def run(self, entry_point, *args):
        self._execute(entry_point, *args)

        while not self._queue.is_empty():
            fn, mask = self._queue.pop(self._time)
            self._execute(fn, mask)

        self._queue.close()

    def register_fileobj(self, fileobj, callback):
        self._queue.register_fileobj(fileobj, callback)

    def unregister_fileobj(self, fileobj):
        self._queue.unregister_fileobj(fileobj)

    def set_timer(self, duration, callback):
        self._time = hrtime()
        self._queue.register_timer(self._time + duration,
                                   lambda _: callback())

    def _execute(self, callback, *args):
        self._time = hrtime()
        try:
            callback(*args)  # new callstack starts
        except Exception as err:
            print('Uncaught exception:', err)
        self._time = hrtime()


class Queue:
    def __init__(self):
        self._selector = selectors.DefaultSelector()
        self._timers = []
        self._timer_no = 0
        self._ready = collections.deque()

    def register_timer(self, tick, callback):
        timer = (tick, self._timer_no, callback)
        heapq.heappush(self._timers, timer)
        self._timer_no += 1

    def register_fileobj(self, fileobj, callback):
        self._selector.register(fileobj,
                                selectors.EVENT_READ | selectors.EVENT_WRITE,
                                callback)

    def unregister_fileobj(self, fileobj):
        self._selector.unregister(fileobj)

    def pop(self, tick):
        if self._ready:
            return self._ready.popleft()

        timeout = None
        if self._timers:
            timeout = (self._timers[0][0] - tick) / 10e6  # выглядит как дубль

        # if sys.platform == 'win32':
        events = tuple()
        try:
            events = self._selector.select(timeout)
        except OSError:
            time.sleep(timeout)
        for key, mask in events:
            callback = key.data
            self._ready.append((callback, mask))

        if not self._ready and self._timers:
            idle = (self._timers[0][0] - tick)
            if idle > 0:
                time.sleep(idle / 10e6)
                return self.pop(tick + idle)

        while self._timers and self._timers[0][0] <= tick:
            _, _, callback = heapq.heappop(self._timers)
            self._ready.append((callback, None))

        return self._ready.popleft()

    def is_empty(self):
        return not (self._ready or self._timers or self._selector.get_map())

    def close(self):
        self._selector.close()


class Context:
    _event_loop = None

    @classmethod
    def set_event_loop(cls, event_loop):
        cls._event_loop = event_loop

    @property
    def evloop(self):
        return self._event_loop


class IOError(Exception):
    def __init__(self, message, errorno, errorcode):
        super().__init__(message)
        self.errorno = errorno
        self.errorcode = errorcode

    def __str__(self):
        return super().__str__() + f' (error {self.errorno} {self.errorcode})'


def hrtime():
    """ returns time in microseconds """
    return int(time.time() * 10e6)


class set_timer(Context):
    def __init__(self, duration, callback):
        """ duration is in microseconds """
        self.evloop.set_timer(duration, callback)


class socket(Context):
    def __init__(self, *args):
        self._sock = _socket.socket(*args)
        self._sock.setblocking(False)
        self.evloop.register_fileobj(self._sock, self._on_event)
        # 0 - initial
        # 1 - connecting
        # 2 - connected
        # 3 - closed
        self._state = 0
        self._callbacks = {}

    def connect(self, addr, callback):
        assert self._state == 0, 'state {} expected, but is {}'.format(self._state, self._state)
        self._state = 1
        self._callbacks['conn'] = callback
        err = self._sock.connect_ex(addr)
        assert errno.errorcode[err] == 'EINPROGRESS', 'error code is not EINPROGRESS'

    def recv(self, n, callback):
        assert self._state == 2, f'socket.recv(): self._state expected 2 but actual is {self._state}'
        assert 'recv' not in self._callbacks, 'socket.recv(): recv in self._callbacks'

        def _on_read_ready(err):
            if err:
                return callback(err)
            data = self._sock.recv(n)
            callback(None, data)

        self._callbacks['recv'] = _on_read_ready

    def sendall(self, data, callback):
        assert self._state == 2, f'socket.sendall(), self._state expected 2 but actual is {self._state}'
        assert 'sent' not in self._callbacks, 'socket.sendall(), sent in self._callbacks'

        def _on_write_ready(err):
            nonlocal data
            if err:
                return callback(err)

            n = self._sock.send(data)
            if n < len(data):
                data = data[n:]
                self._callbacks['sent'] = _on_write_ready
            else:
                callback(None)

        self._callbacks['sent'] = _on_write_ready

    def close(self):
        self.evloop.unregister_fileobj(self._sock)
        self._callbacks.clear()
        self._state = 3
        self._sock.close()

    def _on_event(self, mask):
        if self._state == 1:
            assert mask == selectors.EVENT_WRITE, f'_on_event(): mask {selectors.EVENT_WRITE} expeted, but {mask} is actual'
            cb = self._callbacks.pop('conn')
            err = self._get_sock_error()
            if err:
                self.close()
            else:
                self._state = 2
            cb(err)

        if mask & selectors.EVENT_READ:
            cb = self._callbacks.get('recv')
            if cb:
                del self._callbacks['recv']
                err = self._get_sock_error()
                cb(err)

        if mask & selectors.EVENT_WRITE:
            cb = self._callbacks.get('sent')
            if cb:
                del self._callbacks['sent']
                err = self._get_sock_error()
                cb(err)

    def _get_sock_error(self):
        err = self._sock.getsockopt(_socket.SOL_SOCKET,
                                    _socket.SO_ERROR)
        if not err:
            return None
        return IOError('connection failed',
                       err, errno.errorcode[err])
