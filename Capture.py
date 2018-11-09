# -*- coding: utf-8 -*-
""" 抓包 """
import tempfile
import time
from os import getcwd
from threading import Event, Thread

from PyQt5.QtWidgets import QFileDialog, QMessageBox
from scapy.compat import raw
from scapy.layers.inet import *
from scapy.layers.inet6 import *
from scapy.layers.l2 import Ether
from scapy.sendrecv import sniff
from scapy.utils import *

# arp字典
arp_dict = {
    1: "who-has",
    2: "is-at",
    3: "RARP-req",
    4: "RARP-rep",
    5: "Dyn-RARP-req",
    6: "Dyn-RAR-rep",
    7: "Dyn-RARP-err",
    8: "InARP-req",
    9: "InARP-rep"
}
# icmpv6 code字典
icmpv6_code = {
    1: {
        0: "No route to destination",
        1: "Communication with destination administratively prohibited",
        2: "Beyond scope of source address",
        3: "Address unreachable",
        4: "Port unreachable"
    },
    3: {
        0: "hop limit exceeded in transit",
        1: "fragment reassembly time exceeded"
    },
    4: {
        0: "erroneous header field encountered",
        1: "unrecognized Next Header type encountered",
        2: "unrecognized IPv6 option encountered"
    },
}
# 端口字典
ports = {
    80: "HTTP",
    443: "HTTPS",
    1900: "SSDP",
    53: "DNS",
    123: "NTP",
    23: "Telnet",
    21: "FTP",
    20: "FTP_data",
    22: "SSH",
    25: "SMTP",
    110: "POP3",
    143: "IMAP",
    161: "SNMP",
    69: "TFTP"
}


class Core:
    """ 抓包后台类 """
    # 抓到的包编号从1开始
    packet_id = 1
    # 抓到的包的列表
    packet_list = []
    # 网卡的信息,
    netcard = None
    # 开始标志
    start_flag = False
    # 暂停标志
    pause_flag = False
    # 停止标志
    stop_flag = False
    # 保存标志
    save_flag = False
    # 窗口
    main_window = None
    # 停止抓包的线程
    stop_capturing_thread = Event()
    # 抓包过滤条件，遵BPF规则
    filters = None
    # 开始时间戳
    start_timestamp = None
    # 存放等待显示在抓包列表的数据包信息
    row_to_add = []
    temp_file = None
    writer = None

    def updating_thread(self):
        """
        更新抓包列表的线程函数
        """
        start_time = time.time()
        while True:
            time.sleep(0.001)
            row = []
            try:
                row = self.row_to_add.pop(0)
                # 放置更新表格函数，传入列表details
                self.main_window.add_tableview_row(row)
                end_time = time.time()
                # 每1.5s聚焦到最后一行
                if (end_time -
                        start_time) > 2 and self.main_window.notSelected:
                    self.main_window.info_tree.scrollToBottom()
                    start_time = end_time
            except IndexError:
                pass

    def __init__(self, mainwindow):
        """
        初始化, 若不设置netcard则为捕捉所有网卡的数据包
        :parma mainwindow: 传入主窗口
        """
        self.main_window = mainwindow
        _, self.temp_file = tempfile.mkstemp(
            suffix=".pcap", prefix=str(int(time.time())))
        self.writer = PcapWriter(self.temp_file, append=True, sync=True)
        print(self.temp_file)
        thread = Thread(
            target=self.updating_thread, daemon=True, name="updating_thread")
        thread.start()

    def process_packet(self, packet):
        """
        处理抓到的数据包
        :parma packet: 需要处理分类的包
        """
        # 如果暂停，则不对列表进行更新操作
        if self.pause_flag is False and packet.name == "Ethernet":
            details = []
            # 第一次开始或者停止后开始, 暂停后开始packet_id!=1
            if self.packet_id == 1:
                self.start_timestamp = packet.time
            packet_time = packet.time - self.start_timestamp
            #第二层
            ether_type = packet.payload.name
            version_add = ""
            # IPv4
            if ether_type == "IP":
                source = packet[IP].src
                destination = packet[IP].dst
            # IPv6
            elif ether_type == "IPv6":
                source = packet[IPv6].src
                destination = packet[IPv6].dst
                version_add = "v6"
            # ARP
            elif ether_type == "ARP":
                protocol = ether_type
                source = packet[Ether].src
                destination = packet[Ether].dst
                if destination == "ff:ff:ff:ff:ff:ff":
                    destination = "Broadcast"
            else:
                # 其他协议不处理
                return
            if ether_type != "ARP":
                protocol = packet.payload.payload.name
                sport = None
                dport = None
                if protocol == "TCP":
                    sport = packet[TCP].sport
                    dport = packet[TCP].dport
                elif protocol == "UDP":
                    sport = packet[UDP].sport
                    dport = packet[UDP].dport
                elif len(protocol) >= 4 and protocol[0:4] == "ICMP":
                    protocol = "ICMP"
                    protocol += version_add
                else:
                    return
                if sport is not None and dport is not None:
                    if sport in ports:
                        protocol = ports[sport] + version_add
                    elif dport in ports:
                        protocol = ports[dport] + version_add

            details.append(str(self.packet_id))
            details.append(str((packet_time))[:9])
            details.append(source)
            details.append(destination)
            details.append(protocol)
            details.append(str(len(packet)))
            info = packet.summary()
            details.append(info)
            # 将需要显示的包放进字典中
            self.row_to_add.append(details)
            # 将抓到的包存在列表中
            self.packet_list.append(packet)
            self.packet_id += 1
            #self.writer.write(packet)

    def on_click_item(self, this_id):
        """
        处理点击列表中的项
        :parma this_id: 包对应的packet_id，在packet_list里获取该packet
        """
        packet = self.packet_list[this_id]
        # 详细信息列表, 用于添加进GUI
        first_return = []
        second_return = []
        # 第一层: Frame
        first_layer = []
        # 抓包的长度
        packet_len = str(len(packet)) + " bytes (" + \
            str(len(packet) << 3) + " bits)"
        frame = ("Frame " + str(this_id) + ": " + packet_len + " captured" + (
            (" on " + self.netcard) if self.netcard is not None else ""))
        first_return.append(frame)
        # 抓包的时间
        first_layer.append("Arrival Time: " + self.time_to_formal(packet.time))
        first_layer.append("Epoch Time: " + str(packet.time) + " seconds")
        previous_packet_time = self.packet_list[this_id -
                                                1].time if this_id > 0 else 0
        delta_time = packet.time - previous_packet_time
        first_layer.append("[Time delta from previous captured frame: " +
                           str(delta_time) + " seconds]")
        delta_time = packet.time - self.start_timestamp
        first_layer.append("[Time since first frame: " + str(delta_time) +
                           " seconds]")
        first_layer.append("Frame Number: " + str(this_id))
        first_layer.append("Capture Length: " + str(packet_len))
        # 添加第一层信息到二维列表中
        second_return.append(first_layer)
        first_temp, second_temp = self.get_next_layer(packet)
        first_return += first_temp
        second_return += second_temp
        return first_return, second_return

    def get_next_layer(self, packet):
        """
        递归处理下一层信息
        :parma packet: 处理来自上一层packet的payload
        """
        # 第二层: Ethernet
        first_return = []
        second_return = []
        next_layer = []
        protocol = packet.name
        packet_class = packet.__class__
        if protocol == "NoPayload":
            return first_return, second_return
        elif protocol == "Ethernet":
            ether_src = packet[packet_class].src
            ether_dst = packet[packet_class].dst
            if ether_dst == "ff:ff:ff:ff:ff:ff":
                ether_dst = "Broadcast (ff:ff:ff:ff:ff:ff)"
            ethernet = "Ethernet, Src: " + ether_src + ", Dst: " + ether_dst
            first_return.append(ethernet)
            next_layer.append("Source: " + ether_src)
            next_layer.append("Destination: " + ether_dst)
            ether_type = packet.payload.name
            if ether_type == "IP":
                ether_type += "v4"
            ether_proto = (
                "Type: " + ether_type + " (" + hex(packet[packet_class].type) + ")")
            next_layer.append(ether_proto)
        # 第三层: 网络层
        # IPv4
        elif protocol == "IP" or protocol == "IP in ICMP":
            protocol += "v4"
            ip_src = packet[packet_class].src
            ip_dst = packet[packet_class].dst
            network = "Internet Protocol Version 4, Src: "
            network += ip_src + ", Dst: " + ip_dst
            first_return.append(network)
            next_layer.append("Version: " + str(packet[packet_class].version))
            next_layer.append("Header Length: " + str(packet[packet_class].ihl << 2) +
                              " bytes (" + str(packet[packet_class].ihl) + ")")
            next_layer.append("Differentiated Services Field: " +
                              hex(packet[packet_class].tos))
            next_layer.append("Total Length: " + str(packet[packet_class].len))
            next_layer.append("Identification: " + hex(packet[packet_class].id) + " (" +
                              str(packet[packet_class].id) + ")")
            next_layer.append("Flags: " + str(packet[packet_class].flags) + " (" +
                              hex(packet[packet_class].flags.value) + ")")
            next_layer.append("Fragment offset: " + str(packet[packet_class].frag))
            next_layer.append("Time to live: " + str(packet[packet_class].ttl))
            next_protocol = packet.payload.name
            if next_protocol == "IP":
                next_protocol += "v4"
            next_layer.append("Protocol: " + next_protocol + " (" +
                              str(packet[packet_class].proto) + ")")
            ip_chksum = packet[packet_class].chksum
            ip_check = packet_class(raw(packet[packet_class])).chksum
            next_layer.append("Header checksum: " + hex(ip_chksum))
            next_layer.append("[Header checksum status: " + "Correct]"
                              if ip_check == ip_chksum else "Incorrect]")
            next_layer.append("Source: " + ip_src)
            next_layer.append("Destination: " + ip_dst)
        # IPv6
        elif protocol == "IPv6" or protocol == "IPv6 in ICMPv6":
            ipv6_src = packet[packet_class].src
            ipv6_dst = packet[packet_class].dst
            network = ("Internet Protocol Version 6, Src: " + ipv6_src +
                       ", Dst: " + ipv6_dst)
            first_return.append(network)
            next_layer.append("Version: " + str(packet[packet_class].version))
            next_layer.append("Traffice Class: " + hex(packet[packet_class].tc))
            next_layer.append("Flow Label: " + hex(packet[packet_class].fl))
            next_layer.append("Payload Length: " + str(packet[packet_class].plen))
            next_protocol = packet.payload.name
            if next_protocol == "IP":
                next_protocol += "v4"
            next_layer.append("Next Header: " + next_protocol + " (" +
                              str(packet[packet_class].nh) + ")")
            next_layer.append("Hop Limit: " + str(packet[packet_class].hlim))
            next_layer.append("Source: " + ipv6_src)
            next_layer.append("Destination: " + ipv6_dst)
        elif protocol == "ARP":
            arp_op = packet[packet_class].op
            network = "Address Resolution Protocol"
            if arp_op in arp_dict:
                network += " (" + arp_dict[arp_op] + ")"
            first_return.append(network)
            next_layer.append("Hardware type: " + "Ethernet (" if packet[packet_class].
                              hwtype == 1 else "(" + packet[packet_class].hwtype + ")")
            ptype = packet[packet_class].ptype
            temp_str = "Protocol type: " + hex(packet[packet_class].ptype)
            if ptype == 0x0800:
                temp_str += " (IPv4)"
            elif ptype == 0x86DD:
                temp_str += " (IPv6)"
            next_layer.append(temp_str)
            next_layer.append("Hardware size: " + str(packet[packet_class].hwlen))
            next_layer.append("Protocol size: " + str(packet[packet_class].plen))
            temp_str = "Opcode: " + str(arp_op)
            if arp_op in arp_dict:
                temp_str += " (" + arp_dict[arp_op] + ")"
            next_layer.append(temp_str)
            next_layer.append("Sender MAC address: " + packet[packet_class].hwsrc)
            next_layer.append("Sender IP address: " + packet[packet_class].psrc)
            next_layer.append("Target MAC address: " + packet[packet_class].hwdst)
            next_layer.append("Target IP address: " + packet[packet_class].pdst)
        # 第四层: 传输层
        elif protocol == "TCP" or protocol == "TCP in ICMP":
            src_port = packet[packet_class].sport
            dst_port = packet[packet_class].dport
            transport = ("Transmission Control Protocol, Src Port: " +
                         str(src_port) + ", Dst Port: " + str(dst_port))
            first_return.append(transport)
            next_layer.append("Source Port: " + str(src_port))
            next_layer.append("Destination Port: " + str(dst_port))
            next_layer.append("Sequence number: " + str(packet[packet_class].seq))
            next_layer.append("Acknowledgment number: " + str(packet[packet_class].ack))
            tcp_head_length = packet[packet_class].dataofs
            next_layer.append("Header Length: " + str(tcp_head_length << 2) +
                              " bytes (" + str(tcp_head_length) + ")")
            next_layer.append("Flags: " + hex(packet[packet_class].flags.value) + " (" +
                              str(packet[packet_class].flags) + ")")
            next_layer.append("Window size value: " + str(packet[packet_class].window))
            tcp_chksum = packet[packet_class].chksum
            tcp_check = packet_class(raw(packet[packet_class])).chksum
            next_layer.append("Checksum: " + hex(tcp_chksum))
            next_layer.append("[Checksum status: " + "Correct]" if tcp_check ==
                              tcp_chksum else "Incorrect]")
            next_layer.append("Urgent pointer: " + str(packet[packet_class].urgptr))
            options = packet[packet_class].options
            options_length = len(options) << 2
            if options_length > 0:
                string = "Options: (" + str(options_length) + " bytes), "
                for item in options:
                    string += item[0] + ": " + str(item[1]) + " "
                next_layer.append(string)

            payload_length = len(packet.payload)
            if payload_length > 0:
                next_layer.append("TCP payload: " + str(payload_length) +
                                  " bytes")
        elif protocol == "UDP" or protocol == "UDP in ICMP":
            src_port = packet[packet_class].sport
            dst_port = packet[packet_class].dport
            transport = ("User Datagram Protocol, Src Port: " + str(src_port) +
                         ", Dst Port: " + str(dst_port))
            first_return.append(transport)
            next_layer.append("Source Port: " + str(src_port))
            next_layer.append("Destination Port: " + str(dst_port))
            next_layer.append("Length: " + str(packet[packet_class].len))
            udp_chksum = packet[packet_class].chksum
            udp_check = packet_class(raw(packet[packet_class])).chksum
            next_layer.append("Chksum: " + hex(udp_chksum))
            next_layer.append("[Checksum status: " + "Correct]" if udp_check ==
                              udp_chksum else "Incorrect]")
        elif protocol == "ICMP" or protocol == "ICMP in ICMP":
            transport = "Internet Control Message Protocol"
            first_return.append(transport)
            packet_type = packet[packet_class].type
            temp_str = "Type: " + str(packet_type)
            if packet_type in icmptypes:
                temp_str += " (" + icmptypes[packet_type] + ")"
            next_layer.append(temp_str)
            packet_code = packet[packet_class].code
            temp_str = "Code: " + str(packet_code)
            if packet_type in icmpcodes:
                if packet_code in icmpcodes[packet_type]:
                    temp_str += " (" + icmpcodes[packet_type][packet_code] + ")"
            next_layer.append(temp_str)
            icmp_chksum = packet[packet_class].chksum
            icmp_check = packet_class(raw(packet[packet_class])).chksum
            next_layer.append("Checksum: " + hex(icmp_chksum))
            next_layer.append("[Checksum status: " + "Correct]" if icmp_check
                              == icmp_chksum else "Incorrect]")
            next_layer.append("Identifier: " + str(packet[packet_class].id) + " (" +
                              hex(packet[packet_class].id) + ")")
            next_layer.append("Sequence number: " + str(packet[packet_class].seq) +
                              " (" + hex(packet[packet_class].seq) + ")")
            data_length = len(packet.payload)
            if data_length > 0:
                next_layer.append("Data (" + str(data_length) + " bytes): " +
                                  packet[packet_class].load.hex())
        elif len(protocol) >= 6 and protocol[0:6] == "ICMPv6":
            if protocol.lower().find("option") == -1:
                transport = "Internet Control Message Protocol v6"
                first_return.append(transport)
                proto_type = packet[packet_class].type
                temp_str = "Type: " + str(proto_type)
                if proto_type in icmp6types:
                    temp_str += " (" + icmp6types[proto_type] + ")"
                next_layer.append(temp_str)
                packet_code = packet[packet_class].code
                temp_str = "Code: " + str(packet_code)
                if proto_type in icmpv6_code:
                    if packet_code in icmpv6_code[proto_type]:
                        temp_str += " (" + icmpv6_code[proto_type][
                            packet_code] + ")"
                next_layer.append(temp_str)
                icmpv6_cksum = packet[packet_class].cksum
                icmpv6_check = packet_class(raw(packet[packet_class])).cksum
                next_layer.append("Checksum: " + hex(icmpv6_cksum))
                next_layer.append("[Checksum status: " +
                                  "Correct]" if icmpv6_check ==
                                  icmpv6_cksum else "Incorrect]")
                if proto_type == "Echo Request" or proto_type == "Echo Reply":
                    next_layer.append("Identifier: " +
                                      str(packet[packet_class].id) + " (" +
                                      hex(packet[packet_class].id) + ")")
                    next_layer.append("Sequence number: " +
                                      str(packet[packet_class].seq) + " (" +
                                      hex(packet[packet_class].seq) + ")")
                    data_length = packet[packet_class].plen - 8
                    if data_length > 0:
                        next_layer.append("Data (" + str(data_length) +
                                          " bytes): " +
                                          packet[packet_class].load.hex())
                elif proto_type == "Neighbor Advertisement":
                    temp_set = "Set (1)"
                    temp_not_set = "Not set (0)"
                    temp_str = "Router: "
                    if packet[packet_class].R == 1:
                        temp_str += temp_set
                    else:
                        temp_str += temp_not_set
                    next_layer.append(temp_str)
                    temp_str = "Solicited: "
                    if packet[packet_class].S == 1:
                        temp_str += temp_set
                    else:
                        temp_str += temp_not_set
                    next_layer.append(temp_str)
                    temp_str = "Override: "
                    if packet[packet_class].O == 1:
                        temp_str += temp_set
                    else:
                        temp_str += temp_not_set
                    next_layer.append(temp_str)
                    next_layer.append("Reserved: " +
                                      str(packet[packet_class].res))
                    next_layer.append("Target Address: " +
                                      packet[packet_class].tgt)
                elif proto_type == "Neighbor Solicitation":
                    next_layer.append("Reserved: " +
                                      str(packet[packet_class].res))
                    next_layer.append("Target Address: " +
                                      packet[packet_class].tgt)
                elif proto_type == "Router Solicitation":
                    next_layer.append("Reserved: " +
                                      str(packet[packet_class].res))
                elif proto_type == "Router Advertisement":
                    temp_set = "Set (1)"
                    temp_not_set = "Not set (0)"
                    next_layer.append("Cur hop limit: " +
                                      str(packet[packet_class].chlim))
                    temp_str = "Managed address configuration: "
                    if packet[packet_class].M == 1:
                        temp_str += temp_set
                    else:
                        temp_str += temp_not_set
                    next_layer.append(temp_str)
                    temp_str = "Other configuration: "
                    if packet[packet_class].O == 1:
                        temp_str += temp_set
                    else:
                        temp_str += temp_not_set
                    next_layer.append(temp_str)
                    temp_str = "Home Agent: "
                    if packet[packet_class].H == 1:
                        temp_str += temp_set
                    else:
                        temp_str += temp_not_set
                    next_layer.append(temp_str)
                    temp_str = "Preference: " + str(packet[packet_class].prf)
                    next_layer.append(temp_str)
                    temp_str = "Proxy: "
                    if packet[packet_class].P == 1:
                        temp_str += temp_set
                    else:
                        temp_str += temp_not_set
                    next_layer.append(temp_str)
                    next_layer.append("Reserved: " +
                                      str(packet[packet_class].res))
                    next_layer.append("Router lifetime (s): " +
                                      str(packet[packet_class].routerlifetime))
                    next_layer.append("Reachable time (ms): " +
                                      str(packet[packet_class].reachabletime))
                    next_layer.append("Retrans timer (ms): " +
                                      str(packet[packet_class].retranstimer))
                elif proto_type == "Destination Unreachable":
                    next_layer.append("Length: " +
                                      str(packet[packet_class].length) + " (" +
                                      hex(packet[packet_class].length) + ")")
                    next_layer.append("Unused: " +
                                      str(packet[packet_class].unused))
                elif proto_type == "Packet too big":
                    next_layer.append("MTU: " + str(packet[packet_class].mtu))
                elif proto_type == "Parameter problem":
                    next_layer.append("PTR: " + str(packet[packet_class].ptr))
                elif proto_type == "Time exceeded":
                    next_layer.append("Length: " +
                                      str(packet[packet_class].length) + " (" +
                                      hex(packet[packet_class].length) + ")")
                    next_layer.append("Unused: " +
                                      str(packet[packet_class].unused))
            else:
                # ICMPv6 Option
                transport = "ICMPv6 Option ("
                proto_type = packet[packet_class].type
                # Source Link-Layer or Destination Link-Layer
                if proto_type == 1 or proto_type == 2:
                    address = packet[packet_class].lladdr
                    if proto_type == 1:
                        transport += "Source Link-Layer Address: " + address + ")"
                        proto_type = "Type: Source Link-Layer Address (1)"
                    else:
                        transport += "Destination Link-Layer Address: " + address + ")"
                        proto_type = "Type: Destination Link-Layer Address (2)"
                    first_return.append(transport)
                    next_layer.append(proto_type)
                    length = packet[packet_class].len
                    next_layer.append("Length: " + str(length) + " (" +
                                      str(length << 3) + " bytes)")
                    next_layer.append("Link-Layer Address: " + address)
                # Prefix Information
                elif proto_type == 3:
                    packet_prefix = packet[packet_class].prefix
                    transport += "Prefix Information: " + packet_prefix + ")"
                    proto_type = "Type: Prefix Information (3)"
                    first_return.append(transport)
                    next_layer.append(proto_type)
                    length = packet[packet_class].len
                    next_layer.append("Length: " + str(length) + " (" +
                                      str(length << 3) + " bytes)")
                    next_layer.append("Prefix Length: " +
                                      str(packet[packet_class].prefixlen))
                    set_str = "Set (1)"
                    not_set_str = "Not set (0)"
                    next_layer.append("On-link flag (L): " +
                                      set_str if packet[packet_class].L ==
                                      1 else not_set_str)
                    next_layer.append(
                        "Autonomous address-configuration flag (A): " + set_str
                        if packet[packet_class].A == 1 else not_set_str)
                    next_layer.append("Router address flag(R): " +
                                      set_str if packet[packet_class].R ==
                                      1 else not_set_str)
                    next_layer.append("Valid Lifetime: " +
                                      str(packet[packet_class].validlifetime))
                    next_layer.append("Preferred Lifetime: " + str(
                        packet[packet_class].preferredlifetime))
                    next_layer.append("Reserverd: " +
                                      str(packet[packet_class].res2))
                    next_layer.append("Prefix: " + packet_prefix)
                # MTU
                elif proto_type == 5:
                    packet_mtu = packet[packet_class].mtu
                    transport += "MTU: " + str(packet_mtu) + ")"
                    proto_type = "Type: MTU (5)"
                    first_return.append(transport)
                    next_layer.append(proto_type)
                    length = packet[packet_class].len
                    next_layer.append("Length: " + str(length) + " (" +
                                      str(length << 3) + " bytes)")
                    next_layer.append("Reserverd: " +
                                      str(packet[packet_class].res))
                    next_layer.append("MTU: " + str(packet_mtu))
                else:
                    # 不识别，直接返回
                    return first_return, second_return
        # 第五层: 应用层
        elif protocol == "SSDP":
            pass
        if next_layer:
            second_return.append(next_layer)
        first_temp, second_temp = self.get_next_layer(packet.payload)
        first_return += first_temp
        second_return += second_temp
        return first_return, second_return

    def time_to_formal(self, time_stamp):
        """
        将时间戳转换为标准的时间字符串
        如： 2018-10-21 20:27:53.123456
        :parma time_stamp: 时间戳，ms为单位
        """
        delta_ms = str(time_stamp - int(time_stamp))
        time_temp = time.localtime(time_stamp)
        my_time = time.strftime("%Y-%m-%d %H:%M:%S", time_temp)
        my_time += delta_ms[1:8]
        return my_time

    def capture_packet(self):
        """
        抓取数据包
        """
        self.stop_capturing_thread.clear()
        # 抓取数据包并将抓到的包存在列表中
        # sniff中的store=False 表示不保存在内存中，防止内存使用过高
        sniff(
            iface=self.netcard,
            prn=(lambda x: self.process_packet(x)),
            filter=self.filters,
            stop_filter=(lambda x: self.stop_capturing_thread.is_set()),
            store=False)

    def start_capture(self, netcard=None, filters=None):
        """
        开启新线程进行抓包
        :parma netcard: 选择的网卡, "any"为全选
        :parma filters: 过滤器条件
        """
        # 如果已开始抓包，则不能进行操作
        if self.start_flag is True:
            return
        # 如果已经停止且未保存数据包，则提示是否保存数据包
        if self.stop_flag is True:
            if self.save_flag is False:
                resault = QMessageBox.question(
                    self.main_window.this_MainWindow,
                    "提示",
                    "是否保存已抓取的数据包？",
                    QMessageBox.Yes,
                    QMessageBox.Cancel,
                )
                if resault == QMessageBox.Yes:
                    print("先保存数据包,在进行抓包")
                    self.save_captured_to_pcap()
                    self.save_flag = False
                else:
                    print("直接开始不保存")
            self.stop_flag = False
            self.save_flag = False
            self.pause_flag = False
            self.packet_id = 1
            self.packet_list.clear()
        # 如果从暂停开始
        elif self.pause_flag is True:
            # 如果抓包条件改变，停止之前的抓包并开启新线程进行新过滤条件的抓包
            if filters != self.filters or netcard != self.netcard:
                self.stop_capture()
                self.stop_flag = False
            # 如果没改变则继续将抓到的包显示
            self.pause_flag = False
            self.start_flag = True
            return
        self.filters = filters
        self.netcard = netcard
        # 开启新线程进行抓包
        thread = Thread(
            target=self.capture_packet, daemon=True, name="capture_packet")
        thread.start()
        self.start_flag = True

    def pause_capture(self):
        """
        暂停抓包, 抓包函数仍在进行，只是不更行
        """
        self.pause_flag = True
        self.start_flag = False

    def stop_capture(self):
        """
        停止抓包，关闭线程
        """
        # 通过设置终止线程，停止抓包
        self.stop_capturing_thread.set()
        self.stop_flag = True
        self.pause_flag = False
        self.start_flag = False

    def restart_capture(self, netcard=None, filters=None):
        """
        重新开始抓包
        """
        self.stop_capture()
        self.start_capture(netcard, filters)

    def save_captured_to_pcap(self):
        """
        将抓到的数据包保存为pcap格式的文件
        """
        if self.start_flag is True or self.pause_flag is True:
            QMessageBox.warning(self.main_window.this_MainWindow, "警告",
                                "请停止当前抓包！")
            return
        if self.packet_id == 1:
            QMessageBox.warning(self.main_window.this_MainWindow, "警告",
                                "没有可保存的数据包！")
            return
        # 选择保存名称
        filename, _ = QFileDialog.getSaveFileName(
            parent=self.main_window.this_MainWindow,
            caption="保存文件",
            directory=getcwd(),
            filter="All Files (*);;Pcap Files (*.pcap)",
        )
        if filename == "":
            QMessageBox.warning(self.main_window.this_MainWindow, "警告",
                                "保存失败！")
            return
        # 如果没有设置后缀名（保险起见，默认是有后缀的）
        if filename.find(".pcap") == -1:
            # 默认文件格式为 pcap
            filename = filename + ".pcap"
        wrpcap(filename, self.packet_list)
        QMessageBox.information(self.main_window.this_MainWindow, "提示",
                                "保存成功！")
        self.save_flag = True

    def open_pcap_file(self):
        """
        打开pcap格式的文件
        """
        if self.start_flag is True or self.pause_flag is True:
            QMessageBox.warning(self.main_window.this_MainWindow, "警告",
                                "请停止当前抓包！")
            return
        if self.stop_flag is True and self.save_flag is False:
            reply = QMessageBox.question(
                self.main_window.this_MainWindow, 'Message',
                "Do you want to save as pcap?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.save_captured_to_pcap()
        filename, _ = QFileDialog.getOpenFileName(
            parent=self.main_window.this_MainWindow,
            caption="打开文件",
            directory=getcwd(),
            filter="All Files (*);;Pcap Files (*.pcap)",
        )
        if filename == "":
            return
        self.main_window.info_tree.clear()
        self.main_window.treeWidget.clear()
        self.main_window.set_hex_text("")
        # 如果没有设置后缀名（保险起见，默认是有后缀的）
        if filename.find(".pcap") == -1:
            # 默认文件格式为 pcap
            filename = filename + ".pcap"
        self.packet_id = 1
        self.packet_list.clear()
        self.main_window.info_tree.setUpdatesEnabled(False)
        sniff(
            prn=(lambda x: self.process_packet(x)),
            store=False,
            offline=filename)
        self.main_window.info_tree.setUpdatesEnabled(True)
        self.stop_flag = True
        self.save_flag = True

    def get_hex(self, packet_id):
        """
        获取数据包的hexdump()
        :parma packet_id: 传入包对应的序号
        """
        # dump=True 将hexdump返回而不是打印
        return hexdump(self.packet_list[packet_id], dump=True)

    def get_transport_count(self):
        """
        获取传输层数据包的数量
        """
        counter = {"tcp": 0, "udp": 0, "icmp": 0, "arp": 0}
        packet_list = self.packet_list.copy()
        for packet in packet_list:
            if TCP in packet:
                counter["tcp"] += 1
            elif UDP in packet:
                counter["udp"] += 1
            elif ICMP in packet:
                counter["icmp"] += 1
            elif ARP in packet:
                counter["arp"] += 1
            elif packet.payload.payload.name[0:6] == "ICMPv6":
                counter["icmp"] += 1
        return counter

    def get_network_count(self):
        """
        获取网络层数据包的数量
        """
        counter = {"ipv4": 0, "ipv6": 0}
        packet_list = self.packet_list.copy()
        for packet in packet_list:
            if IP in packet:
                counter["ipv4"] += 1
            elif IPv6 in packet:
                counter["ipv6"] += 1
        return counter