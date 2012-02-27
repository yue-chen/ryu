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

from ryu.controller import dispatcher
from ryu.controller import handler
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_parser


class ReplyHandler(object):
    def __init__(self):
        super(ReplyHandler, self).__init__()
        self.dps = {}
        handler.register_instance(self)
        for ev_cls in ofp_event.OFP_REPLY_EVENTS:
            MAIN_DISPATCHER.register_handler(ev_cls, self._reply_handler)

    def _get_callbacks(self, datapath, ev_cls):
        dp_dict = self.dps.get(datapath, None)
        if dp_dict is None:
            return None
        return dp_dict.get(ev_cls, None)

    def _reply_handler(self, ev):
        msg = ev.msg
        callbacks = self._get_callbacks(msg.datapath, ev.__class__)
        if callbacks is None:
            return

        reply_key = (msg.version, msg.xid)
        callback = callbacks.get(reply_key, None)
        if callback is not None:
            callback(ev)

    @set_ev_cls(ofp_event.EventOFPErrorMsg, MAIN_DISPATCHER)
    def _error_msg_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        if msg.type != datapath.ofproto.OFPET_BAD_REQUEST:
            return

        error_backs = self._get_callbacks(datapath, ofp_event.EventOFPErrorMsg)
        if error_backs is None:
            return

        (version, msg_type, msg_len, xid) = ofproto_parser.header(msg.data)
        error_key = (version, msg_type, msg_len, xid)
        error_back = error_backs.get(error_key, None)
        if error_back is not None:
            error_back(ev)

    @set_ev_cls(dispatcher.EventDispatcherChange,
                dispatcher.QUEUE_EV_DISPATCHER)
    def _dispacher_change(self, ev):
        if ev.ev_q.name != handler.QUEUE_NAME_OFP_MSG:
            return
        if ev.new_dispatcher.name != handler.DISPATCHER_NAME_OFP_DEAD:
            return

        datapath = ev.ev_q.aux
        assert datapath is not None
        dead_backs = self.dps.pop(datapath, None)
        if dead_backs is None:
            return
        for dead_back in dead_backs.values():
            dead_back(ev)

    @staticmethod
    def _get_keys(msg):
        assert msg.version is not None
        assert msg.msg_type is not None
        assert msg.msg_len is not None
        assert msg.xid is not None

        reply_key = (msg.version, msg.xid)
        error_key = (msg.version, msg.msg_type, msg.msg_len, msg.xid)
        return (reply_key, error_key)

    def register(self, msg, callback, error_back, dead_back):
        (reply_key, error_key) = self._get_keys(msg)
        dp_dict = self.dps.setdefault(msg.datapath,
                                      {ofp_event.EventOFPErrorMsg: {},
                                       dispatcher.EventDispatcherChange: {}})
        reply_dict = dp_dict.setdefault(msg.cls_ev_reply, {})
        reply_dict[reply_key] = callback
        dp_dict[ofp_event.EventOFPErrorMsg][error_key] = error_back
        dp_dict[dispatcher.EventDispatcherChange][reply_key] = dead_back

    def unregister(self, msg):
        (reply_key, error_key) = self._get_keys(msg)
        dp_dict = self.dps[msg.datapath]
        del dp_dict[msg.cls_ev_reply][reply_key]
        del dp_dict[ofp_event.EventOFPErrorMsg][error_key]
        del dp_dict[dispatcher.EventDispatcherChange][reply_key]
