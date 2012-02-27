# Copyright (C) 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2012 Isaku Yamahata <yamahata at valinux co jp>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# application which enables open vswtich nx extension

import logging

from ryu.controller import handler
from ryu.controller import ofp_event
from ryu.ofproto import classifier
from ryu.ofproto import ofproto_v1_0
from ryu.ofproto.desc import desc_equal

LOG = logging.getLogger(__name__)

# Open vSwtich
MFR_DESC_NICIRA = 'Nicira Networks, Inc.'
HW_DESC_OPENVSWITCH = 'Open vSwitch'
SERIAL_NUM_OPENVSWITCH = 'None'
DP_DESC_OPENVSWITCH = 'None'


@handler.register_cls()
class NXEnablerHandler(object):
    @staticmethod
    def is_nx_switch(desc):
        return desc_equal(desc, mfr_desc=MFR_DESC_NICIRA,
                          hw_desc=HW_DESC_OPENVSWITCH)

    @staticmethod
    def nx_enable(datapath):
        LOG.debug('enabling nx extension')
        # now nxt set flow format vendor message
        #
        # XXX: If NXFF_NXM is not supported by the swtich then a
        # OFPT_ERROR:OFPBRC_EPERM message will be recieved.  It can just be
        # ignored but currently isn't.  This needs to be fixed
        set_format = datapath.ofproto_parser.NXTSetFlowFormat(
            datapath, ofproto_v1_0.NXFF_NXM)
        datapath.send_msg(set_format)

        # now nxt set packet in format vendor message
        #
        # XXX: If NXPIF_NXM is not supported by the swtich then a
        # OFPT_ERROR:OFPBRC_EPERM message will be recieved.  It can just be
        # ignored but currently isn't.  This needs to be fixed
        set_format = datapath.ofproto_parser.NXTSetPacketInFormat(
            datapath, ofproto_v1_0.NXPIF_NXM)
        datapath.send_msg(set_format)

        # now send barrier to see if NXTSetFlowFormat and NXTSetPacketInFormat
        # doesn't return error
        datapath.send_barrier()

        # Add Flow
        out_port = 0
        rule = classifier.ClsRule()
        rule.set_in_port(1)
        rule.set_tun_id(64)
        actions = [datapath.ofproto_parser.OFPActionOutput(out_port)]
        flow_mod = datapath.ofproto_parser.NXTFlowMod(datapath, 0,
                                                      ofproto_v1_0.OFPFC_ADD,
                                                      60, 60, 0, 0, out_port,
                                                      0, rule, actions)
        datapath.send_msg(flow_mod)

    @staticmethod
    @handler.set_ev_cls(ofp_event.EventOFPDescStatsReply,
                        handler.CONFIG_HOOK_DISPATCHER)
    def message_handler(ev):
        datapath, desc = ev.data
        if (NXEnablerHandler.is_nx_switch(desc)):
            NXEnablerHandler.nx_enable(datapath)

    @staticmethod
    @handler.set_ev_cls(ofp_event.EventOFPErrorMsg,
                        [handler.BARRIER_REQUEST_DISPATCHER,
                         handler.BARRIER_REPLY_DISPATCHER])
    def error_msg_handler(ev):
        # TODO:XXX
        # Check if this error message is ours and handle error somehow.
        # abandon to enable nx extension?
        LOG.error('nx error: ev %s %s', ev, ev.msg)

    @staticmethod
    @handler.set_ev_cls(ofp_event.EventOFPBarrierReply,
                        handler.BARRIER_REPLY_DISPATCHER)
    def barrier_reply_handler(ev):
        # TODO:XXX check if error message wasn't received
        LOG.debug('nx enabled')


class NXEnabler(object):
    """dummy app to load NXEnablerHandler"""
    def __init__(self, *args, **kwargs):
        super(NXEnableer, self).__init__()
