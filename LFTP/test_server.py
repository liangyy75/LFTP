# coding:UTF-8

from tcp import *
import threads

if __name__ == "__main__":
    server = TCPServer("127.0.0.1", 10000)
    server_listener = threads.RecvThread(server)
    server_listener.start()

    # https://www.cnblogs.com/vincent2010/p/4780717.html -- 一行 Python 实现并行化 -- 日常多线程操作的新思路