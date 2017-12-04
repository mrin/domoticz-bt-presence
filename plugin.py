import os
import configparser
import json
import time
import Domoticz

#
#       Bluetooth Beacon Presence Plugin
#       Author: mrin, 2017
#
"""
<plugin key="bt-beacon-presence" name="Bluetooth Beacon Presence" author="mrin" version="0.0.2" wikilink="https://github.com/mrin/domoticz-bt-presence" externallink="">
    <params>
        <param field="Mode1" label="Config" width="500px" required="true" default="00:00:00:00:00:00|20, 00:00:00:00:00:01|20"/>
        <param field="Mode2" label="UDP Listen" width="200px" required="true" default="192.168.0.10:2221"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug" default="true"/>
                <option label="False" value="Normal"/>
            </options>
        </param>
    </params>
</plugin>
"""


class BasePlugin:


    def __init__(self):
        self.udpConn = None
        self.batteryServiceModeTime = None
        self.batteryServiceModeTimeout = 60
        self.config = {}
        self.iconName = 'bt-beacon-presence-icon'

    def onStart(self):
        if Parameters['Mode6'] == 'Debug':
            Domoticz.Debugging(1)
            DumpConfigToLog()

        self.config = loadConfig(Parameters['Mode1'])
        if not self.config: return

        if self.iconName not in Images: Domoticz.Image('icons.zip').Create()
        iconID = Images[self.iconName].ID

        for tagMac, tagSettings in self.config.items():
            if tagSettings['unit'] not in Devices:
                Domoticz.Device(Name='Tag %s' % tagMac, Unit=tagSettings['unit'], TypeName='Switch',
                                Image=iconID).Create()

        host, port = Parameters['Mode2'].split(':')
        self.udpConn = Domoticz.Connection(Name='UDP', Transport='UDP/IP', Protocol='None', Address=host, Port=port)
        self.udpConn.Listen()

        Domoticz.Heartbeat(2)


    def onStop(self):
        pass


    def onMessage(self, Connection, Data):
        tagData = json.loads(Data.decode("utf-8"))
        try:
            cmd = tagData[0]
            scannerName = tagData[1]
            macAddress = tagData[2]
            tag = self.config.get(macAddress, None)

            if not tag:
                Domoticz.Error('Beacon %s is not configured. [Hardware->Device->Config]' % macAddress)
                return

            unit = tag['unit']
            if unit not in Devices: return

            if cmd == 'beacon':
                UpdateDevice(unit, 1, '100')
                rssi = tagData[3]
                Domoticz.Debug('%s RSSI %s. Scanner: %s' % (macAddress, rssi, scannerName))

            elif cmd == 'battery':
                batteryLevel = tagData[3]

                Domoticz.Debug('%s BATTERY %s. Scanner: %s' % (macAddress, batteryLevel, scannerName))

                if batteryLevel:
                    UpdateDevice(unit, Devices[unit].nValue, Devices[unit].sValue, batteryLevel)

                if self.batteryServiceModeTime:
                    self.exitBatteryServiceMode()

            elif cmd == 'battery_service_mode':
                self.enterBatteryServiceMode()

            else:
                Domoticz.Error('Unexpected command: %s' % tagData[0])

            tag['last_update'] = time.time()

        except IndexError:
            Domoticz.Error('Unexpected packet: %s' % tagData)


    def onConnect(self, Connection, Status, Description):
        pass


    def onDisconnect(self, Connection):
        pass


    def onHeartbeat(self):
        if self.batteryServiceModeTime:
            if (time.time() - self.batteryServiceModeTime) >= self.batteryServiceModeTimeout:
                self.exitBatteryServiceMode(byTimeout=True)
            return

        now = time.time()
        for tag in self.config.values():
            if (now - tag['last_update']) >= tag['timeout']:
                UpdateDevice(tag['unit'], 0, '0')

    def onCommand(self, Unit, Command, Level, Hue):
        pass

    def enterBatteryServiceMode(self):
        self.batteryServiceModeTime = time.time()
        Domoticz.Debug('ENTER Battery Service Mode.')

    def exitBatteryServiceMode(self, byTimeout=False):
        t = time.time()
        for tag in self.config.values():
            tag['last_update'] = t
        self.batteryServiceModeTime = None
        Domoticz.Debug('EXIT Battery Service Mode. By Timeout %s.' % byTimeout)


def loadConfig(configStr):
    tags = {}
    cTags = configStr.split(',')
    initialTime = time.time()
    for cTag in cTags:
        parts = cTag.strip().split('|')
        try:
            macAddress = parts[0].lower()
            timeout = int(parts[1])
            tags[macAddress] = {
                'timeout': timeout,
                'last_update': initialTime,
                'unit': None
            }
        except IndexError:
            Domoticz.Error('Unexpected config format: %s' % cTag)

    path = Parameters['HomeFolder'] + 'plugin.ini'
    config = configparser.ConfigParser()
    if os.path.exists(path):
        config.read(path)

    nextId = nextUnitId(config)
    for mac, tag in tags.items():
        if mac in config.sections():
            tag['unit'] = int(config[mac]['unit'])
        else:
            tag['unit'] = nextId
            config[mac] = {'unit': nextId}
            nextId += 1

    try:
        with open(path, 'w') as configfile:
            config.write(configfile)
    except IOError:
        Domoticz.Error('Error updating config file')
        return None

    return tags


def nextUnitId(config):
    unitIds = [int(config[section]['unit']) for section in config.sections()]
    return max(unitIds)+1 if unitIds else 1


def UpdateDevice(Unit, nValue, sValue, BatteryLevel=None, AlwaysUpdate=False):
    if Unit not in Devices: return
    if Devices[Unit].nValue != nValue\
        or Devices[Unit].sValue != sValue\
        or (BatteryLevel and Devices[Unit].BatteryLevel != BatteryLevel)\
        or AlwaysUpdate == True:

        BatteryLevel = Devices[Unit].BatteryLevel if BatteryLevel is None else BatteryLevel

        Devices[Unit].Update(nValue, str(sValue), BatteryLevel=BatteryLevel)

        Domoticz.Log("Update %s: nValue %s - sValue %s - BatteryLevel %s" % (
            Devices[Unit].Name,
            nValue,
            sValue,
            BatteryLevel
        ))


global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onMessage(Connection, Data, Status=None, Extra=None):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

    # Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return