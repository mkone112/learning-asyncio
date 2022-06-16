import socket


class _socket:
    """Обертка на сокетом, регистрируем ?базовый файловый дескриптор неблокирующего сокета
    При появлении информации в файловом дескрипторе(видимо при <os>.send(descriptor) -> info)
    need read
    all data writen
    error occured
    -> el будет вызывать соответствующий callback
    """
    def __init__(self, *args):
        self._sock = socket.socket(*args)
        self._sock.setbloking(False)
        self.evloop.register_fileobj(self._sock, self._on_event)
        ...
        self._callbacks = {}

    def _on_event(self, *args):
        """run a callback from self._callbaks if exists"""

    def connect(self, addr, callback):
        """
        self._callbacks['on_conn'] = callback
        self._sock.connect(addr)"""

    def recv(self, n, callback):
        """self._callbacks['on_read_ready'] = callback"""



class Context:
    """Context class is an execution context, providing a placeholder for
     the event loop reference"""
    _event_loop = None

    @classmethod
    def set_event_loop(cls, event_loop):
        cls._event_loop = event_loop

    @property  # упростить
    def evloop(self):
        return self._event_loop


class set_timer(Context):
    """Convenience method to call event_loop.set_timer() without knowing about
     the current event loop variable"""
    def __init__(self, duration, callback):
        self.evloop.set_timer(duration, callback)


def main():
    sock = _socket(socket.AF_INET, socket.SOCK_STREAM)

    def on_timer():
        def on_conn(err):
            if err:
                raise err

            def on_sent(err):
                if err:
                    sock.close()
                    raise err

                def on_read(err, data=None):
                    sock.close()
                    if err:
                        raise err
                    print(data)

                sock.recv(1024, on_read)

            sock.sendall(b'foobar', on_sent)
        # Регистрируем on_conn в _socket
        # и _sock.connect() должен быть запущен
        # начиная с этого момента и до завершения процедуры подключения - нам
        # нечего делать в скрипте -> event loop должен обрабатывать эту приостановку(?)
        sock.connect(('127.0.0.1', 53210), on_conn)

    set_timer(1000, on_timer)


event_loop = EventLoop()
Context.set_event_loop(event_loop)
event_loop.run(main)