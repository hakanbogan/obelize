import asyncore


class Echo(asyncore.dispatcher_with_send):
    def handle_read(self):
        self.send(self.recv(1024))


asyncore.loop()
