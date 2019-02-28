from time import time
import os, math, random
from numpy import *


# 计时器
# 提供缓存与发送速率
class Timer:
    def __init__(self):
        self.time = 0
        # 定义一个
        self.time_out = 0.1

    def start(self):
        self.time = time()

    def is_time_out(self):
        if time() - self.time > self.time_out:
            return True
        else:
            return False

    # 缓存超时时进行超时翻倍以及重新计时
    def buffer_reset_time_out(self):
        # 翻倍
        self.time_out = self.time_out * 2
        # 重新开始
        self.start()

    # 预留
    # 设置超时时间
    def set_time_out(self, new_time_out):
        self.time_out = new_time_out


# 缓存类
class Buffer:
    def __init__(self, seq_num, data):
        # 每一个缓存的序列号
        self.seq_num = seq_num
        # 每一个缓存的数据
        self.data = data
        # 计时器
        self.timer = Timer()

    # 判断是否超时
    def is_time_out(self):
        return self.timer.is_time_out()

    # 超时 时调用
    # 进行重传
    def re_transmission(self):
        self.timer.buffer_reset_time_out()

    # 手动开启时间
    # 第一次发送的时候使用
    def start(self):
        # 创建的时候顺便开始计时
        self.timer.start()


# 发送窗口
# 使用TCP的控制，GBN+SR
# 每次重新发文件就开一个新的SendWindow
class SendWindow:
    # 传入文件名用于打开文件并更新

    def __init__(self, filename):
        # list存储
        self.buffers = []
        # 缓存空间的最大长度
        self.windows_size = 40
        # 每次读取文件的最大长度
        # 限制每一个buffer的长度
        self.read_len = 1000
        # 保存文件名
        self.filename = filename
        # 打开文件，后面用于更新缓存
        self.readfile = open(filename, "rb")
        # 用于拥塞控制，虚拟的窗口大小，可以是小数，使用的时候注意取整
        self.cwnd = 1
        # ssthresh 用于控制cwnd的阈值
        self.ssthresh = 64
        # 用于存储当前全部创建的序列号
        self.seq_num = 0

        self.least_not_send = 0
        # 创建初始缓存
        for i in range(self.windows_size):
            # 判断是否为空
            data = self.readfile.read(self.read_len)
            if data == b'':
                break
            self.buffers.append(Buffer(self.seq_num, data))
            self.seq_num += 1

    # 返回需要确认的序号
    # -1表示传输完成
    def least_not_ack(self):
        if not len(self.buffers) == 0:
            try:
                return self.buffers[0].seq_num
            except Exception as e:
                return -1
        return -1

    # 更新操作
    # 三次的重传在上一层实现，不正确的ACK不要进入这里
    # 三次重传调用get_buffer实现
    # 小于数字的都弹出，并且压入新的数据
    # 返回是否传完
    def ack_and_renew(self, seq_num):
        # 删除已经ack的buffer
        while len(self.buffers) > 0:
            #  ??????要不要<=???
            if self.buffers[0].seq_num <= seq_num:
                self.buffers.pop(0)
            else:
                break
        # 插入新的元素
        while len(self.buffers) < self.windows_size:
            data = self.readfile.read(self.read_len)
            if data == b'':
                break
            self.buffers.append(Buffer(self.seq_num, data))
            self.seq_num += 1
        if len(self.buffers) == 0:
            return True
        else:
            return False

    # 通过序列号获得对应的buffer
    # 返回的是Buffer类型
    def get_buffer(self, seq_num):
        # 获取缓存对应的索引
        index = seq_num - self.buffers[0].seq_num
        return self.buffers[index]

    # 用于快速重传以及更新cwnd
    # current_state:表示的是当前的状态
    #           slow 包含congestion
    #           quick
    # new_ack：
    #           1， 表示新的ack
    # duplicate_ack:
    #           num: 表示序列号
    # dupack_count：
    #           <3,
    #           ==3, 慢启动/拥塞控制->快速重传
    #           >3, 继续快速重传
    # time_out:
    #           0,  表示未超时
    #           > 1， 表示超时
    #           len(get_time_out_buffers)
    # 返回当前需要发送的分组
    def quick_update_cwnd(self, current_state, new_ack=-1, duplicate_ack=None, dupack_count=0, time_out=0):
        # 超时,不返回数组
        # 超时
        if not time_out == 0:
            if not self.cwnd == 1:
                self.ssthresh = self.cwnd // 2
                self.cwnd = 1
        elif current_state == "slow" and (not duplicate_ack == None) and dupack_count < 3:
            # 外部处理
            pass
        # 返回多次冗余的分组
        elif current_state == "slow" and (not duplicate_ack == None) and dupack_count == 3:
            if self.cwnd >= 2:
                self.ssthresh = self.cwnd // 2
                self.cwnd = self.ssthresh + 3
            else:
                self.ssthresh = self.cwnd
                self.cwnd = self.ssthresh + 3
            # ???是否要+1
            print("发送窗口cwnd：", self.cwnd, "发送窗口ssthresh :", self.ssthresh)
            return self.get_buffer(duplicate_ack + 1)
        # 接收到新的ack，重新传输新的分组
        elif current_state == "slow" and not new_ack == -1:
            # 慢启动
            if self.cwnd < self.ssthresh <= self.windows_size:
                self.cwnd += 1
            # 拥塞控制
            elif self.ssthresh <= self.cwnd < self.windows_size:
                self.cwnd += (1 / self.cwnd)
        elif current_state == "quick" and (not duplicate_ack == None):
            # 快速恢复
            if self.cwnd <= self.windows_size:
                self.cwnd += 1
            # ???是否要+1
            print("发送窗口cwnd：", self.cwnd, "发送窗口ssthresh :", self.ssthresh)
            return self.get_buffer(duplicate_ack + 1)
        print("发送窗口cwnd：", self.cwnd, "发送窗口ssthresh :", self.ssthresh)

    # TTL过后需要进行发送的分组
    # 返回None表示发送结束
    # 返回[]表示所有的数据都在wait ack
    # 返回需要发送的分组
    def get_buffers(self):
        if len(self.buffers) == 0:
            return None
        # 表示全部的数据都处于wait ack的状态中
        try:
            if self.least_not_send > self.buffers[-1].seq_num:
                return []
            # 与缓存最后的seq_num比较
            elif self.least_not_send + math.floor(self.cwnd) - 1 > self.buffers[-1].seq_num:
                # 存储b需要发送的buffer
                buffers = self.buffers[self.least_not_send - self.buffers[0].seq_num:]
                # 启动计时器
                for buffer in buffers:
                    buffer.start()
                self.least_not_send = self.buffers[-1].seq_num + 1
                return buffers
            elif self.least_not_send + math.floor(self.cwnd) - 1 <= self.buffers[-1].seq_num:
                # 存储需要发送的buffers
                buffers = self.buffers[self.least_not_send - self.buffers[0].seq_num: self.least_not_send - self.buffers[
                    0].seq_num + math.floor(self.cwnd)]
                # 启动计时器
                for buffer in buffers:
                    buffer.start()
                self.least_not_send = self.least_not_send + math.floor(self.cwnd)
                return buffers
        except Exception as e:
            return None

    # 获取超时分组在外部进行重传
    def get_time_out_buffers(self):
        try:
            resent_buffers = []
            if len(self.buffers) > 0:
                wait_buffers = self.buffers[0: self.least_not_send - self.buffers[0].seq_num]
                for i in wait_buffers:
                    if i.is_time_out():
                        resent_buffers.append(i)
                        # 超时时间重置
                        i.re_transmission()
                return resent_buffers
        except Exception as e:
            print("Buffer get_time_out_buffers 出错")
        return []


# 接受窗口
class ReceiveWindow:
    def __init__(self, filename):
        self.buffers = {}
        # 缓存字典
        self.windows_size = 30
        # 窗口的大小
        self.not_get = []
        # 序列数组
        self.not_get.append(0)
        # 当前窗口大小
        self.current_window = 0
        # 保存文件名
        self.filename = filename
        # 输出
        self.writefile = open(filename, "wb")
        # 写的大小
        self.write_len = 5

    # 传入接收到的序列号与数据
    # 返回ACK， 窗口大小， 以及是否结束传输
    # 真正传输完成：tag == 1 and len(self.not_get) == 1 成立
    # tag表示发送文件是否结束，如果结束则为1
    def return_message(self, seq_num, data, tag=0):
        # 是期待的数据的时候
        # 以下是测试的时候用的，用于终止
        # if self.not_get[0] == 111:
        #     self.write(1)
        #     tag = 1
        #     return seq_num, self.windows_size - len(self.buffers), tag == 1 and len(self.not_get) == 1

        if seq_num == self.not_get[0] and len(self.buffers) + len(self.not_get) < self.windows_size:
            # 一直维护一个最后的元素表示期待的
            if len(self.not_get) == 1:
                self.not_get.pop(0)
                self.not_get.append(seq_num + 1)
                self.buffers[seq_num] = data
            else:
                self.not_get.pop(0)
                self.buffers[seq_num] = data
            self.write(tag)
            print("接受窗口当前缓存大小：", len(self.buffers), "接受窗口期望数组的大小：", len(self.not_get), "期望0元素", self.not_get[0])
            return seq_num, self.windows_size - len(self.buffers), tag == 1 and len(self.not_get) == 1
        # 小于 最小的期待的时候，直接返回
        elif seq_num < self.not_get[0]:
            self.write(tag)
            print("接受窗口当前缓存大小：", len(self.buffers), "接受窗口期望数组的大小：", len(self.not_get), "期望0元素", self.not_get[0])
            return seq_num, self.windows_size - len(self.buffers), tag == 1 and len(self.not_get) == 1
        elif seq_num > self.not_get[0]:
            # 如果是自己所期待的并且不是最后一个元素
            if seq_num in self.not_get and seq_num != self.not_get[-1]:
                self.not_get.remove(seq_num)
                self.buffers[seq_num] = data
            # 等于最后一个元素
            elif seq_num == self.not_get[-1] and len(self.not_get) + len(self.buffers) + 1 < self.windows_size:
                self.not_get.remove(seq_num)
                self.not_get.append(seq_num + 1)
                self.buffers[seq_num] = data
            # 不在期待的数组中并且数值比一个期待元素大。意味者比最大的元素还大
            elif len(self.not_get) + len(self.buffers) + seq_num - self.not_get[-1] + 1 < self.windows_size and seq_num > self.not_get[-1]:
                for i in range(seq_num - self.not_get[-1] - 1):
                    self.not_get.append(self.not_get[-1] + 1)
                self.not_get.append(seq_num + 1)
                self.buffers[seq_num] = data
                # self.windows_size
            else:
                # 丢弃
                pass
            # 调用写方法
            self.write(tag)
            print("接受窗口当前缓存大小：", len(self.buffers), "接受窗口期望数组的大小：", len(self.not_get), "期望0元素", self.not_get[0])
            return self.not_get[0] - 1, self.windows_size - len(self.buffers), tag == 1 and len(self.not_get) == 1
        else:
            self.write(tag)
            print("接受窗口当前缓存大小：", len(self.buffers), "接受窗口期望数组的大小：", len(self.not_get), "期望0元素", self.not_get[0])
            return self.not_get[0] - 1, self.windows_size - len(self.buffers), tag == 1 and len(self.not_get) == 1

    # tag用于表示是否结束，结束表示为1，立刻写入
    # 当有效的缓存大于10的时候自动写入
    def write(self, tag=0):
        if tag == 1 and len(self.not_get) == 1:
            if len(self.buffers) > 0:
                index = min(self.buffers.keys())
                length = len(self.buffers)
                for i in range(length):
                    # self.writefile.write(bytearray("\n序号是" + str(index + i) + "\n", encoding="utf-8"))
                    self.writefile.write(self.buffers[index + i])
                    del self.buffers[index + i]
            self.writefile.close()
        elif len(self.buffers) != 0 and self.not_get[0] - min(self.buffers.keys()) > self.write_len :
            index = min(self.buffers.keys())
            for i in range(self.write_len):
                # self.writefile.write(bytearray("\n序号是" + str(index + i) + "\n", encoding="utf-8"))
                self.writefile.write(self.buffers[index + i])
                self.writefile.flush()
                del self.buffers[index + i]


if __name__ == '__main__':
    receive_window = ReceiveWindow("./server_files/test2.txt")
    read_file = open("./client_files/test2.txt", "rb")
    length = 1000
    buffers = {}
    seq_num = 0
    while True:
        data = read_file.read(length)
        if data == b"":
            break
        else:
            buffers[seq_num] = data
            seq_num += 1
    indexs_seq = array([i for i in range(len(buffers))])
    random.shuffle(indexs_seq)
    tag = False
    index = 0
    print(indexs_seq)
    print(len(indexs_seq))
    while tag == False:
        for i in range(len(indexs_seq)):
            a, b, tag = receive_window.return_message(indexs_seq[i], buffers[indexs_seq[i]])
            print(a, b, tag)
            if tag == True:
                break
        print("*" *100)