# Copyright (C) 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2012 Isaku Yamahata <yamahata at private email ne jp>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging

from ryu.controller import (dispatcher,
                            event)


LOG = logging.getLogger(__name__)


QUEUE_NAME_QUANTUM_IFACE_EV = 'quantum_iface'
DISPATCHER_NAME_QUANTUM_IFACE_EV = 'quantum_iface_handler'
QUANTUM_IFACE_EV_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_QUANTUM_IFACE_EV)


class EventQuantumIfaceSet(event.EventBase):
    def __init__(self, iface_id, key, value):
        super(EventQuantumIfaceSet, self).__init__()
        self.iface_id = iface_id
        self.key = key
        self.value = value

    def __str__(self):
        return 'EventQuantumIfaceSet<%s, %s, %s>' % (
            self.iface_id, self.key, self.value)


class QuantumIfaces(dict):
    # iface-id => dict

    KEY_NETWORK_ID = 'network_id'
    KEY_DATAPATH_ID = 'datapath_id'
    KEY_OFPORT = 'ofport'
    KEY_NAME = 'name'

    def __init__(self):
        super(QuantumIfaces, self).__init__()
        self.ev_q = dispatcher.EventQueueThread(QUEUE_NAME_QUANTUM_IFACE_EV,
                                                QUANTUM_IFACE_EV_DISPATCHER)

    def register(self, iface_id):
        self.setdefault(iface_id, {})

    def unregister(self, iface_id):
        del self[iface_id]

    def get_iface_dict(self, iface_id):
        return self[iface_id]

    def list_keys(self, iface_id):
        return self[iface_id].keys()

    def get_key(self, iface_id, key):
        return self[iface_id][key]

    def _update_key(self, iface_id, key, value):
        self[iface_id][key] = value
        self.ev_q.queue(EventQuantumIfaceSet(iface_id, key, value))

    def set_key(self, iface_id, key, value):
        iface = self.setdefault(iface_id, {})
        if key in iface:
            raise ValueError('trying to set already existing value '
                             '%s %s -> %s', key, iface[key], value)
        self._update_key(iface_id, key, value)

    def update_key(self, iface_id, key, value):
        iface = self.setdefault(iface_id, {})
        if key in iface:
            if iface[key] != value:
                raise ValueError('unmatched updated %s %s -> %s',
                                 key, iface[key], value)
        self._update_key(iface_id, key, value)
