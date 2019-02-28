# coding:UTF-8
from time import time


class TTLTimer:

    def __init__(self):
        # 计时、默认超时时间
        self.time = 0
        self.time_out = 0.5

    # 开始计时(重新开始计时)
    def start(self):
        self.time = time()

    # 用于进行流控制，根据RTT设置超时时间
    def set_timeout(self, time_out):
        self.time_out = time_out

    def get_time(self):
        return self.time - time()

    # 判断是否超时
    def is_timeout(self):
        return time() - self.time >= self.time_out


class Window:

    # 窗口大小、开始位置、结束位置、下一个将要被发送的(？？？)
    def __init__(self):
        self.window_size = 5
        self.start_window = 0
        self.end_window = self.window_size - 1
        self.next_send = 0

    def set_window_size(self, window_size):
        self.window_size = window_size

    def get_window_size(self):
        return self.window_size


class Header:

    # 纯正tcp报文结构：
    #   源端口号(2byte)、目的端口号(2byte)、序号(4byte)、确认号(4byte)
    #   首部长度(4bit)、保留未用(2bit)
    #   6bit标志位：ack、rst、syn、fin、psh、urg
    #   接受窗口(2byte)、因特网校验和(2byte)、紧急数据指针(2byte)
    # 保留未用哪里与6bit标志位作为8个标志位：fin/syn/cnt/dat/ack/end/operation/None(bit顺序从低位到高位)
    # 紧急数据指针被拆分，1byte为error(错误标记)、1byte为接受窗口
    # 然后后面的才是：
    #   选项
    #   数据
    def __init__(self):
        self.source_port = 0
        self.dest_port = 0
        self.seq_num = 0
        self.ack_num = 0
        self.header_len = 20
        self.fields_len = 0
        # 下面八个bool类型的字段都是同一个byte的，只是属于不同的bit，分别代表
        # ack确认报文、syn初始化连接、fin结束连接
        # data数据报文、end报文(确认数据包完整)、cnt请求报文(请求数据)
        # get形式的数据/post形式的数据的指令操作
        self.ack, self.syn, self.fin = False, False, False
        self.dat, self.end, self.cnt = False, False, False
        self.operation = False
        self.window_size = 0
        self.chekcsum = 0
        self.error = 0
        # 真正存储报文信息的地方，将上面的各个属性变为字节放入byte array中
        self.header = bytearray(20)

    def print_header(self):
        print(self.ack, self.syn, self.fin, self.dat, self.end, self.cnt, self.operation, self.window_size, self.error)
        print(self.source_port, self.dest_port)

    # 将十进制转化为字节流
    def set_header(self):
        # 源端口号与目的端口号
        self.header[0], self.header[1] = (self.source_port >> 8) & 0xFF, self.source_port & 0xFF
        self.header[2], self.header[3] = (self.dest_port >> 8) & 0xFF, self.dest_port & 0xFF
        # 序号
        self.header[4], self.header[5] = (self.seq_num >> 24) & 0xFF, (self.seq_num >> 16) & 0xFF
        self.header[6], self.header[7] = (self.seq_num >> 8) & 0xFF, self.seq_num & 0xFF
        # 确认号
        self.header[8], self.header[9] = (self.ack_num >> 24) & 0xFF, (self.ack_num >> 16) & 0xFF
        self.header[10], self.header[11] = (self.ack_num >> 8) & 0xFF, self.ack_num & 0xFF
        # 首部长度
        self.header[12] = self.header_len & 0xFF
        # 标记字段
        self.header[13] = 0
        if self.fin:
            self.header[13] = 0x1 | self.header[13]
        if self.syn:
            self.header[13] = 0x2 | self.header[13]
        if self.cnt:
            self.header[13] = 0x4 | self.header[13]
        if self.dat:
            self.header[13] = 0x8 | self.header[13]
        if self.ack:
            self.header[13] = 0x10 | self.header[13]
        if self.end:
            self.header[13] = 0x20 | self.header[13]
        if self.operation:
            self.header[13] = 0x40 | self.header[13]
        # 校验和
        self.header[14], self.header[15] = (self.chekcsum >> 24) & 0xFF, (self.chekcsum >> 16) & 0xFF
        # 错误提示
        self.header[16] = self.error & 0xFF
        # 接受窗口
        self.header[17] = (self.window_size >> 16) & 0xFF
        self.header[18] = (self.window_size >> 8) & 0xFF
        self.header[19] = self.window_size & 0xFF
        return self.header

    # 将字节流转换为十进制
    def header_from_bytes(self, header):
        # 译码过程
        self.source_port = header[0] << 8 | header[1]
        self.dest_port = header[2] << 8 | header[3]
        self.seq_num = header[4] << 24 | header[5] << 16 | header[6] << 8 | header[7]
        self.ack_num = header[8] << 24 | header[9] << 16 | header[10] << 8 | header[11]
        # 功能码翻译
        if header[13] & 0x1 == 0x1:
            self.fin = True
        if header[13] & 0x2 == 0x2:
            self.syn = True
        if header[13] & 0x4 == 0x4:
            self.cnt = True
        if header[13] & 0x8 == 0x8:
            self.dat = True
        if header[13] & 0x10 == 0x10:
            self.ack = True
        if header[13] & 0x20 == 0x20:
            self.end = True
        if header[13] & 0x40 == 0x40:
            self.operation = True
        # 窗口以及检验和
        self.checksum = header[14] << 8 | header[15]
        self.error = header[16]
        self.window_size = header[17] << 16 | header[18] << 8 | header[19]
        self.header = header

    def get_header(self):
        return self.set_header()

    def set_header_from_bytes(self, header):
        self.header = header

