import sys

import random

import json

from consts import KB
from event_loop import _socket, set_timer, Context, EventLoop
import socket


class Client:
    def __init__(self, addr):
        self.addr = addr
    
    def get_user(self, user_id, callback):
        self._get(f'GET user {user_id}\n', callback)
    
    def get_balance(self, account_id, callback):
        self._get(f'GET account {account_id}\n', callback)

    def _get(self, req, callback):  # request?
        # регистрируем event_loop._queue.register_fileobj(_socket, _socket.callbacks[...])
        sock = _socket(socket.AF_INET, socket.SOCK_STREAM)

        def _on_conn(error):
            if error:
                return callback(error)

            def _on_sent(error):
                if error:
                    sock.close()
                    return callback(error)

                def _on_resp(error, resp=None):
                    sock.close()  #?
                    if error:
                        return callback(error)
                    callback(None, json.loads(resp))

                sock.recv(KB, _on_resp)

            sock.sendall(req.encode('utf-8'), _on_sent)  #?
        # Регистрируем on_conn в _socket
        # и _sock.connect() должен быть запущен
        # начиная с этого момента и до завершения процедуры подключения - нам
        # нечего делать в скрипте -> event loop должен обрабатывать эту приостановку(?)
        # пробрасывает это в
        sock.connect(self.addr, _on_conn)


def get_user_balance(serv_addr, user_id, done):
    client = Client(serv_addr)

    def on_timer():

        def on_user(error, user=None):
            if error:
                return done(error)

            def on_account(error, account=None):
                if error:
                    return done(error)
                done(None, f'User {user["name"]} has {account["balance"]} USD')

            if user_id % 5 == 0:
                raise Exception('Do not throw from callbacks')

        client.get_user(user_id, on_user)
    # is event_loop._queue.regiter_timer(hrtime() + rand, on_timer)
    set_timer(random.randint(0, 10e6), on_timer)


def main(serv_addr):
    def on_balance(error, balance=None):
        if error:
            print(f'Error {error}')
        print(balance)

    for i in range(10):
        get_user_balance(serv_addr, i, on_balance)


if __name__ == '__main__':
    event_loop = EventLoop()
    Context.set_event_loop(event_loop)

    serv_addr = ('127.0.0.1', int(sys.argv[1]))
    event_loop.run(main, serv_addr)
