"""
ZhongHong platform that offers a ZhongHong climate device.

For more details about this platform, please refer to the documentation
https://home-assistant.io/components/climate
"""
import socket
import logging
import time
from collections import defaultdict
from threading import Thread

import voluptuous as vol

from homeassistant.components.climate import (
    PLATFORM_SCHEMA, SUPPORT_FAN_MODE, SUPPORT_ON_OFF, SUPPORT_OPERATION_MODE,
    STATE_OFF, STATE_ON, STATE_AUTO, STATE_COOL, STATE_DRY, STATE_FAN_ONLY,
    STATE_HEAT, SUPPORT_TARGET_TEMPERATURE, ClimateDevice)
from homeassistant.const import (ATTR_TEMPERATURE, CONF_HOST,
                                 EVENT_HOMEASSISTANT_START, TEMP_CELSIUS)
from homeassistant.exceptions import PlatformNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.util.temperature import convert as convert_temperature

_LOGGER = logging.getLogger(__name__)

ZH_TCP_PORT = 9999
SOCKET_BUFSIZE = 1024
SOCKET_TIMEOUT = 60.0
DISCOVER_TIMEOUT = 10

CONF_GATEWAY_ADDRRESS = 'gateway_address'

def _data_struct(data):
    devices = {}
    if data[2] == 0x01:
        for devnum in range(len(data)//15):
            add = devnum * 15
            dev,addr = _ac_status(data[0+add],data[4+add:14+add])
            devices[addr] = dev
    elif data[2] == 0xFF:
        for devnum in range((len(data)-5)//10):
            add = devnum * 10
            dev,addr = _ac_status(data[0],data[4+add:14+add])
            devices[addr] = dev
    return devices

def _ac_status(gw_addr,data):
    state = ['out_addr', 'in_addr','power',
            'settem', 'mode', 'fan_mode', 'tmp']
    dev = dict(zip(state,data[:7]))
    addr = '_'.join([str(gw_addr),str(data[0]),str(data[1])])
    dev['addr'] = addr
    return dev,addr

def _request_factory(gw_addr,cmd,value,num=0xFF,out_addr=0xFF,in_addr=0xFF):
    cmd = bytes([gw_addr,cmd,int(value),num,out_addr,in_addr])
    check_sum = 0
    for add in cmd:
        check_sum += add
    return cmd + bytes([check_sum & 0xFF])

class ZhongHongHub(object):
    """ZhongHong."""

    def __init__(self, ip_addr, gw_addr=1):

        self._ip_addr = ip_addr
        self._gw_addr = gw_addr
        self._listening = False
        self._socket = None
        self._discover_state = False
        self._threads = []

        self.ac_devices = defaultdict(list)
        self.callbacks = defaultdict(list)

        self.listen()

    def discover_devices(self):
        self._discover_state = True
        self._get_all_state()
        time_now = time.time()
        while self._discover_state:
            time.sleep(1)
            if time.time() - time_now > DISCOVER_TIMEOUT:
                self._discover_state = False
                _LOGGER.error('no zhonghongHub responde')
                return False
        _LOGGER.info("zhonghongHub discovery finished")
        return True

    def send_cmd(self, data):
        try:
            _LOGGER.debug("send >> %s", data)
            self._socket.send(data)

        except socket.timeout:
            _LOGGER.error("Connot connect to ZhongHong_hub %s", self._ip_addr)
            return

        except OSError as e:
            if e.errno == 32:  # Broken pipe
                _LOGGER.error("OSError 32 raise, Broken pipe", exc_info=e)

    def _get_all_state(self):
        cmd = _request_factory(self._gw_addr,0x50,0xFF)
        self.send_cmd(cmd)

    def turn_on(self,out_addr,in_addr):
        cmd = _request_factory(self._gw_addr,0x31,0x01,0x01,out_addr,in_addr)
        self.send_cmd(cmd)

    def turn_off(self,out_addr,in_addr):
        cmd = _request_factory(self._gw_addr,0x31,0x02,0x01,out_addr,in_addr)
        self.send_cmd(cmd)

    def set_temperature(self,out_addr,in_addr,tmp):
        cmd = _request_factory(self._gw_addr,0x32,tmp,0x01,out_addr,in_addr)
        self.send_cmd(cmd)

    def set_operation_mode(self, out_addr,in_addr, operation_mode):
        opt = {
            'cool': 0x01,
            'dry': 0x02,
            'fan_only': 0x04,
            'heat': 0x08
        }
        cmd = _request_factory(self._gw_addr,0x33,opt[operation_mode],
                                                0x01,out_addr,in_addr)
        self.send_cmd(cmd)

    def set_fan_mode(self, out_addr,in_addr, fan_mode):
        opt = {
            "high": 0x01,
            "medium": 0x02,
            "low": 0x04
        }
        cmd = _request_factory(self._gw_addr,0x34,opt[fan_mode],
                                        0x01,out_addr,in_addr)
        self.send_cmd(cmd)

    def _creat_socket(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(SOCKET_TIMEOUT)
            self._socket.connect((self._ip_addr,ZH_TCP_PORT))
        except:
            _LOGGER.error('creat socket error')

    def listen(self):
        """Start listening."""
        _LOGGER.info('Creating Socket')
        self._creat_socket()
        self._listening = True
        thread = Thread(target=self._listen_to_msg, args=())
        self._threads.append(thread)
        thread.daemon = True
        thread.start()

    def stop_listen(self):
        """Stop listening."""
        self._listening = False

        if self._socket is not None:
            _LOGGER.info('Closing socket')
            self._socket.close()
            self._socket = None

        for thread in self._threads:
            thread.join()

    def _listen_to_msg(self):
        while self._listening:
            if self._socket is None:
                continue

            try:
                data = self._socket.recv(SOCKET_BUFSIZE)
            except ConnectionResetError:
                _LOGGER.debug("Connection reset by peer")
                self._creat_socket()
                continue

            except socket.timeout as e:
                self._get_all_state()
                continue

            except OSError as e:
                if e.errno == 9:  # when socket close, errorno 9 will raise
                    _LOGGER.debug("OSError 9 raise, socket is closed")
                else:
                    _LOGGER.error("unknown error when recv", exc_info=e)
                continue

            if len(data) < 15 or data[1] != 0x50:
                continue

            _LOGGER.debug("recv data << %s", data)

            try:
                devices = _data_struct(data)
            except:
                _LOGGER.error('unkonw data recived << %s',data)
                continue

            for addr in devices:
                self.ac_devices[addr] = devices[addr]
                for func in self.callbacks[addr]:
                    func(devices[addr])

            if self._discover_state and data[2] == 0xFF:
                self._discover_state = False

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST):
    cv.string,
    vol.Optional(CONF_GATEWAY_ADDRRESS, default=1):
    vol.Coerce(int),
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the zhonghong component."""

    host = config.get(CONF_HOST)
    gw_addr = config.get(CONF_GATEWAY_ADDRRESS)
    hub = ZhongHongHub(host, gw_addr)
    devices = []
    if hub.discover_devices():
        for dev in hub.ac_devices:
            devices.append(ZhongHongClimate(hub, hub.ac_devices[dev]))
        add_devices(devices)
        return True
    else:
        hub.stop_listen()
        return False

class ZhongHongClimate(ClimateDevice):
    """Representation of a ZhongHong controller support HVAC."""

    def __init__(self, hub, dev):
        """Set up the ZhongHong climate devices."""
        self._addr = dev['addr']
        hub.callbacks[self._addr].append(self.press_data)

        self._out_addr = dev['out_addr']
        self._in_addr = dev['in_addr']

        self._name = 'ZhongHong_' + dev['addr']
        self._min_temp = 16
        self._max_temp = 30

        self._operation_list = [STATE_COOL, STATE_DRY,
                                STATE_FAN_ONLY, STATE_HEAT]
        self._fan_list = ["high", "medium", "low"]

        self._is_on = dev['power'] == 1
        self._target_temperature = dev['settem']
        self._current_temperature = dev['tmp']
        self._current_operation = self._operation_list[len(bin(dev['mode'])[3:])]
        self._current_fan_mode = self._fan_list[len(bin(dev['fan_mode'])[3:])]

        self._turn_on = hub.turn_on
        self._turn_off = hub.turn_off
        self._set_temperature = hub.set_temperature
        self._set_operation_mode = hub.set_operation_mode
        self._set_fan_mode = hub.set_fan_mode


    def press_data(self, data):
        """Push from Hub."""
        if not data:
            return False

        _LOGGER.debug("PUSH >> %s: %s", self, data)
        self._is_on = data['power'] == 1
        self._target_temperature = data['settem']
        self._current_temperature = data['tmp']
        self._current_operation = self._operation_list[len(bin(data['mode'])[3:])]
        self._current_fan_mode = self._fan_list[len(bin(data['fan_mode'])[3:])]

        self.schedule_update_ha_state()
        return True

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the thermostat, if any."""
        return self._name

    @property
    def unique_id(self):
        """Return the unique ID of the HVAC."""
        return self._name

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return (SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE
                | SUPPORT_OPERATION_MODE | SUPPORT_ON_OFF)

    @property
    def temperature_unit(self):
        """Return the unit of measurement used by the platform."""
        return TEMP_CELSIUS

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool, idle."""
        return self._current_operation

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return self._operation_list

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1

    @property
    def is_on(self):
        """Return true if on."""
        return self._is_on

    @property
    def current_fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def fan_list(self):
        """Return the list of available fan modes."""
        return self._fan_list

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return convert_temperature(self._min_temp, TEMP_CELSIUS,
                                   self.temperature_unit)

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return convert_temperature(self._max_temp, TEMP_CELSIUS,
                                   self.temperature_unit)

    def turn_on(self):
        """Turn on ac."""
        self._turn_on(self._out_addr,self._in_addr)

    def turn_off(self):
        """Turn off ac."""
        self._turn_off(self._out_addr,self._in_addr)

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._set_temperature(self._out_addr,self._in_addr,temperature)

    def set_operation_mode(self, operation_mode):
        """Set new target operation mode."""
        self._set_operation_mode(self._out_addr,self._in_addr,operation_mode)

    def set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        self._set_fan_mode(self._out_addr,self._in_addr,fan_mode)
