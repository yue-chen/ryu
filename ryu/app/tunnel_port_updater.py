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

import gflags
import logging
import netaddr

from ryu import execption as ryu_exc
from ryu.app import conf_switch_key as cs_key
from ryu.app import rest_nw_id
from ryu.base import app_manager
from ryu.controller import (conf_switch,
                            handler,
                            network,
                            tunnels)
from ryu.lib import ovs_bridge
from ryu.lib import dpid as dpid_lib


LOG = logging.getLogger(__name__)
FLAGS = gflags.FLAGS
gflags.DEFINE_string('tunnel_type', 'gre', 'tunnel type for ovs tunnel port')

_TUNNEL_TYPE_TO_NW_ID = {
    'gre': rest_nw_id.NW_ID_VPORT_GRE,
}


class NetworkAPI(object):
    """Internal adopter class for RestAPI"""
    def __init__(self, network):
        super(NetworkAPI, self).__init__()
        self.nw = network

    def update_network(self, network_id):
        self.nw_update_network(network_id)

    def create_port(self, network_id, dpid, port_id):
        self.nw.create_port(network_id, dpid, port_id)

    def upddate_port(self, network_id, dpid, port_id):
        self.nw.update_port(network_id, dpid, port_id)

    def delete_port(self, network_id, dpid, port_id):
        try:
            self.nw.remove_port(network_id, dpid, port_id)
        except (ryu_exc.NetworkNotFound, ryu_exc.PortNotFound):
            pass


class TunnelAPI(object):
    """Internal adopter class for RestTunnelAPI"""
    def __init__(self, tunnels_):
        super(TunnelAPI, self).__init__()
        self.tunnels = tunnels_

    def update_remote_dpid(self, dpid, port_id, remote_dpid):
        self.tunnels.update_port(dpid, port_id, remote_dpid)

    def create_remote_dpid(self, dpid, port_id, remote_dpid):
        self.tunnels.create(dpid, port_id, remote_dpid)

    def delete_port(self, dpid, port_id):
        try:
            self.tunnels.delete_port(dpid, port_id)
        except ryu_exc.PortNotFound:
            pass


class TunnelPort(object):
    def __init__(self, dpid, port_no, local_ip, remote_ip, remote_dpid=None):
        super(TunnelPort, self).__init__()
        self.dpid = dpid
        self.port_no = port_no
        self.local_ip = local_ip
        self.remote_ip = remote_ip
        self.remote_dpid = remote_dpid

    def __eq__(self, other):
        return (self.dpid == other.dpid and
                self.port_no == other.port_no and
                self.local_ip == other.local_ip and
                self.remote_ip == other.remote_ip and
                self.remote_dpid == other.remote_dpid)


class TunnelDP(object):
    def __init__(self, dpid, ovsdb_addr, tunnel_ip, tunnel_type, conf_switch_,
                 network_api, tunnel_api):
        super(TunnelDP).__init__()
        self.dpid = dpid
        self.network_api = network_api
        self.tunnel_api = tunnel_api

        # TODO:XXX catch exception which OVSBridge raises, and set it null.
        #          poll connection.
        self.ovs_bridge = ovs_bridge.OVSBridge(dpid, ovsdb_addr)

        self.tunnel_ip = tunnel_ip
        self.tunnel_type = tunnel_type
        self.tunnel_nw_id = _TUNNEL_TYPE_TO_NW_ID[tunnel_type]
        self.tunnels = {}
        self._init(conf_switch_)

    def _update(self, port_no, remote_dpid):
        self.network_api.update_port(self.tunnel_nw_id, self.dpid, port_no)
        self.tunnel_api.update_remote_dpid(self.dpid, port_no, remote_dpid)

    def _init(self, conf_switch_):
        for tp in self.ovs_bridge.get_tunnel_ports(self.tunnel_type):
            if tp.local_ip != self.tunnel_ip:
                LOG.warn('unknown tunnel port %s', tp)
                continue

            remote_dpid = conf_switch_.find_dpid(cs_key.OVS_TUNNEL_ADDR,
                                                 tp.remote_ip)
            self.tunnels[tp.ofport] = TunnelPort(self.dpid, tp.ofport,
                                                 self.tunnel_ip, tp.remote_ip,
                                                 remote_dpid)
            if remote_dpid:
                self._update(tp.port_no, remote_dpid)

    def update_remote(self, remote_dpid, remote_ip):
        if self.dpid == remote_dpid:
            if self.tunnel_ip == remote_ip:
                return

            # tunnel ip address is changed.
            LOG.warn('local ip address is changed %s: %s -> %s',
                     dpid_lib.dpid_to_str(remote_dpid),
                     self.tunnel_ip, remote_ip)
            # recreate tunnel ports.
            for tp in list(self.tunnels.values()):
                if tp.remote_dpid is None:
                    # TODO:XXX
                    continue

                self.add_tunnel_port(tp.remote_dpid, tp.remote_ip)
                self._del_tunnel_port(tp.port_no, tp.local_ip, tp.remote_ip)
                # TODO:XXX notify tunnel API
            return

        if self.tunnel_ip == remote_ip:
            LOG.warn('ip conflict: %s %s %s',
                     dpid_lib.dpid_to_str(self.dpid),
                     dpid_lib.dpid_to_str(remote_dpid), remote_ip)
            # XXX
            return

        for tp in list(self.tunnels.values()):
            if tp.remote_dpid == remote_dpid:
                if tp.remote_ip == remote_ip:
                    self._update(tp.port_no, remote_dpid)
                    continue

                LOG.warn('remote ip address is changed %s: %s -> %s',
                         dpid_lib.dpid_to_str(remote_dpid),
                         tp.remote_ip, remote_ip)
                self.add_tunnel_port(remote_dpid, remote_ip)
                self._del_tunnel_port(tp.port_no,
                                      self.tunnel_ip, tp.remote_ip)
                # TODO:XXX notify tunnel API
                tp.remote_ip = remote_ip
            elif tp.remote_ip == remote_ip:
                assert tp.remote_dpid is None
                self._update(tp.port_no, remote_dpid)
                tp.remote_dpid = remote_dpid

    @staticmethod
    def _to_hex(ip_addr):
        # assuming IPv4 address
        assert netaddr.IPAddress(ip_addr).ipv4()
        return "%02x%02x%02x%02x" % netaddr.IPAddress(ip_addr).words

    @staticmethod
    def _port_name(local_ip, remote_ip):
        # ovs requires requires less or equalt to 14 bytes length
        # gre<remote>-<local lsb>
        local_hex = TunnelDP._to_hex(local_ip)
        remote_hex = TunnelDP._to_hex(remote_ip)
        length = 14 - 4 - len(local_hex)    # 4 = 'gre' + '-'
        assert length > 0
        return "gre%s-%s" % (remote_hex, local_hex[-length:])

    def _tunnel_port_exists(self, remote_dpid, remote_ip):
        return bool(tp for tp in self.tunnels.values()
                    if tp.remote_dpid == remote_dpid and
                    tp.remote_ip == remote_ip)

    def add_tunnel_port(self, remote_dpid, remote_ip):
        if self._tunnel_port_exists(remote_dpid, remote_ip):
            return

        port_name = self._port_name(self.tunnel_ip, remote_ip)
        self.ovs_bridge.add_tunnel_port(self, port_name, self.tunnel_type,
                                        self.tunnel_ip, remote_ip)

        tp = self.ovs_bridge.get_tunnel_port(port_name, self.tunnel_type)
        self.tunnels[tp.ofport] = TunnelPort(self.dpid, tp.ofport,
                                             tp.local_ip, tp.remote_ip,
                                             remote_dpid)
        self.network_api.create_port(self.tunnel_nw_id, self.dpid, tp.ofport)
        self.tunnel_api.create_remote_dpid(self.dpid, tp.ofport, remote_dpid)

    def _del_tunnel_port(self, port_no, local_ip, remote_ip):
        port_name = self._port_name(local_ip, remote_ip)
        self.ovs_bridge.del_port(port_name)
        del self.tunnels[port_no]

    def del_tunnel_port(self, remote_ip):
        for tp in self.tunnels.values():
            if tp.remote_ip == remote_ip:
                self._del_tunnel_port(tp.port_no, self.tunnel_ip, remote_ip)
                self.network_api.delete_port(self.tunnel_nw_id, self.dpid,
                                             tp.ofport)
                self.tunnel_api.delete_port(self.dpid, tp.ofport)
                break


class TunnelDPSet(dict):
    """ dpid -> TunndlDP """
    pass


class TunnelRequests(dict):
    def add(self, dpid0, dpid1):
        self.setdefault(dpid0, []).add(dpid1)
        self.setdefault(dpid1, []).add(dpid0)

    def remove(self, dpid0, dpid1):
        self[dpid0].remove(dpid1)
        self[dpid1].remove(dpid0)

    def get_remote(self, dpid):
        return self[dpid]


class TunnelPortUpdater(app_manager.RyuApp):
    _CONTEXTS = {
        'conf_switch': conf_switch.ConfSwitchSet,
        'network': network.Network,
        'tunnels': tunnels.Tunnels,
    }

    def __init__(self, *args, **kwargs):
        super(TunnelPortUpdater, self).__init__(args, kwargs)
        self.tunnel_type = FLAGS.tunnel_type
        self.cs = kwargs['conf_switch']
        self.nw = kwargs['network']
        self.tunnels = kwargs['tunnels']
        self.tunnel_dpset = TunnelDPSet()
        self.tunnel_requests = TunnelRequests()

        self.network_api = NetworkAPI(self.nw)
        self.tunnel_api = TunnelAPI(self.tunnels)
        self.network_api.update_network(
            _TUNNEL_TYPE_TO_NW_ID[self.tunnel_type])

    def _ovsdb_update(self, dpid, ovsdb_addr, ovs_tunnel_addr):
        if dpid not in self.tunnel_dpset:
            tunnel_dp = TunnelDP(dpid, ovsdb_addr, ovs_tunnel_addr,
                                 self.tunnel_type, self.cs,
                                 self.network_api, self.tunnel_api)
            self.tunnel_dpset[dpid] = tunnel_dp

        tunnel_dp = self.tunnel_dpset.get(dpid)
        assert tunnel_dp
        self._add_tunnel_ports(tunnel_dp,
                               self.tunnel_requests.get_remote(dpid))

    @handler.set_ev_cls(conf_switch.EventConfSwitchSet,
                        conf_switch.CONF_SWITCH_EV_DISPATCHER)
    def conf_switch_set_handler(self, ev):
        dpid = ev.dpid
        if (ev.key == cs_key.OVSDB_ADDR or ev.key == cs_key.OVS_TUNNEL_ADDR):
            if ((dpid, cs_key.OVSDB_ADDR) in self.cs and
                    (dpid, cs_key.OVS_TUNNEL_ADDR) in self.cs):
                self._ovsdb_update(
                    dpid, self.cs.get_key(dpid, cs_key.OVSDB_ADDR),
                    self.cs.get_key(dpid, cs_key.OVS_TUNNEL_ADDR))

        if ev.key == cs_key.OVS_TUNNEL_ADDR:
            for tunnel_dpid in self.tunnel_dpset:
                tunnel_dpid.update_remote(ev.dpid, ev.val)

    @handler.set_ev_cls(conf_switch.EventConfSwitchDel,
                        conf_switch.CONF_SWITCH_EV_DISPATCHER)
    def conf_switch_del_handler(self, ev):
        # TODO:XXX
        pass

    def _add_tunnel_ports(self, tunnel_dp, remote_dpids):
        for remote_dpid in remote_dpids:
            remote_dp = self.tunnel_dpset.get(remote_dpid)
            if remote_dp is None:
                continue
            tunnel_dp.add_tunnel_port(remote_dp.dpid, remote_dp.tunnel_ip)
            remote_dp.add_tunnel_port(tunnel_dp.dpid, tunnel_dp.tunnel_ip)

    def _vm_port_add(self, network_id, dpid):
        dpids = self.nw.get_dpids(network_id).remove(dpid)
        for remote_dpid in dpids:
            self.tunnel_requests.add(dpid, remote_dpid)

        tunnel_dp = self.tunnel_dpset.get(dpid)
        if tunnel_dp is None:
            return
        self._add_tunnel_ports(tunnel_dp, dpids)

    def _vm_port_del(self, network_id, dpid):
        if len(self.nw.get_ports(dpid, network_id)) > 1:
            return

        tunnel_networks = self.nw.get_networks(dpid).copy()
        tunnel_networks.discard(network_id)
        tunnel_networks.difference_update(set(rest_nw_id.RESERVED_NETWORK_IDS))
        dpids = self.nw.get_dpids(network_id).copy()
        dpids.discard(dpid)
        del_dpids = []
        for remote_dpid in dpids:
            if tunnel_networks & self.nw.get_networkds(remote_dpid):
                continue
            self.tunnel_requests.remove(dpid, remote_dpid)
            del_dpids.append(remote_dpid)

        tunnel_dp = self.tunnel_dpset.get(dpid)
        if tunnel_dp is None:
            return
        for remote_dpid in del_dpids:
            remote_dp = self.tunnel_dpset.get(remote_dpid)
            if remote_dp is None:
                continue
            tunnel_dp.del_tunnel_port(remote_dp.tunnel_ip)
            remote_dp.del_tunnel_port(tunnel_dp.tunnel_ip)

    @handler.set_ev_cls(network.EventNetworkPort,
                        network.NETWORK_TENANT_EV_DISPATCHER)
    def network_port_handler(self, ev):
        if ev.network_id in rest_nw_id.RESERVED_NETWORK_IDS:
            return

        if ev.add_del:
            self._vm_port_add(ev.network_id, ev.dpid)
        else:
            self._vm_port_del(ev.network_id, ev.dpid)
