# coding:UTF-8
import threading


class RecvThread(threading.Thread):

    def __init__(self, method):
        super(RecvThread, self).__init__()
        self.method = method
        self._stopper = threading.Event()

    def stop(self):
        self._stopper.set()

    def stopped(self):
        return self._stopper.isSet()

    # 运行一个进程来监听数据
    def run(self):
        self.method.listen(self)


class SendThread(threading.Thread):

    def __init__(self, method, filename):
        super(SendThread, self).__init__()
        self.method = method
        self.filename = filename
        self._stopper = threading.Event()

    def stop(self):
        self._stopper.set()

    def stopped(self):
        return self._stopper.isSet()

    # 运行一个进程用于发送数据
    def run(self):
        self.method.post_file(self.filename, self)