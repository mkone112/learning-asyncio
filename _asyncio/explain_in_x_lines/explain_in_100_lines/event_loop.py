import collections
import errno
import heapq
# селекторы - высокоуровневая облочка для мультиплексирования
import selectors
import socket
import time

from consts import KB


class Context:
    """Context class is an execution context, providing a placeholder for
     the event loop reference"""
    _event_loop = None

    class state:
        INITIAL = 0
        CONNECTING = 1
        CONNECTED = 2
        CLOSED = 3

    @classmethod
    def set_event_loop(cls, event_loop):
        cls._event_loop = event_loop

    @property  # упростить
    def evloop(self):
        return self._event_loop


class _socket(Context):
    """Обертка на сокетом, регистрируем ?базовый файловый дескриптор неблокирующего сокета
    При появлении информации в файловом дескрипторе(видимо при <os>.send(descriptor) -> info)
    need read
    all data writen
    error occured
    -> el будет вызывать соответствующий callback
    """
    def __init__(self, *args):
        self._sock = socket.socket(*args)
        self._sock.setblocking(False)
        self.evloop.register_fileobj(self._sock, self._on_event)

        self._state = self.state.INITIAL
        self._callbacks = {}

    def _on_event(self, mask):
        """run a callback from self._callbaks if exists"""
        if self._state == self.state.CONNECTING:
            assert mask == selectors.EVENT_WRITE
            callback = self._callbacks.pop('conn')  # ~?ready
            error = self._get_sock_error()
            if error:
                self.close()
            else:
                self._state = self.state.CONNECTED
            callback(error)

        if mask & selectors.EVENT_READ:
            callback = self._callbacks.get('recv')
            if callback:
                del self._callbacks['recv']
                error = self._get_sock_error()
                callback(error)

        if mask & selectors.EVENT_WRITE:
            callback = self._callbacks.get('sent')
            if callback:
                del self._callbacks['sent']
                error = self._get_sock_error()
                callback(error)

    def _get_sock_error(self):
        # Флаги могут существовать на нескольких уровнях протоколов; они всегда присутствуют на самом верхнем из них.
        # При манипулировании флагами сокета должен быть указан уровень, на котором находится этот флаг, и имя этого
        # флага. Для манипуляции флагами на уровне сокета level задается как SOL_SOCKET. Для манипуляции флагами на
        # любом другом уровне этим функциям передается номер соответствующего протокола, управляющего флагами.
        # Например, для указания, что флаг должен интерпретироваться протоколом TCP, в параметре level должен
        # передаваться номер протокола TCP;
        # В случае успеха возвращается ноль.При ошибке возвращается - 1, а значение errno устанавливается должным
        # образом.
        error = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if error:
            return IOError('connection failed', error, errno.errorcode[error])

    def connect(self, addr, callback):
        """"""
        assert self._state == self.state.INITIAL, 'Socket state is not INITIAL'
        self._state = self.state.CONNECTING
        self._callbacks['on_conn'] = callback
        err = self._sock.connect_ex(addr)
        assert errno.errorcode[err] == 'EINPROGRESS'

    def recv(self, n, callback):
        """"""
        assert self._state == self.state.CONNECTED
        assert 'recv' not in self._callbacks

        def _on_read_ready(err):
            if err:
                return callback(err)
            data = self._sock.recv(n)
            callback(None, data)

        self._callbacks['on_read_ready'] = _on_read_ready

    def sendall(self, data, callback):
        assert self._state == self.state.CONNECTED
        assert 'sent' not in self._callbacks

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
        self._state = self.state.CLOSED
        self._sock.close()


class set_timer(Context):
    """Convenience method to call event_loop.set_timer() without knowing about
     the current event loop variable
     регистрирует callback с задержкой в event loop

     duration - in ms
     """
    def __init__(self, duration, callback):
        self.evloop.set_timer(duration, callback)


class EventLoop:
    def __init__(self):
        self._queue = Queue()
        self._time = None

    def run(self, entry_point, *args):
        self._execute(entry_point, *args)

        while not self._queue.is_empty():
            fn, mask = self._queue.pop(self._time)  # откуда берется self._time?
            self._execute(fn, mask)

        self._queue.close()

    def _execute(self, callback, *args):
        self._time = hrtime()
        try:
            # "корень" стека
            callback(*args)
        except Exception as err:
            print('Uncaught exception:', err)
        self._time = hrtime()

    def register_fileobj(self, fileobj, callback):
        """а нужно ли?"""
        self._queue.register_fileobj(fileobj, callback)

    def unregister_fileobj(self, fileobj):
        """а нужно ли?"""
        self._queue.unregister_fileobj(fileobj)

    def set_timer(self, duration, callback):
        self._time = hrtime()
        # на данный момент lambda излишня
        self._queue.register_timer(self._time + duration, lambda _: callback())


def hrtime():
    """return time in ms"""
    # походу 10e6 - разрешение таймера
    return int(time.time() * 10e6)


class Queue:
    """Фасад для двух суб-очередей"""
    def __init__(self):
        # мультиплексирование i/o
        self._selector = selectors.DefaultSelector()
        self._timers = []
        self._timer_no = 0
        self._ready = collections.deque()

    def is_empty(self):
        # Возвращает сопоставление файловых объектов с ключами селектора.
        return not (self._ready or self._timers or self._selector.get_map())

    def get_timeout(self, tick):
        return (self._timers[0][0] - tick) / 10e6 if self._timers else None

    def pop(self, tick):
        """Возвращает следующий готовый к выполению callback
        Если нечего запускать - просто спит

        На каждой итерации цикл событий пытается синхронно извлечь следующий обратный вызов из очереди. Если в данный
        момент нет обратного вызова для выполнения, pop() блокирует основной поток. Когда обратный вызов готов, цикл
        обработки событий выполняет его. Выполнение обратного вызова всегда происходит синхронно. Каждое выполнение
        обратного вызова запускает новый стек вызовов, который длится до полного синхронного вызова в дереве вызовов с
        корнем в исходном обратном вызове. Это также объясняет, почему ошибки должны доставляться как параметры
        обратного вызова, а не выбрасываться. Создание исключения влияет только на текущий стек вызовов, в то время
        как стек вызовов получателя может находиться в другом дереве. И в любой момент времени существует только один
        стек вызовов. т.е. если исключение, выброшенное функцией, не было перехвачено в текущем стеке вызовов, оно
        появится непосредственно в методе EventLoop._execute().

        Выполнение текущего обратного вызова регистрирует новые обратные вызовы в очереди. И цикл повторяется.
        """
        if self._ready:
            return self._ready.popleft()

        timeout = self.get_timeout(tick)
        # при операциях на зареганых сокетах - возникает event соответствующей
        # маской и данными
        events = self._selector.select(timeout)
        for key, mask in events:
            callback = key.data
            self._ready.append((callback,  mask))

        if not self._ready and self._timers:
            idle = (self._timers[0][0] - tick)
            if idle > 0:
                time.sleep(idle / 10e6)
                return self.pop(tick + idle)

        while self._timers and self._timers[0][0] <= tick:
            _, _, callback = heapq.heappop(self._timers)
            self._ready.append((callback, None))

        return self._ready.popleft()

    def register_timer(self, tick, callback):
        timer = (tick, self._timer_no, callback)
        heapq.heappush(self._timers, timer)
        self._timer_no += 1

    def register_fileobj(self, fileobj, callback):
        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        # Зарегистрировать файловый объект для выбора, отслеживая его на предмет событий ввода-вывода.
        # fileobj — это файловый объект, который нужно отслеживать. Это может быть целочисленный файловый дескриптор или объект с методом fileno(). events — это побитовая маска отслеживаемых событий. data — непрозрачный объект.
        # Это возвращает новый экземпляр SelectorKey или вызывает ValueError в случае недопустимой маски события или дескриптора файла, или KeyError, если объект файла уже зарегистрирован
        self._selector.register(fileobj, events, callback)

    def unregister_fileobj(self, fileobj):
        # Это возвращает связанный экземпляр SelectorKey или вызывает KeyError, если fileobj не зарегистрирован.
        self._selector.unregister(fileobj)

    def close(self):
        self._selector.close()


def main():
    # регистрируем event_loop._queue.register_fileobj(_socket, _socket.callbacks[...])
    sock = _socket(socket.AF_INET, socket.SOCK_STREAM)

    def on_timer():
        def on_conn(err):
            if err:
                raise err

            def on_sent(err):
                if err:
                    sock.close()  #?
                    raise err

                def on_read(err, data=None):
                    sock.close()  #?
                    if err:
                        raise err
                    print(data)

                sock.recv(KB, on_read)

            sock.sendall(b'foobar', on_sent)  #?
        # Регистрируем on_conn в _socket
        # и _sock.connect() должен быть запущен
        # начиная с этого момента и до завершения процедуры подключения - нам
        # нечего делать в скрипте -> event loop должен обрабатывать эту приостановку(?)
        # пробрасывает это в
        sock.connect(('127.0.0.1', 53210), on_conn)

    # is event_loop._queue.regiter_timer(hrtime() + 1000, on_timer)
    set_timer(1000, on_timer)


event_loop = EventLoop()
Context.set_event_loop(event_loop)  # instance?
event_loop.run(main)
