# Copyright (C) 2011, 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011, 2012 Isaku Yamahata <yamahata at valinux co jp>
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

from ryu.controller.switch_features import SwitchFeatures
from ryu.controller import dispatcher
from ryu.controller import event
from ryu.controller import ofp_event

LOG = logging.getLogger('ryu.controller.handler')

QUEUE_NAME_OFP_MSG = 'ofp_msg'
DISPATCHER_NAME_OFP_HANDSHAKE = 'ofp_handshake'
HANDSHAKE_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_OFP_HANDSHAKE)
DISPATCHER_NAME_OFP_SWITCH_FEATURES = 'ofp_switch_features'
SWITCH_FEATURES_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_OFP_SWITCH_FEATURES)
DISPATCHER_NAME_OFP_DESC = 'ofp_desc'
DESC_DISPATCHER = dispatcher.EventDispatcher(DISPATCHER_NAME_OFP_DESC)
DISPATCHER_NAME_OFP_CONFIG_HOOK = 'ofp_config_hook'
CONFIG_HOOK_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_OFP_CONFIG_HOOK)
DISPATCHER_NAME_BARRIER_REQUEST = 'ofp_barrier_request'
BARRIER_REQUEST_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_BARRIER_REQUEST)
DISPATCHER_NAME_OFP_BARRIER_REPLY = 'ofp_barrier_reply'
BARRIER_REPLY_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_OFP_BARRIER_REPLY)
DISPATCHER_NAME_OFP_MAIN = 'ofp_main'
MAIN_DISPATCHER = dispatcher.EventDispatcher(DISPATCHER_NAME_OFP_MAIN)
DISPATCHER_NAME_OFP_DEAD = 'ofp_dead'
DEAD_DISPATCHER = dispatcher.EventDispatcher(DISPATCHER_NAME_OFP_DEAD)

ALL_HANDLERS = [HANDSHAKE_DISPATCHER,
                SWITCH_FEATURES_DISPATCHER,
                DESC_DISPATCHER,
                CONFIG_HOOK_DISPATCHER,
                BARRIER_REQUEST_DISPATCHER,
                BARRIER_REPLY_DISPATCHER,
                MAIN_DISPATCHER]


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


def register_cls_object(cls, dispatchers=None):
    dispatchers = _listify(dispatchers)
    for _key, func in inspect.getmembers(cls, inspect.isfunction):
        # LOG.debug('cls %s k %s func %s', cls, _key, func)
        if not _is_ev_handler(func):
            continue

        dispatchers = _get_hnd_spec_dispatchers(func, dispatchers)
        # LOG.debug("dispatchers %s", dispatchers)
        for disp in dispatchers:
            # LOG.debug('register dispatcher %s ev %s cls %s k %s func %s',
            #           disp.name, func.ev_cls, cls, k, func)
            disp.register_handler(func.ev_cls, func)


def register_cls(dispatchers=None):

    def _register_cls_method(cls):
        register_cls_object(cls, dispatchers)
        return cls

    return _register_cls_method


def register_instance(i, dispatchers=None):
    dispatchers = _listify(dispatchers)

    for _k, m in inspect.getmembers(i, inspect.ismethod):
        # LOG.debug('instance %s k %s m %s', i, _k, m)
        if not _is_ev_handler(m):
            continue

        _dispatchers = _get_hnd_spec_dispatchers(m, dispatchers)
        # LOG.debug("_dispatchers %s", _dispatchers)
        for d in _dispatchers:
            # LOG.debug('register dispatcher %s ev %s k %s m %s',
            #           d.name, m.ev_cls, _k, m)
            d.register_handler(m.ev_cls, m)


@register_cls(ALL_HANDLERS)
class EchoHandler(object):
    @staticmethod
    @set_ev_cls(ofp_event.EventOFPEchoRequest)
    def echo_request_handler(ev):
        msg = ev.msg
        # LOG.debug('echo request msg %s %s', msg, str(msg.data))
        datapath = msg.datapath
        echo_reply = datapath.ofproto_parser.OFPEchoReply(datapath)
        echo_reply.xid = msg.xid
        echo_reply.data = msg.data
        datapath.send_msg(echo_reply)

    @staticmethod
    @set_ev_cls(ofp_event.EventOFPEchoReply)
    def echo_reply_handler(ev):
        # do nothing
        # msg = ev.msg
        # LOG.debug('echo reply ev %s %s', msg, str(msg.data))
        pass


@register_cls(ALL_HANDLERS)
class ErrorMsgHandler(object):
    @staticmethod
    @set_ev_cls(ofp_event.EventOFPErrorMsg)
    def error_msg_handler(ev):
        msg = ev.msg
        LOG.debug('error msg ev %s type 0x%x code 0x%x %s',
                  msg, msg.type, msg.code, str(msg.data))
        msg.datapath.is_active = False


@register_cls(HANDSHAKE_DISPATCHER)
class HandShakeHandler(object):
    @staticmethod
    @set_ev_cls(ofp_event.EventOFPHello)
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

        # should we again send HELLO with the version that the switch
        # supports?
        # msg.version != datapath.ofproto.OFP_VERSION:

        datapath.set_version(msg.version)

        # now send feature
        features_reqeust = datapath.ofproto_parser.OFPFeaturesRequest(datapath)
        datapath.send_msg(features_reqeust)

        # now move on to switch feature state
        LOG.debug('move onto switch feature mode')
        datapath.ev_q.set_dispatcher(SWITCH_FEATURES_DISPATCHER)


@register_cls(SWITCH_FEATURES_DISPATCHER)
class SwitchFeaturesHandler(object):
    @staticmethod
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures)
    def switch_features_handler(ev):
        msg = ev.msg
        datapath = msg.datapath
        LOG.debug('switch features ev %s', msg)

        datapath.id = msg.datapath_id
        datapath.ports = msg.ports
        datapath.features = SwitchFeatures(msg)

        # send desc stats request to get description of the switch,
        # then know the switch vendor
        desc_stats_request = datapath.ofproto_parser.OFPDescStatsRequest(
            datapath, 0)
        datapath.send_msg(desc_stats_request)

        LOG.debug('move onto desc mode')
        datapath.ev_q.set_dispatcher(DESC_DISPATCHER)


@register_cls(DESC_DISPATCHER)
class DescHandler(object):
    @staticmethod
    @set_ev_cls(ofp_event.EventOFPDescStatsReply)
    def desc_stats_reply_handler(ev):
        msg = ev.msg
        datapath = msg.datapath
        ev_q = datapath.ev_q
        LOG.debug('move onto config mode')
        ev_q.set_dispatcher(CONFIG_HOOK_DISPATCHER)
        ev_q.queue(event.EventMsg(str(DescHandler), None,
                                  (datapath, msg.body)))


@register_cls(CONFIG_HOOK_DISPATCHER)
class ConfigHookHandler(object):
    @staticmethod
    @set_ev_cls(event.EventMsg)
    def message_handler(ev):
        datapath, _desc = ev.data
        ev_q = datapath.ev_q

        LOG.debug('move onto barrier request mode')
        ev_q.set_dispatcher(BARRIER_REQUEST_DISPATCHER)
        ev_q.queue(event.EventMsg(str(ConfigHookHandler), None, ev.data))


@register_cls(BARRIER_REQUEST_DISPATCHER)
class BarrierRequestHandler(object):
    @staticmethod
    @set_ev_cls(event.EventMsg)
    def message_handler(ev):
        datapath, _desc = ev.data

        # to wait for messages sent by CONFIG_HOOK_DISPATCHER to be processed
        LOG.debug('move onto barrier reply mode')
        datapath.ev_q.set_dispatcher(BARRIER_REPLY_DISPATCHER)
        datapath.send_barrier()


@register_cls(BARRIER_REPLY_DISPATCHER)
class BarrierReplyHandler(object):
    @staticmethod
    @set_ev_cls(ofp_event.EventOFPBarrierReply)
    def barrier_reply_handler(ev):
        LOG.debug('move onto main mode')
        ev.msg.datapath.ev_q.set_dispatcher(MAIN_DISPATCHER)


@register_cls(MAIN_DISPATCHER)
class MainHandler(object):
    @staticmethod
    @set_ev_cls(ofp_event.EventOFPPortStatus)
    def port_status_handler(ev):
        msg = ev.msg
        LOG.debug('port status %s', msg.reason)

        msg = ev.msg
        reason = msg.reason
        port = msg.desc
        datapath = msg.datapath
        ofproto = datapath.ofproto

        if reason == ofproto.OFPPR_ADD:
            datapath.ports[port.port_no] = port
        elif reason == ofproto.OFPPR_DELETE:
            del datapath.ports[port.port_no]
        else:
            assert reason == ofproto.OFPPR_MODIFY
            datapath.ports[port.port_no] = port
