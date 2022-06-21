from _event_loop import _socket
from _event_loop import *


class Client:
    def __init__(self, addr):
        self.addr = addr

    def get_user(self, user_id, callback):
        self._get('GET user %s\n' % user_id, callback)

    def get_balance(self, account_id, callback):
        self._get('GET account %s\n' % account_id, callback)

    def _get(self, req, callback):
        sock = socket(_socket.AF_INET, _socket.SOCK_STREAM)

        def _on_conn(err):
            if err:
                return callback(err)

            def _on_sent(err):
                if err:
                    sock.close()
                    return callback(err)

                def _on_resp(err, resp=None):
                    sock.close()
                    if err:
                        return callback(err)
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

            def on_account(err, acc=None):
                if err:
                    return done(err)
                done(None, 'User %s has %s USD' % (user['name'], acc['balance']))

            if user_id % 5 == 0:
                raise Exception('Do not throw from callbacks')
            client.get_balance(user['account_id'], on_account)

        client.get_user(user_id, on_user)

    set_timer(random.randint(0, 10e6), on_timer)


def main(serv_addr):
    def on_balance(err, balance=None):
        if err:
            print('ERROR', err)
        else:
            print(balance)

    for i in range(10):
        get_user_balance(serv_addr, i, on_balance)


if __name__ == '__main__':
    event_loop = EventLoop()
    Context.set_event_loop(event_loop)

    serv_addr = ('127.0.0.1', int(sys.argv[1]))
    event_loop.run(main, serv_addr)
