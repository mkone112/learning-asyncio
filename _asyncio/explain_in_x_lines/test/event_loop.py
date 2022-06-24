import collections
import errno
import heapq
# селекторы - высокоуровневая облочка для мультиплексирования
import selectors
import socket
import time


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

    def register_fileobj(self, fileobj, callback):
        self._queue.register_fileobj(fileobj, callback)

    def unregister_fileobj(self, fileobj):
        self._queue.unregister_fileobj(fileobj)

    def set_timer(self, duration, callback):
        self._time = hrtime()
        self._queue.register_timer(self._time + duration,
                                   lambda _: callback())  # разобраться почему lambda нужна

    def _execute(self, callback, *args):
        self._time = hrtime()
        try:
            # "корень" стека
            callback(*args)
        except Exception as exc:
            print('Uncaught exception:', exc)
        self._time = hrtime()


class Queue:
    """Фасад для двух суб-очередей"""
    def __init__(self):
        # мультиплексирование i/o
        self._selector = selectors.DefaultSelector()
        self._timers = []
        self._timer_no = 0
        self._ready = collections.deque()

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
        events = self.select(timeout)

        for key, mask in events:
            callback = key.data
            self._ready.append((callback, mask))

        if not self._ready and self._timers:
            idle = (self._timers[0][0] - tick)
            if idle > 0:
                time.sleep(idle / 10e6)
                return self.pop(tick + idle)

        while self._timers and self._timers[0][0] <= tick:
            *_, callback = heapq.heappop(self._timers)
            self._ready.append((callback, None))

        return self._ready.popleft()

    def select(self, timeout):
        try:
            """Берем первый готовый сокет"""
            events = self._selector.select(timeout)
        except OSError:
            time.sleep(timeout)
            events = tuple()

        return events

    def get_timeout(self, tick):
        return (self._timers[0][0] - tick) / 10e6 if self._timers else None

    def is_empty(self):
        # .get_map Возвращает сопоставление файловых объектов с ключами селектора.
        return not (self._ready or self._timers or self._selector.get_map())

    def close(self):
        self._selector.close()


class Context:
    """Context class is an execution context, providing a placeholder for
     the event loop reference"""

    class states:  # noqa
        INITIAL = 0
        CONNECTING = 1
        CONNECTED = 2
        CLOSED = 3

    @classmethod
    def set_event_loop(cls, event_loop):
        cls.event_loop = event_loop


def hrtime():
    """
    Походу 10e6 - разрешение таймера

    Returns time in microseconds
    """
    return int(time.time() * 10e6)


class set_timer(Context):
    def __init__(self, duration, callback):
        """Convenience method to call event_loop.set_timer() without knowing about
         the current event loop variable
         регистрирует callback с задержкой в event loop

         duration is in microseconds

        """
        self.event_loop.set_timer(duration, callback)


class async_socket(Context):
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
        self.event_loop.register_fileobj(self._sock, self._on_event)

        self._state = self.states.INITIAL
        self._callbacks = {}

    def connect(self, addr, callback):
        if self._state != self.states.INITIAL:
            raise Exception(f'state {self.states.INITIAL} expected, but is {self._state}')

        self._state = self.states.CONNECTING
        self._callbacks['conn'] = callback

        # ~ connect, но -> код ошибки вместо возбуждения исключения
        error_code = self._sock.connect_ex(addr)
        if errno.errorcode[error_code] != 'EINPROGRESS':
            # неожиданное поведение - коннект возвращает не establishing connection in progress
            raise Exception('error code is not EINPROGRESS')

    def recv(self, n, callback):
        """

        Args:
            n (int): число байт
            callback:

        Returns: None
        """
        if self._state != self.states.CONNECTED:
            Exception(f'socket.recv(): self._state expected 2 but actual is {self._state}')

        if 'recv' in self._callbacks:
            Exception('socket.recv(): recv in self._callbacks')

        def _on_read_ready(error):
            if error:
                return callback(error)
            data = self._sock.recv(n)
            callback(None, data)

        self._callbacks['recv'] = _on_read_ready

    def sendall(self, data, callback):
        if self._state != self.states.CONNECTED:
            raise Exception(f'socket.sendall(), self._state expected 2 but actual is {self._state}')

        if 'sent' in self._callbacks:
            raise Exception('socket.sendall(), sent in self._callbacks')

        def _on_write_ready(error):
            nonlocal data
            if error:
                return callback(error)

            n = self._sock.send(data)
            if n < len(data):
                data = data[n:]
                self._callbacks['sent'] = _on_write_ready
            else:
                callback(None)

        self._callbacks['sent'] = _on_write_ready

    def close(self):
        self.event_loop.unregister_fileobj(self._sock)
        self._callbacks.clear()
        self._state = self.states.CLOSED
        self._sock.close()

    def _on_event(self, mask):
        """run a callback from self._callbaks if exists"""
        if self._state == self.states.CONNECTING:
            if mask != selectors.EVENT_WRITE:
                raise Exception(
                    f'_on_event(): mask {selectors.EVENT_WRITE} expeted, but {mask} is actual'
                )

            callback = self._callbacks.pop('conn')

            error = self._get_sock_error()
            if error:
                self.close()
            else:
                self._state = self.states.CONNECTED
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
        """
        Флаги могут существовать на нескольких уровнях протоколов; они всегда присутствуют на самом верхнем из них.
        При манипулировании флагами сокета должен быть указан уровень, на котором находится этот флаг, и имя этого
        флага. Для манипуляции флагами на уровне сокета level задается как SOL_SOCKET. Для манипуляции флагами на
        любом другом уровне этим функциям передается номер соответствующего протокола, управляющего флагами.
        Например, для указания, что флаг должен интерпретироваться протоколом TCP, в параметре level должен
        передаваться номер протокола TCP;
        В случае успеха возвращается ноль.При ошибке возвращается - 1, а значение errno устанавливается должным
        образом.

        Returns: ConnectionError | None

        """
        errorno = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if errorno:
            return ConnectionError(
                f'connection failed: error: {errorno}, {errno.errorcode[errorno]}'
            )
