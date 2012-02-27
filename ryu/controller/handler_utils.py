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

# library to initialize switch which application can use

import logging

from ryu.controller import event
from ryu.controller import handler
from ryu.controller import ofp_event

LOG = logging.getLogger(__name__)


class ConfigHookDeleteAllFlowsHandler(object):
    """an initialization handler to remove all flow entries"""
    @staticmethod
    @handler.set_ev_cls(ofp_event.EventOFPDescStatsReply,
                        handler.CONFIG_HOOK_DISPATCHER)
    def message_handler(ev):
        datapath, _desc = ev.data
        # drop all flows in order to put datapath into unknown state
        datapath.send_delete_all_flows()

    # The above OFPC_DELETE request may trigger flow removed ofp_event.
    # Just ignore them.
    @staticmethod
    @handler.set_ev_cls(ofp_event.EventOFPFlowRemoved,
                        [handler.BARRIER_REQUEST_DISPATCHER,
                         handler.BARRIER_REPLY_DISPATCHER])
    def flow_removed_handler(ev):
        LOG.debug("flow removed ev %s msg %s", ev, ev.msg)


class ConfigHookOFPSetConfigHandler(object):
    """an initialization handler to to set normal mode"""
    @staticmethod
    @handler.set_ev_cls(event.EventMsg, handler.CONFIG_HOOK_DISPATCHER)
    def message_handler(ev):
        datapath, _desc = ev.data

        ofproto = datapath.ofproto
        ofproto_parser = datapath.ofproto_parser
        set_config = ofproto_parser.OFPSetConfig(
            datapath, ofproto.OFPC_FRAG_NORMAL,
            128)  # TODO:XXX 128 is app specific
        datapath.send_msg(set_config)
