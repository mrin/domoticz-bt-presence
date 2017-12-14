#!/usr/bin/python

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
import re
from datetime import datetime, timedelta

#### LOGGING
import logging
from logging.handlers import RotatingFileHandler
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--log', type=str, default=None)
parser.add_argument('--loglevel', type=str, const='all', nargs='?', choices=['debug', 'info', 'error'], default='debug')
args = parser.parse_args()

logLevelMap = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'error': logging.ERROR
}
logLevel = logLevelMap.get(args.loglevel)

logger = logging.getLogger('ble_scanner')
logger.setLevel(logLevel)
if args.log:
    h = RotatingFileHandler(os.path.join(os.path.dirname(__file__), '.', args.log), maxBytes=1024 * 1024, backupCount=5)
else:
    h = logging.StreamHandler(sys.stdout)

h.setLevel(logLevel)
h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(h)
#### ./LOGGING

LE_META_EVENT = 0x3e
OGF_LE_CTL = 0x08
OCF_LE_SET_SCAN_ENABLE = 0x000C
EVT_LE_CONN_COMPLETE = 0x01
EVT_LE_ADVERTISING_REPORT = 0x02

SCANNER_NAME = ''
HCI_INTERFACE = ''
SERVER_IP = ''
SERVER_PORT = 2221
BATTERY_CHECK_TIME = None
BATTERY_CHECK_INTERVAL = 30 * 60
BATTERY_CHECK_RSSI = None
BATTERY_CHECK_ATTEMPTS = 0
BATTERY_UUID = {
    'miband2': '00000006-0000-3512-2118-0009af100700',
    'nut3': '00002a19-0000-1000-8000-00805f9b34fb'
}
FILTER_TAGS = {}


### for run as service
def signal_handler(signum=None, frame=None):
    time.sleep(1)
    sys.exit(0)
for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT]:
    signal.signal(sig, signal_handler)
### ./for run as service

def loadConfig():
    global SCANNER_NAME, FILTER_TAGS, HCI_INTERFACE, SERVER_IP, SERVER_PORT, BATTERY_CHECK_TIME, \
        BATTERY_CHECK_RSSI, BATTERY_CHECK_ATTEMPTS

    path = os.path.join(os.path.dirname(__file__), 'config.ini')
    config = ConfigParser.ConfigParser()
    if os.path.exists(path):
        config.read(path)
    else:
        logger.error('File %s cannot be opened', path)
        sys.exit(1)

    SCANNER_NAME = config.get('Settings', 'scanner_name').strip()
    HCI_INTERFACE = config.get('Settings', 'bt_interface').strip()
    SERVER_IP = config.get('Settings', 'server_ip').strip()
    SERVER_PORT = int(config.get('Settings', 'server_port').strip())
    FILTER_TAGS = {}
    for section in config.sections():
        if section != 'Settings':
            FILTER_TAGS[section.strip().lower()] = {
                'label': config.get(section, 'label', '').strip(),
                'rssi_threshold': config.get(section, 'rssi_threshold', '').strip(),
                'battery_service_type': config.get(section, 'battery_service_type', '').strip(),
                'battery_last_check': None,
                'battery_check_attempts': 0,
                'battery_last_attempt': None,
                'battery_check_on_script_start': True
            }

    battery_rssi = config.get('Settings', 'battery_check_rssi_threshold', '').strip()
    BATTERY_CHECK_RSSI = int(battery_rssi) if battery_rssi != '' else None

    battery_attempts = config.get('Settings', 'battery_check_attempts', '').strip()
    BATTERY_CHECK_ATTEMPTS = int(battery_attempts) if battery_attempts != '' else 0

    battery_time = config.get('Settings', 'battery_check_time', '').strip()
    BATTERY_CHECK_TIME = battery_time if battery_time != '' else None

def print_packet(pkt):
    for c in pkt:
        sys.stdout.write("%02x " % struct.unpack("B", c)[0])

def packed_bdaddr_to_string(bdaddr_packed):
    return ':'.join('%02x' % i for i in struct.unpack("<BBBBBB", bdaddr_packed[::-1]))

def restart_hci():
    os.system('sudo hciconfig %s down' % HCI_INTERFACE)
    time.sleep(1)
    os.system('sudo hciconfig %s up' % HCI_INTERFACE)

def popen_execute(cmd):
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (output, err) = p.communicate()
    return (output, err)

def battery_service_checker(mac, tag):
    logger.info('start battery check %s', mac)
    level = None
    battery_service_type = tag['battery_service_type']
    battery_uuid = BATTERY_UUID.get(battery_service_type)

    try:
        restart_hci()

        if battery_service_type != 'miband2':

            bt_conn_output, err = popen_execute(["hcitool -i %s lecc --random %s" % (HCI_INTERFACE, mac)])
            bt_conn_handle_regex = re.search('(\d+)', bt_conn_output)
            if err or not bt_conn_handle_regex:
                logger.error('battery service: LE connect error [%s] [%s]', mac, err)
                return level

            bt_conn_handle_id = bt_conn_handle_regex.group(1)

            bt_disconnect_output, err = popen_execute(["hcitool -i %s ledc %s" % (HCI_INTERFACE, bt_conn_handle_id)])
            if err:
                logger.error('battery service: LE disconnect error [%s] [%s]', mac, err)
                return level

        gatt_output, err = popen_execute(["gatttool -i %s -t random -b %s --char-read --uuid %s" % (
            HCI_INTERFACE,
            mac,
            battery_uuid
        )])
        if err or "value:" not in gatt_output:
            logger.error('battery service: LE gatttool error [%s] [%s][%s]', mac, gatt_output, err)
            return level

        gatt_output = gatt_output.replace(" ", "").replace("\n", "")
        bin_value = gatt_output[gatt_output.find("value:") + 6:].decode("hex")

        # Mi Band 2
        if battery_service_type == 'miband2':
            level = struct.unpack('H', bin_value[1:3])[0]

        # NUT 3
        elif battery_service_type == 'nut3':
            level = struct.unpack('H', bin_value)[0]

        else:
            logger.error('battery service: unknown device type [%s] [%s] [%s]', mac, battery_uuid, gatt_output)

        if level is not None:
            logger.info('battery service: [%s] level %s%%', mac, level)

        return level

    except Exception as e:
        logger.error('battery service: Exception %s', e)
        return level

    finally:
        logger.info('end battery check %s', mac)

def is_time_between_check_battery_time(time_str):
    if not BATTERY_CHECK_TIME: return False
    endTime = (datetime.strptime(BATTERY_CHECK_TIME, '%H:%M') + timedelta(seconds=BATTERY_CHECK_INTERVAL)).strftime('%H:%M')
    time_range = (BATTERY_CHECK_TIME, endTime)
    if time_range[1] < time_range[0]:
        return time_str >= time_range[0] or time_str <= time_range[1]
    return time_range[0] <= time_str <= time_range[1]

loadConfig()

# when run as service this script may start before BT daemon is started
bt_is_running_attempts = 5
while bt_is_running_attempts:
    restart_hci()

    # Make sure device is up
    interface = subprocess.Popen(['hciconfig'], stdout=subprocess.PIPE, shell=True)
    (output, err) = interface.communicate()

    if 'RUNNING' in output:  # Check return of hciconfig to make sure it's up
        logger.info('Ok %s interface Up n running !' % HCI_INTERFACE)
        break
    else:
        logger.critical('Error : hci0 interface not Running. Do you have a BLE device connected to %s? '
                         'Check with hciconfig!', HCI_INTERFACE)

    bt_is_running_attempts -= 1
    time.sleep(5)
    if not bt_is_running_attempts:
        sys.exit(1)


udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
bt_sock = None
need_reconnect = False

while True:

    # connect to bt hci
    if bt_sock is None or need_reconnect:
        if bt_sock:
            logger.debug('close old bt socket')
            bt_sock.close()
            bt_sock = None

        restart_hci()

        try:
            logger.debug('new bt socket')
            bt_sock = bluez.hci_open_dev(int(HCI_INTERFACE[-1:]))
            logger.debug('Connected to bluetooth device %s', HCI_INTERFACE)
            time.sleep(1)
        except:
            logger.critical('Unable connect to bluetooth device...')
            sys.exit(1)

        old_filter = bt_sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 14)

        # enable LE scan
        cmd_pkt = struct.pack("<BB", 0x01, 0x00)
        bluez.hci_send_cmd(bt_sock, OGF_LE_CTL, OCF_LE_SET_SCAN_ENABLE, cmd_pkt)

        need_reconnect = False

    # prepare to receive bt events
    old_filter = bt_sock.getsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, 14)
    hci_filter = bluez.hci_filter_new()
    bluez.hci_filter_all_events(hci_filter)
    bluez.hci_filter_set_ptype(hci_filter, bluez.HCI_EVENT_PKT)
    bt_sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, hci_filter)

    pkt = bt_sock.recv(255)
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
                tag = FILTER_TAGS[macAddress]

                rssi, = struct.unpack("b", pkt[report_pkt_offset - 1])
                rssiTreshold = tag['rssi_threshold'].strip()

                # tag availability
                if rssiTreshold == '' or rssi >= int(rssiTreshold):
                    udp.sendto(json.dumps(['beacon', SCANNER_NAME, macAddress, rssi]), (SERVER_IP, SERVER_PORT))
                    logger.info('%s RSSI %s - %s', macAddress.lower(), rssi, tag['label'])

                #  battery check
                cur_time = datetime.now()
                if BATTERY_UUID.get(tag['battery_service_type'], None) \
                        and rssi >= BATTERY_CHECK_RSSI \
                        and (is_time_between_check_battery_time(cur_time.strftime('%H:%M'))
                             or tag['battery_check_on_script_start']):

                    last_attempt_time = tag['battery_last_attempt']
                    delta_last_attempt = cur_time - last_attempt_time if last_attempt_time else None
                    attempts = tag['battery_check_attempts']

                    if attempts and delta_last_attempt and delta_last_attempt.total_seconds() >= BATTERY_CHECK_INTERVAL:
                        attempts = tag['battery_check_attempts'] = 0

                    if attempts < BATTERY_CHECK_ATTEMPTS:

                        last_check_time = tag['battery_last_check']
                        delta_last_check = cur_time - last_check_time if last_check_time else None

                        if tag['battery_check_on_script_start'] \
                                or last_check_time is None \
                                or delta_last_check.total_seconds() >= BATTERY_CHECK_INTERVAL:

                            udp.sendto(json.dumps(['battery_service_mode', SCANNER_NAME, macAddress]), (SERVER_IP, SERVER_PORT))
                            battery_level = battery_service_checker(macAddress, tag)
                            udp.sendto(json.dumps(['battery', SCANNER_NAME, macAddress, battery_level]), (SERVER_IP, SERVER_PORT))

                            if tag['battery_check_on_script_start']:
                                pass

                            elif battery_level is None:
                                tag['battery_check_attempts'] += 1
                                tag['battery_last_attempt'] = cur_time

                            else:
                                tag['battery_last_check'] = cur_time

                            need_reconnect = True

                    tag['battery_check_on_script_start'] = False


    bt_sock.setsockopt(bluez.SOL_HCI, bluez.HCI_FILTER, old_filter)
