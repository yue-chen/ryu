# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011 Isaku Yamahata <yamahata at valinux co jp>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging

from ryu.app.rest_nw_id import NW_ID_UNKNOWN
from ryu.controller import dispatcher
from ryu.controller import event
from ryu.exception import MacAddressAlreadyExist
from ryu.exception import NetworkNotFound, NetworkAlreadyExist
from ryu.exception import PortAlreadyExist, PortNotFound, PortUnknown


LOG = logging.getLogger('ryu.controller.network')


QUEUE_NAME_NETWORK_TENANT_EV = 'network_tenant_event'
DISPATCHER_NAME_NETWORK_TENANT_EV = 'network_tenant_handler'
NETWORK_TENANT_EV_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_NETWORK_TENANT_EV)


class EventNetworkDel(event.EventBase):
    def __init__(self, network_id):
        super(EventNetworkDel, self).__init__()
        self.network_id = network_id


class EventNetworkPort(event.EventBase):
    def __init__(self, network_id, dpid, port_no, add_del):
        super(EventNetworkPort, self).__init__()
        self.network_id = network_id
        self.dpid = dpid
        self.port_no = port_no
        self.add_del = add_del


class EventMacAddress(event.EventBase):
    def __init__(self, dpid, port_no, network_id, mac_address, add_del):
        super(EventMacAddress, self).__init__()
        assert network_id is not None
        assert mac_address is not None
        self.dpid = dpid
        self.port_no = port_no
        self.network_id = network_id
        self.mac_address = mac_address
        self.add_del = add_del


class Networks(dict):
    "network_id -> set of (dpid, port_no)"
    def __init__(self, ev_q):
        super(Networks, self).__init__()
        self.ev_q = ev_q

    def list_networks(self):
        return self.keys()

    def has_network(self, network_id):
        return network_id in self

    def update_network(self, network_id):
        self.setdefault(network_id, set())

    def create_network(self, network_id):
        if network_id in self:
            raise NetworkAlreadyExist(network_id=network_id)

        self[network_id] = set()

    def remove_network(self, network_id):
        try:
            network = self[network_id]
        except KeyError:
            raise NetworkNotFound(network_id=network_id)

        for (dpid, port_no) in network:
            self.ev_q.queue(EventNetworkPort(network_id, dpid, port_no, False))
        self.ev_q.queue(EventNetworkDel(network_id))
        del self[network_id]

    def list_ports(self, network_id):
        try:
            # use list() to keep compatibility for output
            # set() isn't json serializable
            return list(self[network_id])
        except KeyError:
            raise NetworkNotFound(network_id=network_id)

    def add_raw(self, network_id, dpid, port_no):
        self[network_id].add((dpid, port_no))

    def add_event(self, network_id, dpid, port_no):
        self.ev_q.queue(EventNetworkPort(network_id, dpid, port_no, True))

    # def add(self, network_id, dpid, port_no):
    #     self.add_raw(network_id, dpid, port_no)
    #     self.add_event(network_id, dpid, port_no)

    def remove_raw(self, network_id, dpid, port_no):
        if (dpid, port_no) in self[network_id]:
            self.ev_q.queue(EventNetworkPort(network_id, dpid, port_no, False))
        self[network_id].remove((dpid, port_no))

    def remove(self, network_id, dpid, port_no):
        try:
            self.remove_raw(network_id, dpid, port_no)
        except KeyError:
            raise NetworkNotFound(network_id=network_id)
        except ValueError:
            raise PortNotFound(network_id=network_id, dpid=dpid, port=port_no)

    def has_port(self, network_id, dpid, port):
        return (dpid, port) in self[network_id]

    def get_dpids(self, network_id):
        try:
            ports = self[network_id]
        except KeyError:
            return set()

        # python 2.6 doesn't support set comprehension
        # port = (dpid, port_no)
        return set([port[0] for port in ports])


class Port(object):
    def __init__(self, port_no, network_id, mac_address=None):
        super(Port, self).__init__()
        self.port_no = port_no
        self.network_id = network_id
        self.mac_address = mac_address


class DPIDs(dict):
    """dpid -> port_no -> network_id"""
    def __init__(self, ev_q, nw_id_unknown):
        super(DPIDs, self).__init__()
        self.ev_q = ev_q
        self.nw_id_unknown = nw_id_unknown

    def setdefault_dpid(self, dpid):
        return self.setdefault(dpid, {})

    def _setdefault_network(self, dpid, port_no, default_network_id):
        dp = self.setdefault_dpid(dpid)
        return dp.setdefault(port_no, Port(port_no=port_no,
                                           network_id=default_network_id))

    def setdefault_network(self, dpid, port_no):
        self._setdefault_network(dpid, port_no, self.nw_id_unknown)

    def update_port(self, dpid, port_no, network_id):
        port = self._setdefault_network(dpid, port_no, network_id)
        port.network_id = network_id

    def remove_port(self, dpid, port_no):
        # self.dpids[dpid][port_no] can be already deleted by port_deleted()
        port = self[dpid].get(port_no)
        if port and port.network_id and port.mac_address:
            self.ev_q.queue(EventMacAddress(
                dpid, port_no, port.network_id, port.mac_address, False))

        self[dpid].pop(port_no, None)

    def get_ports(self, dpid):
        return self.get(dpid, {}).values()

    def get_port(self, dpid, port_no):
        try:
            return self[dpid][port_no]
        except KeyError:
            raise PortNotFound(dpid=dpid, port=port_no, network_id=None)

    def get_network(self, dpid, port_no):
        try:
            return self[dpid][port_no].network_id
        except KeyError:
            raise PortUnknown(dpid=dpid, port=port_no)

    def get_network_safe(self, dpid, port_no):
        port = self.get(dpid, {}).get(port_no)
        if port is None:
            return self.nw_id_unknown
        return port.network_id

    def get_mac(self, dpid, port_no):
        port = self.get_port(dpid, port_no)
        return port.mac_address

    def _set_mac(self, network_id, dpid, port_no, port, mac_address):
        if not (port.network_id is None or
                port.network_id == network_id or
                port.netowrk_id == self.nw_id_unknown):
            raise PortNotFound(network_id=network_id, dpid=dpid, port=port_no)

        port.network_id = network_id
        port.mac_address = mac_address
        if port.network_id and port.mac_address:
            self.ev_q.queue(EventMacAddress(
                dpid, port_no, port.network_id, port.mac_address, True))

    def set_mac(self, network_id, dpid, port_no, mac_address):
        port = self.get_port(dpid, port_no)
        if port.mac_address is not None:
            raise MacAddressAlreadyExist(dpid=dpid, port=port_no,
                                         mac_address=mac_address)
        self._set_mac(network_id, dpid, port_no, port, mac_address)

    def update_mac(self, network_id, dpid, port_no, mac_address):
        port = self.get_port(dpid, port_no)
        if port.mac_address is None:
            self._set_mac(network_id, dpid, port_no, port, mac_address)
            return

        # For now, we don't allow changing mac address.
        if port.mac_address != mac_address:
            raise MacAddressAlreadyExist(dpid=dpid, port=port_no,
                                         mac_address=port.mac_address)


class Network(object):
    def __init__(self, nw_id_unknown=NW_ID_UNKNOWN):
        super(Network, self).__init__()
        self.nw_id_unknown = nw_id_unknown
        ev_q = dispatcher.EventQueue(QUEUE_NAME_NETWORK_TENANT_EV,
                                     NETWORK_TENANT_EV_DISPATCHER)
        self.networks = Networks(ev_q)
        self.dpids = DPIDs(ev_q, nw_id_unknown)

    def _check_nw_id_unknown(self, network_id):
        if network_id == self.nw_id_unknown:
            raise NetworkAlreadyExist(network_id=network_id)

    def list_networks(self):
        return self.networks.list_networks()

    def update_network(self, network_id):
        self._check_nw_id_unknown(network_id)
        self.networks.update_network(network_id)

    def create_network(self, network_id):
        self._check_nw_id_unknown(network_id)
        self.networks.create_network(network_id)

    def remove_network(self, network_id):
        self.networks.remove_network(network_id)

    def list_ports(self, network_id):
        return self.networks.list_ports(network_id)

    def _update_port(self, network_id, dpid, port, port_may_exist):
        def _known_nw_id(nw_id):
            return nw_id is not None and nw_id != self.nw_id_unknown

        queue_add_event = False
        self._check_nw_id_unknown(network_id)
        try:
            old_network_id = self.dpids.get_network_safe(dpid, port)
            if (self.networks.has_port(network_id, dpid, port) or
                _known_nw_id(old_network_id)):
                if not port_may_exist:
                    raise PortAlreadyExist(network_id=network_id,
                                           dpid=dpid, port=port)

            if old_network_id != network_id:
                queue_add_event = True
                self.networks.add_raw(network_id, dpid, port)
                if _known_nw_id(old_network_id):
                    self.networks.remove_raw(old_network_id, dpid, port)
        except KeyError:
            raise NetworkNotFound(network_id=network_id)

        self.dpids.update_port(dpid, port, network_id)
        if queue_add_event:
            self.networks.add_event(network_id, dpid, port)

    def create_port(self, network_id, dpid, port):
        self._update_port(network_id, dpid, port, False)

    def update_port(self, network_id, dpid, port):
        self._update_port(network_id, dpid, port, True)

    def remove_port(self, network_id, dpid, port):
        # generate event first, then do the real task
        self.dpids.remove_port(dpid, port)
        self.networks.remove(network_id, dpid, port)

    #
    # methods for gre tunnel
    #

    def get_dpids(self, network_id):
        return self.networks.get_dpids(network_id)

    def has_network(self, network_id):
        return self.networks.has_network(network_id)

    def create_mac(self, network_id, dpid, port_no, mac_address):
        self.dpids.set_mac(network_id, dpid, port_no, mac_address)

    def update_mac(self, network_id, dpid, port_no, mac_address):
        self.dpids.update_mac(network_id, dpid, port_no, mac_address)

    def get_mac(self, dpid, port_no):
        return self.dpids.get_mac(dpid, port_no)

    def list_mac(self, dpid, port_no):
        mac_address = self.dpids.get_mac(dpid, port_no)
        if mac_address is None:
            return []
        return [mac_address]

    def get_ports(self, dpid):
        return self.dpids.get_ports(dpid)

    def get_port(self, dpid, port_no):
        return self.dpids.get_port(dpid, port_no)

    #
    # methods for simple_isolation
    #

    def same_network(self, dpid, nw_id, out_port, allow_nw_id_external=None):
        assert nw_id != self.nw_id_unknown
        out_nw = self.dpids.get_network_safe(dpid, out_port)

        if nw_id == out_nw:
            return True

        if (allow_nw_id_external is not None and
            (allow_nw_id_external == nw_id or allow_nw_id_external == out_nw)):
            # allow external network -> known network id
            return True

        LOG.debug('blocked dpid %s nw_id %s out_port %d out_nw %s'
                  'external %s',
                  dpid, nw_id, out_port, out_nw, allow_nw_id_external)
        return False

    def get_network(self, dpid, port):
        return self.dpids.get_network(dpid, port)

    def add_datapath(self, ofp_switch_features):
        datapath = ofp_switch_features.datapath
        dpid = ofp_switch_features.datapath_id
        ports = ofp_switch_features.ports
        self.dpids.setdefault_dpid(dpid)
        for port_no in ports:
            self.port_added(datapath, port_no)

    def port_added(self, datapath, port_no):
        if port_no == 0 or port_no >= datapath.ofproto.OFPP_MAX:
            # skip fake output ports
            return

        self.dpids.setdefault_network(datapath.id, port_no)

    def port_deleted(self, dpid, port_no):
        self.dpids.remove_port(dpid, port_no)

    def filter_ports(self, dpid, in_port, nw_id, allow_nw_id_external=None):
        assert nw_id != self.nw_id_unknown
        ret = []

        for port in self.get_ports(dpid):
            nw_id_ = port.network_id
            if port.port_no == in_port:
                continue

            if nw_id_ == nw_id:
                ret.append(port.port_no)
            elif (allow_nw_id_external is not None and
                  nw_id_ == allow_nw_id_external):
                ret.append(port.port_no)

        return ret
