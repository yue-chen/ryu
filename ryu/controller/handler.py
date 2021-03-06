# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011 Isaku Yamahata <yamahata at valinux co jp>
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

import copy
import inspect
import logging
import struct

from ryu.controller import event
from ryu.controller import dispatcher
from ryu.lib.mac import haddr_to_bin

LOG = logging.getLogger('ryu.controller.handler')

handshake_dispatcher = dispatcher.EventDispatcher('handshake')
config_dispatcher = dispatcher.EventDispatcher('config')
main_dispatcher = dispatcher.EventDispatcher('main')


def set_ev_cls(ev_cls, dispatchers=None):
    def _set_ev_cls_dec(handler):
        handler.ev_cls = ev_cls
        if dispatchers is not None:
            handler.dispatchers = dispatchers
        return handler
    return _set_ev_cls_dec


def _is_ev_handler(meth):
    return 'ev_cls' in meth.__dict__


def _listify(may_list):
    if may_list is None:
        may_list = []
    if not isinstance(may_list, list):
        may_list = [may_list]
    return may_list


def _get_hnd_spec_dispatchers(handler, dispatchers):
    hnd_spec_dispatchers = _listify(getattr(handler, 'dispatchers', None))
    # LOG.debug("hnd_spec_dispatchers %s", hnd_spec_dispatchers)
    if hnd_spec_dispatchers:
        _dispatchers = copy.copy(dispatchers)
        _dispatchers.extend(hnd_spec_dispatchers)
    else:
        _dispatchers = dispatchers

    return _dispatchers


def register_cls(dispatchers=None):
    dispatchers = _listify(dispatchers)

    def _register_cls_method(cls):
        for k, f in inspect.getmembers(cls, inspect.isfunction):
            # LOG.debug('cls %s k %s f %s', cls, k, f)
            if not _is_ev_handler(f):
                continue

            _dispatchers = _get_hnd_spec_dispatchers(f, dispatchers)
            # LOG.debug("_dispatchers %s", _dispatchers)
            for d in _dispatchers:
                # LOG.debug('register dispatcher %s ev %s cls %s k %s f %s',
                #          d.name, f.ev_cls, cls, k, f)
                d.register_handler(f.ev_cls, f)

    return _register_cls_method


def register_instance(i, dispatchers=None):
    dispatchers = _listify(dispatchers)

    for k, m in inspect.getmembers(i, inspect.ismethod):
        # LOG.debug('instance %s k %s m %s', i, k, m)
        if not _is_ev_handler(m):
            continue

        _dispatchers = _get_hnd_spec_dispatchers(m, dispatchers)
        # LOG.debug("_dispatchers %s", _dispatchers)
        for d in _dispatchers:
            # LOG.debug('register dispatcher %s ev %s k %s m %s',
            #           d.name, m.ev_cls, k, m)
            d.register_handler(m.ev_cls, m)


@register_cls([handshake_dispatcher, config_dispatcher, main_dispatcher])
class EchoHandler(object):
    @staticmethod
    @set_ev_cls(event.EventOFPEchoRequest)
    def echo_request_handler(ev):
        msg = ev.msg
        # LOG.debug('echo request msg %s %s', msg, str(msg.data))
        datapath = msg.datapath
        echo_reply = datapath.ofproto_parser.OFPEchoReply(datapath)
        echo_reply.data = msg.data
        datapath.send_msg(echo_reply)

    @staticmethod
    @set_ev_cls(event.EventOFPEchoReply)
    def echo_reply_handler(ev):
        # do nothing
        # msg = ev.msg
        # LOG.debug('echo reply ev %s %s', msg, str(msg.data))
        pass


@register_cls([handshake_dispatcher, config_dispatcher, main_dispatcher])
class ErrorMsgHandler(object):
    @staticmethod
    @set_ev_cls(event.EventOFPErrorMsg)
    def error_msg_handler(ev):
        msg = ev.msg
        LOG.debug('error msg ev %s type 0x%x code 0x%x %s',
                  msg, msg.type, msg.code, str(msg.data))
        msg.datapath.is_active = False


@register_cls(handshake_dispatcher)
class HandShakeHandler(object):
    @staticmethod
    @set_ev_cls(event.EventOFPHello)
    def hello_handler(ev):
        LOG.debug('hello ev %s', ev)
        msg = ev.msg
        datapath = msg.datapath

        # TODO: check if received version is supported.
        #       pre 1.0 is not supported
        if msg.version not in datapath.supported_ofp_version:
            # send the error
            error_msg = datapath.ofproto_parser.OFPErrorMsg(datapath)
            error_msg.type = datapath.ofproto.OFPET_HELLO_FAILED
            error_msg.code = datapath.ofproto.OFPHFC_INCOMPATIBLE
            error_msg.data = 'unsupported version 0x%x' % msg.version
            datapath.send_msg(error_msg)
            return

        datapath.version = min(datapath.version_sent, msg.version)
        datapath.set_version(datapath.version)

        # now send feature
        features_reqeust = datapath.ofproto_parser.OFPFeaturesRequest(datapath)
        datapath.send_msg(features_reqeust)

        # now move on to config state
        LOG.debug('move onto config mode')
        datapath.ev_q.set_dispatcher(config_dispatcher)


@register_cls(config_dispatcher)
class ConfigHandler(object):
    @staticmethod
    @set_ev_cls(event.EventOFPSwitchFeatures)
    def switch_features_handler(ev):
        msg = ev.msg
        datapath = msg.datapath
        LOG.debug('switch features ev %s', msg)

        datapath.id = msg.datapath_id
        datapath.ports = msg.ports

        ofproto = datapath.ofproto
        ofproto_parser = datapath.ofproto_parser
        set_config = ofproto_parser.OFPSetConfig(
            datapath, ofproto.OFPC_FRAG_NORMAL,
            128  # TODO:XXX
            )
        datapath.send_msg(set_config)

        #
        # drop all flows in order to put datapath into unknown state
        #
        datapath.send_delete_all_flows()

        datapath.send_barrier()

    # The above OFPC_DELETE request may trigger flow removed event.
    # Just ignore them.
    @staticmethod
    @set_ev_cls(event.EventOFPFlowRemoved)
    def flow_removed_handler(ev):
        LOG.debug("flow removed ev %s msg %s", ev, ev.msg)

    @staticmethod
    @set_ev_cls(event.EventOFPBarrierReply)
    def barrier_reply_handler(ev):
        LOG.debug('barrier reply ev %s msg %s', ev, ev.msg)

        # move on to main state
        LOG.debug('move onto main mode')
        ev.msg.datapath.ev_q.set_dispatcher(main_dispatcher)


@register_cls(main_dispatcher)
class MainHandler(object):
    @staticmethod
    @set_ev_cls(event.EventOFPFlowRemoved)
    def flow_removed_handler(ev):
        msg = ev.msg

    @staticmethod
    @set_ev_cls(event.EventOFPPortStatus)
    def port_status_handler(ev):
        msg = ev.msg
        LOG.debug('port status %s', msg.reason)
