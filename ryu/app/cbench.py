# Copyright (C) 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2012 Isaku Yamahata <yamahata at valinux co jp>

import logging

from ryu.controller import event
from ryu.controller import ofp_event
from ryu.controller.handler import BARRIER_REQUEST_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import nx_match

LOG = logging.getLogger(__name__)


class Cbench(object):
    def __init__(self, *_args, **kwargs):
        super(Cbench, self).__init__()

    @set_ev_cls(event.EventMsg, BARRIER_REQUEST_DISPATCHER)
    def message_handler(self, ev):
        datapath, _desc = ev.data

        # cbench doesn't work as is because it ignores the barrier request.
        # So queue barrier reply event artificially as work around
        barrier_reply = datapath.ofproto_parser.OFPBarrierReply(datapath)
        datapath.ev_q.queue(ofp_event.EventOFPBarrierReply(barrier_reply))

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto

        rule = nx_match.ClsRule()
        datapath.send_flow_mod(
            rule=rule, cookie=0, command=ofproto.OFPFC_ADD,
            idle_timeout=0, hard_timeout=0,
            priority=ofproto.OFP_DEFAULT_PRIORITY, flags=0, actions=None)
