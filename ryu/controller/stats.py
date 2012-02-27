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

import gevent
import logging

from ryu import exception as ryu_exception


LOG = logging.getLogger(__name__)


# TODO:XXX What default timeout is appropriate?
#                                  configurable? adaptive to datapath?
_DEFAULT_TIMEOUT = 1.0


def _do_send_request(datapath, reply_handler, msg, is_last_fn, timeout):
    async_result = gevent.event.AsyncResult()
    ret_msgs = []

    def callback(ev):
        msg_ = ev.msg
        ret_msgs.append(msg_)
        if is_last_fn(msg_):
            reply_handler.unregister(msg)
            async_result.set(ret_msgs)

    def error_back(ev):
        reply_handler.unregister(msg)

        msg_ = ev.msg
        exc = ryu_exception.OFPErrorMessage(ev, type=msg_.type, code=msg_.code)
        async_result.set_exception(exc)

    def dead_back(ev):
        reply_handler.unregister(msg)
        exc = ryu_exception.OFPDatapathDisconnected(ev, id=datapath.id)
        async_result.set_exception(exc)

    datapath.serialize_msg(msg)  # to set xid and msg_len which
                                 # reply_handler.register() requires
    reply_handler.register(msg, callback, error_back, dead_back)
    datapath.send(msg.buf)
    try:
        return async_result.get(timeout=timeout)
    except gevent.Timeout:
        reply_handler.unregister(msg)
        raise


# one shot return
def _send_request(datapath, reply_handler, msg, timeout):
    ret = _do_send_request(datapath, reply_handler, msg, lambda msg_: True,
                           timeout)
    return ret[0]


# for stats request
def _send_stats_request(datapath, reply_handler, msg, timeout):
    def is_last_fn(msg_):
        return not (msg_.flags & datapath.ofproto.OFPSF_REPLY_MORE)

    return _do_send_request(datapath, reply_handler, msg, is_last_fn, timeout)


def request_queue_config(datapath, reply_handler, port_no,
                         timeout=_DEFAULT_TIMEOUT):
    queue_get_config = datapath.ofproto_parser.OFPQueueGetConfigRequest(
        datapath, port_no)
    return _send_request(datapath, reply_handler, queue_get_config, timeout)


def request_desc_stats(datapath, reply_handler, timeout=_DEFAULT_TIMEOUT):
    desc_stats = datapath.ofproto_parser.OFPDescStatsRequest(datapath, 0)
    msgs = _send_stats_request(datapath, reply_handler, desc_stats, timeout)
    # assuming that ofp_desc_stats doesn't carry OFPSF_REPLY_MORE
    return msgs[0].body


def _request_stats_array(datapath, reply_handler, msg, timeout):
    msgs = _send_stats_request(datapath, reply_handler, msg, timeout)
    body = []
    for m in msgs:
        body.extend(m.body)
    return body


def request_table_stats(datapath, reply_handler, timeout=_DEFAULT_TIMEOUT):
    table_stats = datapath.ofproto_parser.OFPTableStatsRequest(datapath, 0)
    return _request_stats_array(datapath, reply_handler, table_stats, timeout)


def request_port_stats(datapath, reply_handler, port_no,
                       timeout=_DEFAULT_TIMEOUT):
    port_stats = datapath.ofproto_parser.OFPPortStatsRequest(datapath,
                                                             0, port_no)
    return _request_stats_array(datapath, reply_handler, port_stats, timeout)


def request_queue_stats(datapath, reply_handler, port_no, queue_id,
                        timeout=_DEFAULT_TIMEOUT):
    queue_stats = datapath.ofproto_parser.OFPQueueStatsRequest(
        datapath, 0, port_no, queue_id)
    return _request_stats_array(datapath, reply_handler, queue_stats, timeout)
