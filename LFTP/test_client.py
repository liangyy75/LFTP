# coding:UTF-8

from tcp import *
import threads
import time


if __name__ == "__main__":
    mess = ["127.0.0.1", 12001, "127.0.0.1", 10000]
    client = None
    client_listener = None
    while True:
        time.sleep(.500)
        print("type connect - to establish connection \n"
              + "get 'filename' - to download the file from server \n"
              + "post 'filename' - to upload thecon file to server \n"
              + "disconnect - to close the connection\n")
        command = input()
        if command == "connect":
            if client is None:
                client = TCPClient(mess[0], mess[1], mess[2], mess[3])
                client_listener = threads.RecvThread(client)
                client_listener.start()
                client.connect()
        elif "get" in command:
            if client:
                client.get_file(command.split()[1])
            else:
                print("Please connect first")
        elif "post" in command:
            if client:
                client.post_file(command.split()[1])
            else:
                print("Please connect first")
        elif command == "disconnect":
            if client:
                client.close()
                client_listener.stop()
                client.socket.close()
                client = None
                client_listener = None
            else:
                print("Please connect first")
        else:
            print("The command is not correct")