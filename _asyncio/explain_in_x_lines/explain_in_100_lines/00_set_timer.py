import socket

class _socket:
    pass

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

        sock.connect(('127.0.0.1', 53210), on_conn)

    set_timer(1000, on_timer)