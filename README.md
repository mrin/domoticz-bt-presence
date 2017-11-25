# Bluetooth Beacon Presence Detection

*See this [link](https://www.domoticz.com/wiki/Using_Python_plugins) for more information on the Domoticz plugins.*

Plugin consists of:

**Bluetooth LE scanner**: for listening of beacons, check battery level and sending info to the domoticz plugin through UDP. 
Ability to run several services for greater coverage of home.

**Domoticz plugin**: Manage beacons availability by timeout. Contains UDP server for receive data from scanner.

## Prepare to install

These instructions assume a Debian-based Linux.

On Linux the [BlueZ](http://www.bluez.org/download/) library is necessary to access your built-in Bluetooth controller or Bluetooth USB dongle.
It is tested to work with BlueZ 5.47, but it should work with 5.43+ too.

Check BlueZ version: ```bluetoothd --version```

### Installing BlueZ from sources:

```
sudo systemctl stop bluetooth
sudo apt-get update
sudo apt-get install libusb-dev libdbus-1-dev libglib2.0-dev libudev-dev libical-dev libreadline-dev

# latest http://www.bluez.org/download/ (User Space Package)
wget http://www.kernel.org/pub/linux/bluetooth/bluez-5.47.tar.xz
tar xf bluez-5.47.tar.xz
cd bluez-5.47
./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var --enable-library
make
sudo make install

sudo ln -svf /usr/libexec/bluetooth/bluetoothd /usr/sbin/
sudo install -v -dm755 /etc/bluetooth
sudo install -v -m644 src/main.conf /etc/bluetooth/main.conf
sudo systemctl daemon-reload
sudo systemctl start bluetooth

bluetoothd --version 
# should now print 5.47
```

### Checking bluetooth:

Run the hciconfig tool:
```
pi@smarthome:~ $ hciconfig
hci0:	Type: Primary  Bus: UART
	BD Address: 00:27:EB:9F:11:C1  ACL MTU: 1021:8  SCO MTU: 64:1
	UP RUNNING 
	RX bytes:573313972 acl:0 sco:0 events:14089069 errors:0
	TX bytes:1947 acl:0 sco:0 commands:113 errors:0
```

Reset the bluetooth adapter (hci0 in the above example) with:
```
sudo hciconfig hci0 down
sudo hciconfig hci0 up
```

Find the MAC Address of your beacon with hcitool:
```
sudo hcitool lescan
```

### Domoticz plugin system requirements:

Latest Beta's only now. Make sure you have installed ```python3```, ```python3-dev``` for run python plugin system.

```sudo apt-get install python3 python3-dev```

## Installation

```
sudo apt-get install python-bluez

cd domoticz/plugins
git clone https://github.com/mrin/domoticz-bt-presence bt-presence
cd bt-presence
sudo chmod +x ble_scanner.sh
sudo chmod +x ble_scanner.py

# restart domoticz
sudo service domoticz.sh restart
```

If you have mac addresses of your beacons let's configure plugin and then BLE Scanner.
 
**Setup** -> **Hardware** in your Domoticz interface and add type with name **Bluetooth Beacon Presence**.

| Field | Information|
| ----- | ---------- |
| Data Timeout | Keep Disabled |
| Config | Format "mac:timeout", ex. 00:00:00:00:00:00&#124;20 where 20sec is timeout. Comma is delimiter.|
| UDP Listen | 192.168.0.10:2221, domoticz IP and UDP port for incoming messages from BLE Scanner |
| Debug | When set to true the plugin shows additional information in the Domoticz log |
 
 After clicking on the Add button the new devices are available in **Setup** -> **Devices**.
 
 **Time to configure BLE Scanner**
 
```
# copy config template
cp config.ini.dist config.ini
nano config.ini

# config.ini

[Settings]
; Use different scanner_name if you have several instances for better debugging
scanner_name=Living room
; By default hci0 in RPI3, but you can check with "hciconfig" command
bt_interface=hci0
; Domoticz IP and UDP port where plugin runs
server_ip=192.168.0.10
server_port=2221
; Check battery if signal strength >= setting
; Connection will not be established if signal is very low
battery_check_rssi_threshold=-75
; Time to check battery. 24h. Interval check_time + 30min
battery_check_time=03:00
; Attempts to check in time interval when beacon available
battery_check_attempts=2

; Beacon MAC address
[00:00:00:00:00:00]
; For better debug
label=key tag
; Supports battery check for nut3 and miband2
; Can be empty (battery check disabled)
battery_service_type=nut3
; Signal strength threshold,
; When signal lower the setting -> beacon info will not send to the plugin
; Can be empty (threshold disabled)
rssi_threshold=

[00:00:00:00:00:01]
label=mi band 2
battery_service_type=miband2
rssi_threshold=-120
```

Now you can run BLE Scanner:
```
pi@smarthome:~/domoticz/plugins/bt-presence $ sudo ./ble_scanner.py
2017-11-25 02:02:32,469 - root - DEBUG - Ok hci0 interface Up n running !
2017-11-25 02:02:33,731 - root - DEBUG - new bt socket
2017-11-25 02:02:33,732 - root - DEBUG - Connected to bluetooth device hci0
2017-11-25 02:02:36,251 - root - DEBUG - 00:00:00:00:00:00 RSSI -55 - mi band 2
2017-11-25 02:02:36,802 - root - DEBUG - 00:00:00:00:00:01 RSSI -100 - key tag
```

*Keep in mind, you can run several scanners for greater coverage*


### Run BLE scanner as service

Check absolute path to ble scanner:
```
nano ble_scanner.sh

DAEMON=/home/pi/domoticz/plugins/bt-presence/ble_scanner.py
```

Symlink ble_scanner.sh and add to system services:

```
# check your path here:
sudo ln -s /home/pi/domoticz/plugins/bt-presence/ble_scanner.sh /etc/init.d/ble_scanner
# add to startup:
sudo update-rc.d ble_scanner defaults
sudo systemctl daemon-reload

# check service status
sudo service ble_scanner status

# to start
sudo service ble_scanner start

# to stop
sudo service ble_scanner stop

# if you want to delete from startup:
sudo update-rc.d -f ble_scanner remove
```

## Screenshots

![ble_tag](https://user-images.githubusercontent.com/93999/33228134-fa826958-d1c4-11e7-846b-690ceee87825.png)


## Beacons

- Nut find 3, Nut find 2, Nut mini
http://nutspaworce.com (can be found on ALI etc...)
- Mi Band 1, 1S, 2 (in discoverable mode)
- other LE beacons

Battery checker supports "Nut find 3" and Mi Band 2 now. 
To add your beacon, use Android app "BLE Scanner:
1. Open app and Scan BLE devices
2. Find your device in the list and click Connect
3. Find attribute "Battery Service", click on it then save UUID.
4. Create Issue on github and send UUID, beacon device link/photo, read value.
Also battery level can be encoded in other attribute, for example Mi Band 2 does not have "Battery service", 
but have bettery level encoded in depth by UUID ```00000006-0000-3512-2118-0009af100700```


![battery_1](https://user-images.githubusercontent.com/93999/33228575-aae2e070-d1cf-11e7-9adc-989b8e3494d3.png)
