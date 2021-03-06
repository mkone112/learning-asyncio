import sys

import json

import random

from uuid import uuid4

from socketserver import BaseRequestHandler, TCPServer

from consts import KB


class Handler(BaseRequestHandler):
    users = {}
    accounts = {}

    def handle(self):
        client = f'client {self.client_address}'
        req = self.request.recv(KB)

        if not req:
            print(f'{client} unexpectedly disconnected')
            return

        print(f'{client} < {req}')
        req = req.decode('utf-8')

        if req[-1] != '\n':
            raise Exception('Max request length exceeded')

        method, entity_kind, entity_id = req[:-1].split(' ', 3)  # asterisk
        if (
            method != 'GET'
            or entity_kind not in ('user', 'account')
            or not entity_id.isdigit()
        ):
            raise Exception('Bad request')

        if entity_kind == 'user':
            user = self.users.get(entity_id) or {'id': entity_id}   # явно какая-то дичь с setdefault
            self.users[entity_id] = user

            if 'name' not in user:
                user['name'] = str(uuid4()).split('-')[0]

            if 'aacount_id' not in user:
                account_id = str(len(self.accounts) + 1)
                account = {'id': account_id, 'balance': random.randint(0, 100)}
                self.accounts[account_id] = account
                user['account_id'] = account_id

            self.send(user)
            return

        if entity_kind == 'account':
            account = self.accounts[entity_id]
            self.send(account)
            return

    def send(self, data):
        resp = json.dumps(data).encode('utf-8')
        print(f'client {self.client_address} > {resp}')
        self.request.sendall(resp)


if __name__ == '__main__':
    port = int(sys.argv[1])
    with TCPServer(('127.0.0.1', port), Handler) as server:
        server.serve_forever()
