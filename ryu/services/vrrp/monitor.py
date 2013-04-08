# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2013 Isaku Yamahata <yamahata at private email ne jp>
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
"""
Interface monitor.
Watching packet recevined on this interface and parse VRRP packet.
"""

from ryu.base import app_manager
from ryu.controller import handler
from ryu.controller import ofp_event
from ryu.lib import dpid as dpid_lib
from ryu.lib.packet import packet
from ryu.lib.packet import vlan
from ryu.lib.packet import vrrp
from ryu.ofproto import ether
from ryu.ofproto import inet
from ryu.ofproto import ofproto_v1_2
from ryu.ofproto import ofproto_v1_3
from ryu.services.vrrp import event as vrrp_event
from ryu.services.vrrp import utils


class VRRPInterfaceMonitor(app_manager.RyuApp):
    # subclass of VRRPInterfaceBase -> subclass of VRRPInterfaceMonitor
    _CONSTRUCTORS = {}

    @staticmethod
    def register(interface_cls):
        def _register(cls):
            VRRPInterfaceMonitor._CONSTRUCTORS[interface_cls] = cls
            return cls
        return _register

    @staticmethod
    def factory(interface, config, router_name, *args, **kwargs):
        cls = VRRPInterfaceMonitor._CONSTRUCTORS[interface.__class__]
        app_mgr = app_manager.AppManager.get_instance()

        kwargs = kwargs.copy()
        kwargs['router_name'] = router_name
        kwargs['vrrp_config'] = config
        kwargs['vrrp_interface'] = interface
        app = app_mgr.instantiate(cls, *args, **kwargs)
        return app

    @classmethod
    def instance_name(cls, interface, vrid):
        return '%s-%s-%d' % (cls.__name__, str(interface), vrid)

    def __init__(self, *args, **kwargs):
        super(VRRPInterfaceMonitor, self).__init__(*args, **kwargs)
        self.config = kwargs['vrrp_config']
        self.interface = kwargs['vrrp_interface']
        self.router_name = kwargs['router_name']
        self.name = self.instance_name(self.interface, self.config.vrid)

    def _send_vrrp_packet_received(self, packet_data):
        # OF doesn't support VRRP packet matching, so we have to parse
        # it ourselvs.
        packet_ = packet.Packet(packet_data)
        protocols = packet_.protocols
        if len(protocols) < 2:
            self.logger.debug('len(protocols) %d', len(protocols))
            return

        vlan_vid = self.interface.vlan_id
        may_vlan = protocols[1]
        if (vlan_vid is not None) != isinstance(may_vlan, vlan.vlan):
            self.logger.debug('vlan_vid: %s %s', vlan_vid, type(may_vlan))
            return
        if vlan_vid is not None and vlan_vid != may_vlan.vid:
            self.logger.debug('vlan_vid: %s vlan %s', vlan_vid, type(may_vlan))
            return

        may_ip, may_vrrp = vrrp.vrrp.get_payload(packet_)
        if not may_ip or not may_vrrp:
            self.logger.debug('may_ip %s may_vrrp %s', may_ip, may_vrrp)
            return
        if not vrrp.vrrp.is_valid_ttl(may_ip):
            self.logger.debug('valid_ttl')
            return
        if may_vrrp.version != self.config.version:
            self.logger.debug('vrrp version %d %d',
                              may_vrrp.version, self.config.version)
            return
        if not may_vrrp.is_valid():
            self.logger.debug('valid vrrp')
            return
        offset = 0
        for proto in packet_.protocols:
            if proto == may_vrrp:
                break
            offset += proto.length
        if not may_vrrp.checksum_ok(
                may_ip, packet_.data[offset:offset + may_vrrp.length]):
            self.logger.debug('bad checksum')
            return
        if may_vrrp.vrid != self.config.vrid:
            self.logger.debug('vrid %d %d', may_vrrp.vrid, self.config.vrid)
            return
        if may_vrrp.is_ipv6 != self.config.is_ipv6:
            self.logger.debug('is_ipv6 %s %s',
                              may_vrrp.is_ipv6, self.config.is_ipv6)
            return

        # TODO: Optional check rfc5798 7.1
        # may_vrrp.ip_addresses equals to self.config.ip_addresses

        vrrp_received = vrrp_event.EventVRRPReceived(self.interface, packet_)
        self.send_event(self.router_name, vrrp_received)

    @handler.set_ev_handler(vrrp_event.EventVRRPTransmitRequest)
    def vrrp_transmit_request_handler(self, ev):
        raise NotImplementedError()

    def _initialize(self):
        raise NotImplementedError()

    def _shutdown(self):
        raise NotImplementedError()

    @handler.set_ev_handler(vrrp_event.EventVRRPStateChanged)
    def vrrp_state_changed_handler(self, ev):
        assert ev.interface == self.interface

        if ev.new_state == vrrp_event.VRRP_STATE_INITIALIZE:
            # add/del packet in rule
            if ev.old_state:
                self._shutdown()
            else:
                self._initialize()
        elif ev.new_state in [vrrp_event.VRRP_STATE_BACKUP,
                              vrrp_event.VRRP_STATE_MASTER]:
            pass
        else:
            raise RuntimeError('unknown vrrp state %s' % ev.new_state)


@VRRPInterfaceMonitor.register(vrrp_event.VRRPInterfaceOpenFlow)
class VRRPInterfaceMonitorOpenFlow(VRRPInterfaceMonitor):
    # OF1.2
    OFP_VERSIONS = [ofproto_v1_2.OFP_VERSION,
                    ofproto_v1_3.OFP_VERSION]   # probably work with OF1.3

    _TABLE = 0          # generate packet-in in this table
    _PRIORITY = 0x8000  # default priority

    def __init__(self, *args, **kwargs):
        super(VRRPInterfaceMonitorOpenFlow, self).__init__(*args, **kwargs)
        table = kwargs.get('vrrp_imof_table', None)
        if table is not None:
            self._TABLE = int(table)
        priority = kwargs.get('vrrp_imof_priority', None)
        if priority is not None:
            self._PRIORITY = int(priority)

    @handler.set_ev_cls(ofp_event.EventOFPPacketIn, handler.MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        self.logger.debug('packet_in_handler')
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto

        # TODO: subscribe only the designated datapath
        dpid = datapath.id
        if dpid != self.interface.dpid:
            self.logger.debug('packet_in_handler dpid %s %s',
                              dpid_lib.dpid_to_str(dpid),
                              dpid_lib.dpid_to_str(self.interface.dpid))
            return

        in_port = None
        for field in msg.match.fields:
            if field.header == ofproto.OXM_OF_IN_PORT:
                in_port = field.value
                break

        if in_port != self.interface.port_no:
            self.logger.debug('packet_in_handler in_port %s %s',
                              in_port, self.interface.port_no)
            return

        self._send_vrrp_packet_received(msg.data)

    def _get_dp(self):
        return utils.get_dp(self, self.interface.dpid)

    @handler.set_ev_handler(vrrp_event.EventVRRPTransmitRequest)
    def vrrp_transmit_request_handler(self, ev):
        dp = self._get_dp()
        if not dp:
            return
        utils.dp_packet_out(dp, self.interface.port_no, ev.data)

    def _ofp_match(self, ofproto_parser):
        match = ofproto_parser.OFPMatch()
        match.set_in_port(self.interface.port_no)
        is_ipv6 = vrrp.is_ipv6(self.config.ip_addresses[0])
        if is_ipv6:
            match.set_dl_dst(vrrp.VRRP_IPV6_DST_MAC_ADDRESS)
            match.set_dl_src(vrrp.vrrp_ipv6_src_mac_address(self.config.vrid))
            match.set_dl_type(ether.ETH_TYPE_IPV6)
            match.set_ipv6_dst(vrrp.VRRP_IPV6_DST_ADDRESS)
        else:
            match.set_dl_dst(vrrp.VRRP_IPV4_DST_MAC_ADDRESS)
            match.set_dl_src(vrrp.vrrp_ipv4_src_mac_address(self.config.vrid))
            match.set_dl_type(ether.ETH_TYPE_IP)
            match.set_ipv4_dst(vrrp.VRRP_IPV4_DST_ADDRESS)

        if self.interface.vlan_id is not None:
            match.set_vlan_vid(self.interface.vlan_id)
        match.set_ip_proto(inet.IPPROTO_VRRP)
        # OF1.2 doesn't support TTL match.
        # It needs to be checked by packet in handler

        return match

    def _initialize(self):
        dp = self._get_dp()
        if not dp:
            return

        ofproto = dp.ofproto
        ofproto_parser = dp.ofproto_parser

        match = self._ofp_match(ofproto_parser)
        utils.dp_flow_mod(dp, self._TABLE, ofproto.OFPFC_DELETE_STRICT,
                          self._PRIORITY, match, [],
                          out_port=ofproto.OFPP_CONTROLLER)

        match = self._ofp_match(ofproto_parser)
        actions = [ofproto_parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                                  ofproto.OFPCML_NO_BUFFER)]
        instructions = [ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        utils.dp_flow_mod(dp, self._TABLE, ofproto.OFPFC_ADD, self._PRIORITY,
                          match, instructions)

    def _shutdown(self):
        dp = self._get_dp()
        if not dp:
            return

        ofproto = dp.ofproto
        match = self._ofp_match(dp.ofproto_parser)
        utils.dp_flow_mod(dp, self._TABLE, ofproto.OFPFC_DELETE_STRICT,
                          self._PRIORITY, match, [],
                          out_port=ofproto.OFPP_CONTROLLER)
