# coding:UTF-8
from header import *
from socket import *
from threads import *
from Buffer import *
import os
import random


# 每个用户一个connection，代表一个连接
# 拥有属性：
#   tag: 客户端(True)还是服务端(False)
#   dest_address: 目的地址
#   dest_port: 目的端口
#   socket: 管理这个connection的socket，提供send方法给connection
#   lock: 获取的线程锁
#   header: 这个连接的头部
#   cnt_tag: 连接状态
#   get_tag: get状态
#   post_tag: post状态
#   error_tag: error状态
#   out: 文件
#   timer: 计时器
#   window: 缓存窗口
class Connection:

    def __init__(self, tag, dest_address, dest_port, socket):
        self.tag = tag
        self.dest_address = dest_address
        self.dest_port = dest_port
        self.socket = socket
        self.lock = None
        self.header = Header()
        self.cnt_tag, self.get_tag, self.post_tag, self.error_tag = 0, 0, 0, 0
        self.out = None
        self.ttl_timer = TTLTimer()
        self.send_window = None
        self.receive_window = None
        self.current_state = "slow"
        self.duplicate_ack = dict()
        self.duplicate_resend = None
        self.last_ack_num = 0
        self.header.dest_port = dest_port

    def set_lock(self, lock):
        self.lock = lock

    # 处理packet
    def deal_with_packet(self, packet, header):
        message = ("客户端" if self.tag else "服务端") + "接受到一个{0}报文，头部是：" + str(header.get_header())
        # get/post，客户端和服务端的操作是一样的吗？？？
        if header.cnt:
            print(message.format("控制"))
            self.deal_with_cnt(header)
        elif header.dat:
            self.deal_with_dat(header, packet)
            # print(message.format("数据"))
        else:
            print(message.format("get" if header.operation else "post"))
            self.deal_with_operation(header, packet)

    # 处理控制报文
    def deal_with_cnt(self, header):
        self.header.ack_num = header.seq_num
        if self.tag:
            if self.cnt_tag == 0 and header.ack and self.header.syn:
                print("客户端：建立连接 —— 接收到 SYN ACK 报文，发送 SYN = 0 报文")
                self.cnt_tag = 1
                # connect里面会自动send syn=0了
            elif self.cnt_tag == 1 and header.ack:
                print("客户端：建立连接 —— 接收到 ACK，连接建立成功")
                self.cnt_tag = 2
            elif self.cnt_tag == 2 and self.header.fin and header.ack:
                print("客户端：结束连接 —— 接受到 FIN ACK 报文，发送 FIN = 0 报文")
                self.cnt_tag = 3
                # close里面会自动send fin=0了
            elif self.cnt_tag == 3 and header.ack:
                print("客户端：结束连接 —— 接受到 FIN = 0 ACK 报文，结束连接")
                self.cnt_tag = 0
        else:
            if self.cnt_tag == 0 and header.syn:
                print("服务端：建立连接 —— 接受到 SYN = 1 报文，发送 SYN ACK 报文")
                self.header.cnt = True
                self.send_ack()
                self.cnt_tag = 1
            elif self.cnt_tag == 1 and header.syn and header.seq_num == 0:
                print("服务端：建立连接 —— SYN ACK重发")
                self.resend_cnt_ack()
            elif self.cnt_tag == 1 and not header.ack and not header.syn:
                print("服务端：建立连接 —— 连接已完成建立")
                self.cnt_tag = 2
                self.send_ack()
                self.header.cnt = False
            elif self.cnt_tag == 2 and header.fin:
                print("服务端：结束连接 —— 接收到 FIN = 1 报文，发送 FIN ACK 报文")
                self.header.cnt = True
                self.send_ack()
                self.cnt_tag = 3
            elif self.cnt_tag == 2 and not header.ack and not header.syn:
                print("服务端：建立连接 —— SYN = 0 的ACK重发")
                self.resend_cnt_ack()
            elif self.cnt_tag == 3 and not header.ack and not header.fin:
                print("服务端：结束连接 —— 接受到 FIN = 0 报文，发送 ACK，连接关闭")
                self.cnt_tag = 0
                self.send_ack()
                self.header.cnt = False
            elif self.cnt_tag == 3 and not header.seq_num and header.fin:
                print("服务端：结束连接 —— 重传 FIN ACK")
                self.resend_cnt_ack()
            elif self.cnt_tag == 0 and not header.ack and not header.fin:
                print("服务端：结束连接 —— FIN = 0 的ACK重发")
                self.resend_cnt_ack()

    # 处理数据报文
    def deal_with_dat(self, header, packet):
        role = "客户端" if self.tag else "服务端"
        if self.get_tag == 1:
            # 接收方
            self.get_tag = 2
            self.header.dat = True
        if self.post_tag == 1:
            # 接收方
            self.post_tag = 2
            self.header.dat = True
        # 准备输入文件
        if header.ack and (self.get_tag == 2 or self.post_tag == 2):
            # 发送方
            # print(role + "：接收到ACK为%d的数据包" % header.ack_num)
            if header.ack_num == self.send_window.least_not_ack():
                print(role + "：接收到ACK为%d的数据包" % header.ack_num)
                self.send_window.ack_and_renew(header.ack_num)
                self.send_window.quick_update_cwnd(self.current_state, new_ack=1)
                self.current_state = "slow"
                if header.ack_num in self.duplicate_ack.keys():
                    del self.duplicate_ack[header.ack_num]
            else:
                if header.ack_num not in self.duplicate_ack.keys():
                    self.duplicate_ack[header.ack_num] = 0
                self.duplicate_ack[header.ack_num] += 1
                self.duplicate_resend = self.send_window.quick_update_cwnd(
                    self.current_state,
                    duplicate_ack=self.send_window.least_not_ack() - 1,
                    dupack_count=self.duplicate_ack[header.ack_num]
                )
                if self.duplicate_ack[header.ack_num] >= 3:
                    self.current_state = "quick"
                    self.duplicate_ack[header.ack_num] = 0
        elif self.get_tag == 2 or self.post_tag == 2:
            # 接收方
            # 是否重复 TODO
            # print(packet[header.header_len:].decode("utf-8"))
            if self.receive_window is None:
                self.receive_window = ReceiveWindow(self.out)
            self.header.ack_num, self.header.window_size, tag = self.receive_window.return_message(header.seq_num, packet[header.header_len:], header.end)
            # print(role + "：接收到数据包，seq_num：", header.seq_num, "；数据是", packet[header.header_len:], "传回dat ack报文")
            print(role + "：接收到数据包，接收到seq_num：", header.seq_num, "传回dat ack报文，期望", self.header.ack_num)
            self.send_ack()
            if tag:
                self.resend_end_ack()
                self.header.dat = False
                self.header.operation = False
                self.get_tag = 0
                self.post_tag = 0
                self.out = None
                self.duplicate_resend = None
                self.duplicate_ack = dict()
                self.current_state = "slow"
                self.last_ack_num = 0
                self.receive_window = None
                print(role + "：接收到 dat end 数据包，结束传输，发送end ack")
        elif (self.get_tag == 2 or self.post_tag == 2) and header.end and not header.ack:
            pass
        elif (self.get_tag == 0 or self.post_tag == 0) and header.end and not header.ack:
            # 接收方
            self.resend_end_ack()
            print(role + "：重传 end ack 数据包")
        elif (self.get_tag == 3 or self.post_tag == 3) and header.end and header.ack:
            # 发送方
            self.header.end = False
            self.header.dat = False
            self.header.operation = False
            self.get_tag = 0
            self.post_tag = 0
            print(role + "：接收到 end ack，结束连接")

    # 处理指令报文
    def deal_with_operation(self, header, packet):
        if header.operation:
            if self.tag and self.get_tag == 0 and header.ack:
                print("客户端：接收到get ack，确认服务端存在此文件，开始接收文件")
                self.get_tag = 1
            elif self.tag and self.get_tag == 0 and header.error == 1:
                print("客户端：接收到get error，文件不在服务器")
                self.error_tag = 1
            elif not self.tag and not header.ack and self.get_tag == 0:
                print("服务端：接收到get 报文，开始确认文件是否存在")
                path = "./server_files/" + packet[header.header_len:].decode("utf-8")
                if not os.path.exists(path):
                    print("服务端：未找到文件，请输入正确的文件名")
                    self.header.error = 1
                    self.header.operation = True
                    self.send()
                    self.header.error = 0
                    self.header.operation = False
                else:
                    print("服务端：发送get ack，确认文件存在")
                    self.get_tag = 1
                    self.resend_get_ack()
            elif not self.tag and self.get_tag == 1 and not header.ack:
                print("服务端：重发get ack，确认文件存在")
                self.resend_get_ack()
            elif not self.tag and self.get_tag == 1 and header.ack:
                print("服务端：接收到get ack，开始文件传输")
                self.get_tag = 2
                read_and_send_thread = threading.Thread(
                    target=self.read_and_send_file,
                    args=("./server_files/" + packet[header.header_len:].decode("utf-8"), "服务端")
                )
                read_and_send_thread.start()
        else:
            if not self.tag and header.seq_num == 0:
                # 接收方
                self.header.ack_num = 0
                self.header.seq_num = 1
                self.post_tag = 1
                self.out = "./server_files/" + packet[header.header_len:].decode("utf-8")
                self.send_ack()
                print("服务端：接收到post 报文，开始准备文件")
            elif self.tag and header.seq_num == 1 and header.ack:
                print("客户端：接收到post ack，开始文件传输")
                self.post_tag = 2
                read_and_send_thread = threading.Thread(target=self.read_and_send_file, args=(self.out, "客户端"))
                read_and_send_thread.start()

    # 读取文件和发送
    def read_and_send_file(self, filename, role):
        self.send_window = SendWindow(filename)
        self.header.dat = True
        while self.send_window.least_not_ack() != -1:
            if self.duplicate_resend:
                try:
                    self.header.seq_num = self.duplicate_resend.seq_num
                    self.send(self.header, self.duplicate_resend.data)
                    print("快速重传序号是", self.header.seq_num, "DATA IS", self.duplicate_resend.data)
                except Exception as e:
                    print("快速重。。。")
                self.duplicate_resend = None
            time_out_buffers = self.send_window.get_time_out_buffers()
            if len(time_out_buffers) > 0:
                self.send_window.quick_update_cwnd("slow", time_out=1)
                for buffer in time_out_buffers:
                    print("重传序号是", buffer.seq_num, "DATA IS", buffer.data)
                    self.header.seq_num = buffer.seq_num
                    self.send(self.header, buffer.data)
            send_buffers = self.send_window.get_buffers()
            if send_buffers is None or len(send_buffers) == 0:
                continue
            # print(role + "发送数据")
            if not send_buffers == -1 and send_buffers is not None:
                for buffer in send_buffers:
                    # if random.random() < 0.99:
                    print("序号是", buffer.seq_num, "DATA IS", buffer.data)
                    self.header.seq_num = buffer.seq_num
                    self.send(self.header, buffer.data)
                    # print(send_windows.cwnd, send_windows.ssthresh)
        if self.get_tag == 2:
            self.get_tag = 3
        if self.post_tag == 2:
            self.post_tag = 3
        self.header.end = True
        self.send()
        self.ttl_timer.start()
        print(role + "：发送 dat end 报文")
        while self.get_tag == 3 or self.post_tag == 3:
            if self.ttl_timer.is_timeout():
                self.send()
                self.ttl_timer.start()
                print(role + "：重发 dat end 报文")
        print("文件传输结束")
        self.print_state()

    # 发送控制(建立连接和结束连接的控制)报文
    def send_cnt(self, while_cnt_tag, first_message=None, while_message=None):
        self.send()
        self.ttl_timer.start()
        if first_message:
            print(first_message)
        while self.cnt_tag == while_cnt_tag:
            if self.ttl_timer.is_timeout():
                self.send()
                self.ttl_timer.start()
                if while_message:
                    print(while_message)

    def resend_cnt_ack(self):
        self.header.cnt = True
        self.send_ack()
        self.header.cnt = False

    def resend_get_ack(self):
        self.header.operation = True
        self.send_ack()

    def resend_end_ack(self):
        self.header.dat = True
        self.header.end = True
        self.send_ack()
        self.header.end = False
        self.header.dat = False

    # 发送ack
    def send_ack(self):
        self.header.ack = True
        self.send()
        self.header.ack = False

    # 新建一个线程处理get file
    def get_file(self, filename):
        role = "客户端"
        if self.cnt_tag == 2:
            name_bytes = bytearray(filename, encoding="utf-8")
            self.out = "./client_files/" + filename
            self.header.operation = True
            self.header.seq_num = 0
            self.send(self.header, name_bytes)
            self.ttl_timer.start()
            print(role + "：发送第一次get请求")
            while self.get_tag == 0 and self.error_tag == 0:
                if self.ttl_timer.is_timeout():
                    self.send(self.header, name_bytes)
                    self.ttl_timer.start()
                    print(role + "：重发了第一次get请求")
            if self.error_tag != 0:
                self.error_tag = 0
                self.header.operation = False
                self.get_tag = 0
                return
            self.header.ack = True
            self.header.seq_num = 1
            self.send(self.header, name_bytes)
            self.ttl_timer.start()
            print(role + "：发送第二次get请求", name_bytes)
            while self.get_tag == 1 and self.error_tag == 0:
                if self.ttl_timer.is_timeout():
                    self.send(self.header, name_bytes)
                    self.ttl_timer.start()
                    print(role + "：重发了第二次get请求", name_bytes)
            self.header.ack = False
            self.header.seq_num = 0
            self.print_state()
        else:
            print(role + "未连接")

    # 新建一个线程处理post file
    def post_file(self, filename):
        role = "客户端"
        if self.cnt_tag == 2:
            name_bytes = bytearray(filename, encoding="utf-8")
            self.out = "./client_files/" + filename
            if not os.path.exists(self.out):
                print("客户端没有此文件，请输入正确文件名")
                return
            self.post_tag = 1
            self.header.operation = False
            self.header.seq_num = 0
            self.send(self.header, name_bytes)
            self.ttl_timer.start()
            print(role + "正在发送post请求")
            while self.post_tag == 1:
                if self.ttl_timer.is_timeout():
                    self.send(self.header, name_bytes)
                    self.ttl_timer.start()
                    print(role + "重发post请求")
            self.header.seq_num = 0
        pass

    # 发送包
    def send(self, header=None, data=None):
        if self.lock:
            self.lock.acquire()
        try:
            if header is None:
                header = self.header
            datagram = (header.get_header() + data) if data else header.get_header()
            checksum = Connection.checksum_help(datagram)
            datagram[14], datagram[15] = (checksum >> 8) & 0xFF, checksum & 0xFF
            self.socket.sendto(datagram, (self.dest_address, self.dest_port))
            print("目的地址{0}，目的端口{1}，seq{2}".format(self.dest_address, self.dest_port, header.seq_num))
        finally:
            if self.lock:
                self.lock.release()

    # 输出状态
    def print_state(self):
        print("\n", self.header.ack, self.header.syn, self.header.fin, self.header.dat, self.header.end, self.header.cnt,
              self.header.operation, self.header.window_size, self.header.chekcsum, self.header.error, self.get_tag,
              self.post_tag, self.error_tag, self.cnt_tag, "\n")

    def reset(self):
        self.header.ack = False
        self.header.syn = False
        self.header.fin = False
        self.header.dat = False
        self.header.end = False
        self.header.cnt = False
        self.header.operation = False
        self.header.error = 0
        self.get_tag = 0
        self.post_tag = 0
        self.error_tag = 0
        self.cnt_tag = 2

    # 计算校验和
    @staticmethod
    def checksum_help(packet):
        packet_len = len(packet)
        # 校验和需要16bit的整数来计算，所以必须是2的倍数的字节
        tag = 0 if packet_len % 2 == 0 else 2
        checksum = 0
        for i in range(packet_len // 2):
            checksum += (packet[i * 2] << 8 | packet[i * 2 + 1])
        if tag == 1:
            checksum += packet[packet_len - 1]
        checksum = checksum % 65535
        return checksum

    # 验证校验和
    @staticmethod
    def check_checksum(packet):
        checksum = packet[14] << 8 | packet[15]
        packet[14], packet[15] = 0, 0
        return checksum == Connection.checksum_help(packet)


# 一个端口的监听，TCP服务器
# 拥有属性：
#   host_address: 本机地址
#   host_port: 本地端口
#   socket: 用户监听的socket
#   lock: 线程锁
#   threads: 多个连接用户，每个用户的标识是(address, port)，是connection的字典
class TCPServer:

    def __init__(self, host_address, host_port):
        self.host_address, self.host_port = host_address, host_port
        self.socket = socket(AF_INET, SOCK_DGRAM)
        self.socket.bind((self.host_address, self.host_port))
        self.lock = threading.Lock()
        self.threads = dict()

    # 开始接收报文了
    def listen(self, event):
        print("开始接收")
        while True and not event.stopped():
            try:
                data, address = self.socket.recvfrom(1024)
            except IOError:
                continue
            packet = bytearray(data)
            # 验证校验和
            if Connection.check_checksum(packet):
                # 依据header_len取出header
                header = Header()
                header.header_from_bytes(packet[:packet[12] & 0xFF])
                connection_key = address[0] + "/" + str(address[1])
                if connection_key not in self.threads.keys():
                    print("新用户", connection_key)
                    connection = Connection(False, address[0], address[1], self.socket)
                    connection.set_lock(self.lock)
                    self.threads[connection_key] = connection
                # 处理packet
                self.threads[connection_key].deal_with_packet(packet, header)
            else:
                print(packet)
                print("报文损毁，丢弃")


# TCP客户端，可以connect，get file, post file，继承于Connection
# 拥有属性：
#   host_address: 本机地址
#   host_port: 本地端口
#   socket: socket
class TCPClient(Connection):

    def __init__(self, host_address, host_port, dest_address, dest_port):
        self.host_address = host_address
        self.host_port = host_port
        self.socket = socket(AF_INET, SOCK_DGRAM)
        self.socket.bind((self.host_address, self.host_port))
        super(TCPClient, self).__init__(True, dest_address, dest_port, self.socket)
        self.header.source_port = host_port

    # 开始连接，三次握手中的客户端的两次send
    def connect(self):
        print("开始连接")
        self.header.cnt, self.header.syn = True, True
        self.header.seq_num = 0
        self.send_cnt(0, "客户端：建立连接 —— 发送 SYN = 1 报文", "客户端：建立连接 —— 重传 SYN = 1 报文")
        self.header.syn = False
        self.header.seq_num = 1
        self.send_cnt(1, "客户端：建立连接 —— 发送 SYN = 0 报文", "客户端：建立连接 —— 重传 SYN = 0 报文")
        self.header.cnt = False
        self.print_state()
        # print("客户端：连接建立成功", "/" * 100, sep="\n")

    # 结束连接，四次挥手中客户端的两次send
    def close(self):
        print("结束连接")
        self.header.cnt, self.header.fin = True, True
        self.header.seq_num = 0
        self.send_cnt(2, "客户端：结束连接 —— 发送 FIN = 1 的报文", "客户端：结束连接 —— 重传 FIN = 1 的报文")
        self.header.fin = False
        self.header.seq_num = 1
        self.send_cnt(3, "客户端：结束连接 —— 发送 FIN = 0 的报文", "客户端：结束连接 —— 重传 FIN = 0 的报文")
        # 其实我觉得None可能更好
        self.header = False
        # print("客户端：连接结束成功", "/" * 100, sep="\n")

    def listen(self, event):
        print("开始接收")
        while True and not event.stopped():
            try:
                data, address = self.socket.recvfrom(1024)
            except IOError:
                continue
            packet = bytearray(data)
            # 验证校验和
            if Connection.check_checksum(packet):
                # 依据header_len取出header
                header = Header()
                header.header_from_bytes(packet[:packet[12] & 0xFF])
                self.deal_with_packet(packet, header)
            else:
                print(packet)
                print("报文损毁，丢弃")

