import json
import random
import socket
import sys

from _event_loop import Context, EventLoop, async_socket, set_timer
# from consts import KB, serv_addr


class Client:
    def __init__(self, addr):
        self.addr = addr

    def get_user(self, user_id, callback):
        self._get(f'GET user {user_id}\n', callback)

    def get_balance(self, account_id, callback):
        self._get(f'GET account {account_id}\n', callback)

    def _get(self, req, callback):
        sock = async_socket(socket.AF_INET, socket.SOCK_STREAM)

        def _on_conn(error):
            if error:
                return callback(error)

            def _on_sent(error):
                if error:
                    sock.close()
                    return callback(error)

                def _on_resp(error, resp=None):
                    sock.close()
                    if error:
                        return callback(error)
                    callback(None, json.loads(resp.decode()))

                sock.recv(1024, _on_resp)

            sock.sendall(req.encode('utf8'), _on_sent)

        sock.connect(self.addr, _on_conn)


def get_user_balance(serv_addr, user_id, done):
    client = Client(serv_addr)

    def on_timer():

        def on_user(err, user=None):
            if err:
                return done(err)

            def on_account(error, acc=None):
                if error:
                    return done(error)
                done(None, 'User {} has {} USD'.format(user['name'], acc['balance']))

            if user_id % 5 == 0:
                raise Exception('Do not throw from callbacks')
            client.get_balance(user['account_id'], on_account)

        client.get_user(user_id, on_user)

    set_timer(random.randint(0, 10e6), on_timer)


def main(serv_addr):
    def on_balance(error, balance=None):
        if error:
            print(f'ERROR: {error}')
        else:
            print(balance)  # подробнее?

    for i in range(10):
        get_user_balance(serv_addr, i, on_balance)


if __name__ == '__main__':
    event_loop = EventLoop()
    Context.set_event_loop(event_loop)

    serv_addr = ('127.0.0.1', int(sys.argv[1]))
    event_loop.run(main, serv_addr)
