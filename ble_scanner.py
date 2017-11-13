#!/usr/bin/python

#### LOGGING
import logging
logLevel=logging.DEBUG
FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(format=FORMAT, level=logLevel)
#### ./LOGGING

import os
import subprocess
import sys
import struct
import bluetooth._bluetooth as bluez
import time
import signal
import socket
import json
import ConfigParser

LE_META_EVENT = 0x3e
OGF_LE_CTL = 0x08
OCF_LE_SET_SCAN_ENABLE = 0x000C
EVT_LE_CONN_COMPLETE = 0x01
EVT_LE_ADVERTISING_REPORT = 0x02


### for run as service
def signal_handler(signum=None, frame=None):
    time.sleep(1)
    sys.exit(0)
for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT]:
    signal.signal(sig, signal_handler)
### ./for run as service

def loadConfig():
    global SCANNER_NAME, FILTER_TAGS, DEVICE, SERVER_IP, SERVER_PORT
    path = os.path.join(os.path.dirname(__file__), 'config.ini')
    config = ConfigParser.ConfigParser()
    if os.path.exists(path):
        config.read(path)
    else:
        logging.error('File %s cannot be opened', path)
        sys.exit(1)

    SCANNER_NAME = config.get('Settings', 'scanner_name').strip()
    DEVICE = config.get('Settings', 'bt_interface').strip()
    SERVER_IP = config.get('Settings', 'server_ip').strip()
    SERVER_PORT = int(config.get('Settings', 'server_port').strip())
    FILTER_TAGS = {}
    for section in config.sections():
        if section != 'Settings':
            FILTER_TAGS[section.strip().lower()] = {
                'battery_uuid': config.get(section, 'battery_uuid', ''),
                'rssi_threshold': config.get(section, 'rssi_threshold', ''),
            }

loadConfig()

def print_packet(pkt):
    for c in pkt:
        sys.stdout.write("%02x " % struct.unpack("B", c)[0])


def packed_bdaddr_to_string(bdaddr_packed):
    return ':'.join('%02x' % i for i in struct.unpack("<BBBBBB", bdaddr_packed[::-1]))

# Reset Bluetooth interface, hci0
os.system('sudo hciconfig %s down' % DEVICE)
os.system('sudo hciconfig %s up' % DEVICE)

# Make sure device is up
interface = subprocess.Popen(['sudo hciconfig'], stdout=subprocess.PIPE, shell=True)
(output, err) = interface.communicate()
if 'RUNNING' in output:  # Check return of hciconfig to make sure it's up
    logging.debug('Ok %s interface Up n running !' % DEVICE)
else:
    logging.critical(
        'Error : hci0 interface not Running. Do you have a BLE device connected to hci0 ? Check with hciconfig !')
    sys.exit(1)

try:
    sock = bluez.hci_open_dev(int(DEVICE[-1:]))
    logging.debug('Connected to bluetooth device %s', DEVICE)
except:
    logging.critical('Unable connect to bluetooth device...')
    sys.exit(1)

old_filter = sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 14)

# enabling LE scan
cmd_pkt = struct.pack("<BB", 0x01, 0x00)
bluez.hci_send_cmd(sock, OGF_LE_CTL, OCF_LE_SET_SCAN_ENABLE, cmd_pkt)

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP

while True:
    old_filter = sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 14)
    hci_filter = bluez.hci_filter_new()
    bluez.hci_filter_all_events(hci_filter)
    bluez.hci_filter_set_ptype(hci_filter, bluez.HCI_EVENT_PKT)
    sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, hci_filter)

    pkt = sock.recv(255)
    ptype, event, plen = struct.unpack("BBB", pkt[:3])

    if event == bluez.EVT_INQUIRY_RESULT_WITH_RSSI:
        i = 0
    elif event == bluez.EVT_NUM_COMP_PKTS:
        i = 0
    elif event == bluez.EVT_DISCONN_COMPLETE:
        i = 0
    elif event == LE_META_EVENT:
        subevent, = struct.unpack("B", pkt[3])
        pkt = pkt[4:]
        if subevent == EVT_LE_CONN_COMPLETE:
            pass
        elif subevent == EVT_LE_ADVERTISING_REPORT:
            num_reports = struct.unpack("B", pkt[0])[0]
            report_pkt_offset = 0
            for i in range(0, num_reports):

                macAddress = packed_bdaddr_to_string(pkt[report_pkt_offset + 3:report_pkt_offset + 9]).lower()
                if macAddress not in FILTER_TAGS: continue

                rssi, = struct.unpack("b", pkt[report_pkt_offset - 1])
                rssiTreshold = FILTER_TAGS[macAddress]['rssi_threshold'].strip()

                if rssiTreshold == '' or rssi >= int(rssiTreshold):
                    udp.sendto(json.dumps(['beacon', SCANNER_NAME, macAddress, rssi]), (SERVER_IP, SERVER_PORT))
                    logging.debug('%s RSSI %s.', macAddress.lower(), rssi)

    sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, old_filter)
