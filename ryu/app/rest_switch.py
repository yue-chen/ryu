# Copyright (C) 2012 Isaku Yamahata <yamahata at valinux co jp>
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
import httplib
import json
import logging

from ryu.app.wsapi import WSPathComponent
from ryu.app.wsapi import WSPathExtractResult
from ryu.app.wsapi import WSPathStaticString
from ryu.app.wsapi import wsapi
from ryu.controller import dp_type
from ryu.exception import PortUnknown
from ryu.lib import mac


LOG = logging.getLogger('ryu.app.rest_switch')

# REST API for switch status
# query switch for various infos
#
# get the list of switches
# GET /v1.0/switches
#
# get the feature of a given switch
# GET /v1.0/switches/<dpid>
#
# get the type of a given switch
# GET /v1.0/switches/<dpid>/type
#
# get the advertised version of a given switch
# GET /v1.0/switches/<dpid>/version
#
# get the using version of a given switch
# GET /v1.0/switches/<dpid>/current_version
#
# get the desc stats of a given switch
# GET /v1.0/switches/<dpid>/stats/desc
#
# get the table stats of a given switch
# GET /v1.0/switches/<dpid>/stats/tables
#
# get the list of ports of a given switch
# GET /v1.0/switches/<dpid>/ports
#
# get the port info of a given port
# GET /v1.0/switches/<dpid>/ports/<port-no>
#
# get the type of a given port
# GET /v1.0/switches/<dpid>/ports/<port-no>/type
#
# get the network id of a given port
# GET /v1.0/switches/<dpid>/ports/<port-no>/network_id
#
# get the port stats of a given port
# GET /v1.0/switches/<dpid>/ports/<port-no>/stats
#
# get the list of queues of a given port
# GET /v1.0/switches/<dpid>/ports/<port-no>/queues
#
# get the properties of a given queue
# GET /v1.0/switches/<dpid>/ports/<port-no>/queues/<queue-id>/properties
#
# get the queue stats of a given queue
# GET /v1.0/switches/<dpid>/ports/<port-no>/queues/<queue-id>/stats
#
# where
# <dpid>: datapath id in 16 hex
# <port-no>: port no in digit
# <queue_id>: queue id in digit


_DPID_LEN = 16
_DPID_FMT = '%0' + str(_DPID_LEN) + 'x'


class WSPathSwitch(WSPathComponent):
    """ Match a switch id string """

    def __str__(self):
        return '{dpid}'

    def extract(self, pc, _data):
        if pc == None:
            return WSPathExtractResult(error='End of requested URI')
        if len(pc) != _DPID_LEN:
            return WSPathExtractResult(error='Invalid format: %s' % pc)

        try:
            dpid = int(pc, 16)
        except ValueError:
            return WSPathExtractResult(error='Invalid format: %s' % pc)

        return WSPathExtractResult(value=dpid)


class WSPathPort(WSPathComponent):
    """ Match a {port-no} number """

    def __str__(self):
        return '{port-no}'

    def extract(self, pc, _data):
        if pc == None:
            return WSPathExtractResult(error='End of requested URI')

        try:
            port_no = int(pc)
        except ValueError:
            return WSPathExtractResult(error='Invalid format: %s' % pc)

        return WSPathExtractResult(value=port_no)


class WSPathQueue(WSPathComponent):
    """ Match a {queue-id} number """

    def __str__(self):
        return '{queue-id}'

    def extract(self, pc, _data):
        if pc == None:
            return WSPathExtractResult(error='End of requested URI')

        try:
            queue_id = int(pc)
        except ValueError:
            return WSPathExtractResult(error='Invalid format: %s' % pc)

        return WSPathExtractResult(value=queue_id)


class SwitchStatusController(object):
    def __init__(self, *_args, **kwargs):
        self.nw = kwargs['network']
        self.dpset = kwargs['dpset']

        self.ws = wsapi()
        self.api = self.ws.get_version('1.0')
        self._register()

    def list_switches(self, request, data):
        request.setHeader('Content-Type', 'application/json')
        return json.dumps([_DPID_FMT % dp_id for dp_id, dp in
                           self.dpset.get_all()])

    def _do_dp(self, request, data, func):
        request.setHeader('Content-Type', 'application/json')
        dpid = data['{dpid}']

        dp = self.dpset.get(dpid)
        if dp is None:
            request.setResponseCode(httplib.NOT_FOUND)
            return 'dpid %s is not founf' % dpid

        return func(dp)

    def get_switch(self, request, data):
        LOG.debug('get_sw %s %s', request, data)

        def do_features(dp):
            return json.dumps(dp.features)

        return self._do_dp(request, data, do_features)

    def get_switch_type(self, request, data):
        def do_type(dp):
            dp_type_ = getattr(dp, 'dp_type', dp_type.UNKNOWN)
            return json.dumps(dp_type_)
        return self._do_dp(request, data, do_type)

    def get_switch_current_version(self, request, data):
        LOG.debug('get_sw_current_version %s %s', request, data)

        def do_cur_version(dp):
            return json.dumps(dp.ofproto.OFP_VERSION)
        return self._do_dp(request, data, do_cur_version)

    def get_switch_desc_stats(self, request, data):
        LOG.debug('get_sw_desc_stats %s %s', request, data)

        def do_desc_stats(dp):
            desc = dp.request_desc_stats()
            return json.dumps(desc)
        return self._do_dp(request, data, do_desc_stats)

    def get_switch_tables_stats(self, request, data):
        LOG.debug('get_sw_table_stats %s %s', request, data)

        def do_tables_stats(dp):
            LOG.debug('dp_table_stats %s %s', request, data)
            tables = dp.request_table_stats()
            LOG.debug('tables %s', tables)
            return json.dumps([t._asdict() for t in tables])
        return self._do_dp(request, data, do_tables_stats)

    def list_switch_ports(self, request, data):
        LOG.debug('list_swtich_ports %s %s', request, data)

        def do_ports(dp):
            return json.dumps(dp.ports.keys())
        return self._do_dp(request, data, do_ports)

    def _do_port(self, request, data, func):
        request.setHeader('Content-Type', 'application/json')
        dpid = data['{dpid}']
        port_no = data['{port-no}']

        dp = self.dpset.get(dpid)
        if dp is None:
            request.setResponseCode(httplib.NOT_FOUND)
            return 'dpid %s is not found' % dpid

        port = dp.ports.get(port_no, None)
        if port is None:
            request.setResponseCode(httplib.NOT_FOUND)
            return 'dpid %s port %d is not found' % (dpid, port_no)

        return func(dp, port)

    def get_port(self, request, data):
        LOG.debug('get_port %s %s', request, data)

        # TODO:XXX symbolic representation instead of OFP dependent value
        def do_port(dp, port):
            d = port._asdict()
            d['hw_addr'] = mac.haddr_to_str(d['hw_addr'])
            return json.dumps(d)
        return self._do_port(request, data, do_port)

    def get_port_type(self, request, data):
        LOG.debug('get_port_type %s %s', request, data)

        def do_type(dp, port):
            port_type = getattr(port, 'port_type', 'UNKNOWN')
            return json.dumps(port_type)
        return self._do_port(request, data, do_type)

    def get_port_network_id(self, request, data):
        LOG.debug('get_port_network_id %s %s', request, data)

        def do_network_id(dp, port):
            try:
                return self.nw.get_network(dp.id, port)
            except PortUnknown:
                return self.nw.nw_id_unknown
        return self._do_port(request, data, do_network_id)

    def get_port_stats(self, request, data):
        LOG.debug('get_port_stats %s %s', request, data)

        def do_stats(dp, port):
            LOG.debug('reqeust_port_stats %s %s', request, data)
            ports = dp.request_port_stats(port.port_no)
            LOG.debug('ports %s', ports)
            return json.dumps(ports[0]._asdict())
        return self._do_port(request, data, do_stats)

    def get_queues(self, request, data):
        LOG.debug('get_queues %s %s', request, data)

        def do_get_queues(dp, port):
            queue_config = dp.request_queue_config(port.port_no)
            LOG.debug('queue_config %s', queue_config)
            return json.dumps([q.queue_id for q in queue_config.queues])
        return self._do_port(request, data, do_get_queues)

    def _do_queue(self, request, data, func):
        request.setHeader('Content-Type', 'application/json')
        dpid = data['{dpid}']
        port_no = data['{port-no}']
        queue_id = data['{queue-id}']

        dp = self.dpset.get(dpid)
        if dp is None:
            request.setResponseCode(httplib.NOT_FOUND)
            return 'dpid %s is not found' % dpid

        port = dp.ports.get(port_no, None)
        if port is None:
            request.setResponseCode(httplib.NOT_FOUND)
            return 'dpid %s port %d is not found' % (dpid, port_no)

        return func(dp, port_no, queue_id)

    def get_queue_properties(self, request, data):
        LOG.debug('get_queues_properties %s %s', request, data)

        def do_queue_properties(dp, port_no, queue_id):
            queue_config = dp.request_queue_config(port_no)
            LOG.debug('queue_config %s', queue_config)
            for q in queue_config.queues:
                if q.queue_id == queue_id:
                    break
            else:
                request.setResponseCode(httplib.NOT_FOUND)
                return 'dpid %s port %d queue %d is not found' % \
                       (dp.id, port_no, queue_id)
            return json.dumps(q.properties)
        return self._do_queue(request, data, do_queue_properties)

    def get_queue_stats(self, request, data):
        LOG.debug('get_queues_stats %s %s', request, data)

        def do_queue_stats(dp, port_no, queue_id):
            queues = dp.request_queue_stats(port_no, queue_id)
            queues = [q._asdict() for q in queues]
            return json.dumps(queues)
        return self._do_queue(request, data, do_queue_stats)

    def _register(self):
        path_switches = (WSPathStaticString('switches'), )
        self.api.register_request(self.list_switches, 'GET',
                                  path_switches,
                                  'get the list of switches')

        path_switch_id = path_switches + (WSPathSwitch(), )
        self.api.register_request(self.get_switch, 'GET',
                                  path_switch_id,
                                  'get the info of a given switch')

        path_switch_type = path_switch_id + (WSPathStaticString('type'), )
        LOG.debug('%s', path_switch_type)
        self.api.register_request(self.get_switch_type, 'GET',
                                  path_switch_type,
                                  'get the type of a given switch')

        path_switch_current_version = path_switch_id + \
                                    (WSPathStaticString('current_version'), )
        self.api.register_request(self.get_switch_current_version, 'GET',
                                  path_switch_current_version,
                                  'get the version of a given switch')

        path_switch_stats = path_switch_id + (WSPathStaticString('stats'), )

        path_switch_desc_stats = path_switch_stats + \
                                 (WSPathStaticString('desc'), )
        self.api.register_request(self.get_switch_desc_stats, 'GET',
                                  path_switch_desc_stats,
                                  'get the desc stats of a given switch')

        path_switch_tables_stats = path_switch_stats + \
                                   (WSPathStaticString('tables'), )
        self.api.register_request(self.get_switch_tables_stats, 'GET',
                                  path_switch_tables_stats,
                                  'get the table stats of a given switch')

        path_switch_ports = path_switch_id + (WSPathStaticString('ports'), )
        self.api.register_request(self.list_switch_ports, 'GET',
                                  path_switch_ports,
                                  'list the ports of a given switch')

        path_port = path_switch_ports + (WSPathPort(), )
        self.api.register_request(self.get_port, 'GET',
                                  path_port,
                                  'get the info of a given port')

        path_port_type = path_port + (WSPathStaticString('type'), )
        self.api.register_request(self.get_port_type, 'GET',
                                  path_port_type,
                                  'get the type of a given port')

        path_port_network_id = path_port + (WSPathStaticString('network_id'), )
        self.api.register_request(self.get_port_network_id, 'GET',
                                  path_port_network_id,
                                  'get the network_id of a given port')

        path_port_stats = path_port + (WSPathStaticString('stats'), )
        self.api.register_request(self.get_port_stats, 'GET',
                                  path_port_stats,
                                  'get the stats of a given port')

        path_queues = path_port + (WSPathStaticString('queues'), )
        self.api.register_request(self.get_queues, 'GET',
                                  path_queues,
                                  'get the queue list of a given port')

        path_queue = path_queues + (WSPathQueue(), )

        path_queue_properties = path_queue + \
                                (WSPathStaticString('properties'), )
        self.api.register_request(self.get_queue_properties, 'GET',
                                  path_queue_properties,
                                  'get the properties of a given queue')

        path_queue_stats = path_queue + (WSPathStaticString('stats'), )
        self.api.register_request(self.get_queue_stats, 'GET',
                                  path_queue_stats,
                                  'get the stats of a given queue')
