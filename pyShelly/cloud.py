# -*- coding: utf-8 -*-
# pylint: disable=broad-except, bare-except

import json
import time
import asyncio
import urllib
import threading
from datetime import datetime, timedelta

from .compat import s
from .const import LOGGER

try:
    import http.client as httplib
except:
    import httplib

class Cloud():
    def __init__(self, root, server, key):
        self.auth_key = key
        self.server = server.replace("https://", "")
        self._last_update = None
        self._stopped = threading.Event()
        self.update_interval = timedelta(minutes=1)
        self._device_list = None
        self._room_list = None
        self._cloud_thread = None
        self._last_post = datetime.now()
        self._root = root
        self.http_lock = threading.Lock()

    def start(self):
        self._cloud_thread = threading.Thread(target=self._update_loop)
        self._cloud_thread.name = "Cloud"
        self._cloud_thread.daemon = True
        self._cloud_thread.start()

    def stop(self):
        self._stopped.set()

    def _update_loop(self):
        if self._root.loop:
            asyncio.set_event_loop(self._root.loop)
        try:
            cloud = self._root.load_cache('cloud')
            if cloud:
                self._device_list = cloud['device_list']
                self._room_list = cloud['room_list']
        except:
            LOGGER.error("Error load cloud cache, %s", ex)
        while not self._stopped.isSet():
            try:
                if self._last_update is None or \
                    datetime.now() - self._last_update \
                                    > self.update_interval:
                    self._last_update = datetime.now()
                    LOGGER.debug("Update from cloud")
                    devices = self.get_device_list()
                    if devices:
                        self._device_list = devices

                    rooms = self.get_room_list()
                    if rooms:
                        self._room_list = rooms

                    self._root.save_cache('cloud', \
                        {'device_list' : self._device_list,
                         'room_list' : self._room_list}
                    )
                else:
                    time.sleep(5)
            except Exception as ex:
                LOGGER.error("Error update cloud, %s", ex)

    def _post(self, path, params=None, retry=0):
        with self.http_lock:
            while datetime.now() - self._last_post < timedelta(seconds=2):
                time.sleep(1)
            self._last_post = datetime.now()

        json_body = None
        params = params or {}
        try:
            LOGGER.debug("POST to Shelly Cloud")
            conn = httplib.HTTPSConnection(self.server, timeout=15)
            headers = {'Content-Type' : 'application/x-www-form-urlencoded'}
            params["auth_key"] = self.auth_key
            conn.request("POST", "/" + path, urllib.parse.urlencode(params),
                         headers)
            resp = conn.getresponse()

            if resp.status == 200:
                body = resp.read()
                json_body = json.loads(s(body))
            else:
                if retry < 2:
                    return self._post(path, params, retry + 1)
                else:
                    LOGGER.warning("Error receive JSON from cloud, %s : %s", \
                                   resp.reason, resp.read())
        except Exception as ex:
            LOGGER.warning("Error connect cloud, %s", ex)
        finally:
            if conn:
                conn.close()

        return json_body

    def get_device_name(self, _id, idx=None, _ext_sensor=None):
        """Return name using template for device"""
        dev = None
        add_idx = idx and idx > 1
        if idx:
            dev = self._device_list.get(_id + '_' + str(idx-1))
            if dev:
                add_idx = False
        if not dev:
            dev = self._device_list.get(_id)
        if dev:
            name = dev['name']
            if _ext_sensor is not None and 'external_sensors_names' in dev:
                ext_sensors = dev['external_sensors_names']
                if str(_ext_sensor) in ext_sensors:
                    ext_name = ext_sensors[str(_ext_sensor)]['name']
                    if ext_name != 'unnamed':
                        name = ext_name
                        add_idx = False
            room = ""
            try:
                room_id = dev['room_id']
                if room_id == '-10':
                    room = '[Hidden]'
                elif room_id in self._room_list:
                    room = self._room_list[room_id]['name']
                else:
                    room = str(room_id)
            except:
                pass
            tmpl = self._root.tmpl_name
            value = tmpl.format(id=id, name=name, room=room)
            if add_idx:
                value = value + " - " + str(idx)
            return value
        return None

    def get_relay_usage(self, _id, channel):
        dev_id = (_id + "_" + str(channel) if channel else _id).lower()
        if self._device_list and dev_id in self._device_list:
            dev = self._device_list[dev_id]
            if 'relay_usage' in dev:
                return dev['relay_usage']
        return None

    def get_room_name(self, _id):
        """Return room name of a device"""
        room = None
        if self._device_list and _id in self._device_list:
            dev = self._device_list[_id]
            try:
                room_id = dev['room_id']
                if room_id == '-10':
                    room = '[Hidden]'
                elif room_id in self._room_list:
                    room = self._room_list[room_id]['name']
                else:
                    room = str(room_id)
            except:
                pass
        return room

    def get_device_list(self):
        resp = self._post("interface/device/list")
        return resp['data']['devices'] if resp else None

    def get_status(self):
        self._post("device/all_status")

    def get_room_list(self):
        resp = self._post("interface/room/list")
        return resp['data']['rooms'] if resp else None