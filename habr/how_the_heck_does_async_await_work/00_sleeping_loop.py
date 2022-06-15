import heapq
import time

from datetime import datetime, timedelta


class Task:

    def __init__(self, waiting_until, coro):
        self.coro = coro
        self.waiting_until = waiting_until

    def __eq__(self, other):
        return self.waiting_until == other.waiting_until

    def __lt__(self, other):
        return self.waiting_until < other.waiting_until


class SleepingLoop:
    def __init__(self, *coros):
        self._new = coros
        self._waiting = []

    def run_until_complete(self):
        for coro in self._new:
            wait_for = coro.send(None)
            heapq.heappush(self._waiting, Task(wait_for, coro))

        while self._waiting:
            now = datetime.now()
            task = heapq.heappop(self._waiting)
            if now < task.waiting_until:
                delta = task.waiting_until - now
                time.sleep(delta.total_seconds())
                now = datetime.now()
            try:
                wait_until = task.coro.send(now)
                heapq.heappush(self._waiting, Task(wait_until, task.coro))
            except StopIteration:
                pass

import types
@types.coroutine
def sleep(seconds):
    now = datetime.now()
    wait_until = now + timedelta(seconds=seconds)
    # останавливаем все сопрограммы в текущем стеке
    actual = yield wait_until
    # возобнавляем стек, возвращая время ожидания
    return actual - now


async def countdown(label, wait_for, *, delay=0):
    """Начинает обратный отсчет от wait_for с delay
    Иммитация пользовательского кода"""
    print('%s waiting %s seconds before starting countdown' % (label, delay))
    delta = await sleep(delay)
    print('%s starting after waiting %s' %(label, delay))
    while wait_for:
        print('%s T-minus %s' % (label, wait_for))
        waited = await sleep(1)
        wait_for -= 1
    print('%s lift-off!' % label)


# Запустить el с обратным отсчетом 3х отдельных таймеров

loop = SleepingLoop(
    countdown('A', 5),
    countdown('B', 3, delay=2),
    countdown('C', 4, delay=1),
)
start = datetime.now()
loop.run_until_complete()
print('Elapsed: %s' % (datetime.now() - start))


















