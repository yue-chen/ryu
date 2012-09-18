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
import socket
import ssl
import uuid

from gevent import monkey
import gevent
monkey.patch_all()

from sqlalchemy.exc import NoSuchTableError, OperationalError
from sqlalchemy.ext.sqlsoup import SqlSoup
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm.exc import NoResultFound

from ovs import json
from ovs.jsonrpc import Message

from quantumclient import client as q_client
from quantumclient.common import exceptions as q_exc
from quantumclient.v2_0 import client as q_clientv2

from ryu.app import conf_switch_key as cs_key
from ryu.app import rest_nw_id
from ryu.base import app_manager
from ryu.controller import conf_switch, handler, network
from ryu.lib import dpid as dpid_lib
from ryu.lib import synchronized


LOG = logging.getLogger('quantum_adapter')

FLAGS = gflags.FLAGS
gflags.DEFINE_string(
    'sql_connection',
    'mysql://root:mysql@192.168.122.10/ovs_quantum?charset=utf8',
    'database connection')
gflags.DEFINE_string('int_bridge', 'br-int', 'integration bridge name')

gflags.DEFINE_string('quantum_url', 'http://localhost:9696',
                     'URL for connecting to quantum')
gflags.DEFINE_integer('quantum_url_timeout', 30,
                      'timeout value for connecting to quantum in seconds')
gflags.DEFINE_string('quantum_admin_username', 'quantum',
                     'username for connecting to quantum in admin context')
gflags.DEFINE_string('quantum_admin_password', 'service_password',
                     'password for connecting to quantum in admin context')
gflags.DEFINE_string('quantum_admin_tenant_name', 'service',
                     'tenant name for connecting to quantum in admin context')
gflags.DEFINE_string('quantum_admin_auth_url', 'http://localhost:5000/v2.0',
                     'auth url for connecting to quantum in admin context')
gflags.DEFINE_string(
    'quantum_auth_strategy',
    'keystone',
    'auth strategy for connecting to quantum in admin context')

gflags.DEFINE_string('quantum_controller_addr', None,
                     'openflow mehod:address:port to set controller of'
                     'ovs bridge')


def _get_auth_token():
    httpclient = q_client.HTTPClient(
        username=FLAGS.quantum_admin_username,
        tenant_name=FLAGS.quantum_admin_tenant_name,
        password=FLAGS.quantum_admin_password,
        auth_url=FLAGS.quantum_admin_auth_url,
        timeout=FLAGS.quantum_url_timeout,
        auth_strategy=FLAGS.quantum_auth_strategy)
    try:
        httpclient.authenticate()
    except (q_exc.Unauthorized, q_exc.Forbidden, q_exc.EndpointNotFound) as e:
        LOG.error("authentication failure: %s", e)
        return None
    # LOG.debug("_get_auth_token: token=%s", httpclient.auth_token)
    return httpclient.auth_token


def _get_quantum_client(token):
    if token:
        my_client = q_clientv2.Client(
            endpoint_url=FLAGS.quantum_url,
            token=token, timeout=FLAGS.quantum_url_timeout)
    else:
        my_client = q_clientv2.Client(
            endpoint_url=FLAGS.quantum_url,
            auth_strategy=None, timeout=FLAGS.quantum_url_timeout)
    return my_client


PORT_ERROR = -1
PORT_UNKNOWN = 0
PORT_GATEWAY = 1
PORT_VETH_GATEWAY = 2
PORT_GUEST = 3
PORT_TUNNEL = 4


class OVSPort(object):
    # extra-ids: 'attached-mac', 'iface-id', 'iface-status', 'vm-uuid'

    def __init__(self, row, port):
        super(OVSPort, self).__init__()
        self.row = row
        self.name = None
        self.ofport = None
        self.type = None
        self.ext_ids = {}
        self.options = {}
        self.update(port)

    def update(self, port):
        self.__dict__.update((key, port[key]) for key
                             in ['name', 'ofport', 'type']
                             if key in port)
        if 'external_ids' in port:
            self.ext_ids = dict(port['external_ids'][1])
        if 'options' in port:
            self.options = dict(port['options'][1])

    def get_port_type(self):
        if not isinstance(self.ofport, int):
            return PORT_ERROR
        if self.type == 'internal' and 'iface-id' in self.ext_ids:
            return PORT_GATEWAY
        if self.type == '' and 'iface-id' in self.ext_ids:
            return PORT_VETH_GATEWAY
        if (self.type == 'gre' and 'local_ip' in self.options and
                'remote_ip' in self.options):
            return PORT_TUNNEL
        if self.type == '' and 'vm-uuid' in self.ext_ids:
            return PORT_GUEST
        return PORT_UNKNOWN

    def __str__(self):
        return "name=%s type=%s ofport=%s ext_ids=%s options=%s" % (
            self.name, self.type, self.ofport, self.ext_ids, self.options)


S_DPID_GET = 0      # start datapath-id monitoring
S_CTRL_SET = 1      # start set controller
S_PORT_GET = 2      # start port monitoring
S_MONITOR = 3       # datapath-id/port monitoring


class OVSMonitor(object):
    def __init__(self, dpid, nw, db, q_api, ctrl_addr):
        super(OVSMonitor, self).__init__()
        self.dpid = dpid
        self.network_api = nw
        self.db = db
        self.q_api = q_api
        self.ctrl_addr = ctrl_addr

        self.address = None
        self.tunnel_ip = None
        self.int_bridge = None
        self.socket = None
        self.state = None
        self.parser = None
        self.dpid_row = None
        self.is_active = False

        self.handlers = {}
        self.handlers[S_DPID_GET] = {Message.T_REPLY: self.receive_dpid}
        self.handlers[S_CTRL_SET] = {Message.T_REPLY:
                                     self.receive_set_controller}
        self.handlers[S_PORT_GET] = {Message.T_REPLY: self.receive_port}
        self.handlers[S_MONITOR] = {Message.T_NOTIFY: {
            'port_monitor': self.monitor_port
        }}

    def update_external_port(self, port, delete=False):
        # TODO:XXX
        # check if the given port is in self.dpid
        # Once this is done, ryu_quantum_agent.VifPortSet can be eliminated
        return

        if delete:
            self.network_api.delete_port(rest_nw_id.NW_ID_EXTERNAL,
                                         self.dpid, port.ofport)
        else:
            self.network_api.update_port(rest_nw_id.NW_ID_EXTERNAL,
                                         self.dpid, port.ofport)

    def update_vif_port(self, port, delete=False):
        # LOG.debug("update_vif_port: %s", port)
        try:
            port_info = self.db.ports.filter(
                self.db.ports.id == port.ext_ids['iface-id']).one()
        except NoResultFound:
            LOG.warn("port not found: %s", port.ext_ids['iface-id'])
            self.db.commit()
            return
        except (NoSuchTableError, OperationalError):
            LOG.error("could not access database")
            self.db.rollback()
            # TODO: If OperationalError occurred, it should re-connect to
            # the database (re-create SplSoup object)
            return
        self.db.commit()

        # TODO:XXX
        # this port can be in other bridge, not self.dpid.
        # If so, ignore it.
        # For now, this is an easy workaround.
        if port_info.device_owner == 'network:router_gateway':
            return

        port_data = {
            # TODO:XXX check if this port is in dpid
            'datapath_id': dpid_lib.dpid_to_str(self.dpid),

            'port_no': port.ofport,
        }
        if delete:
            # In order to set
            # port.status = quantum.common.constants.PORT_STATUS_DOWN
            # port.status can't be changed via rest api directly, so resort to
            # ryu-specical parameter to tell it.
            port_data['deleted'] = True
        body = {'port': port_data}
        # LOG.debug("port-body = %s", body)
        try:
            self.q_api.update_port(port_info.id, body)
        except (q_exc.ConnectionFailed, q_exc.QuantumClientException) as e:
            LOG.error("quantum update port failed: %s", e)
            # TODO: When authentication failure occurred, it should get auth
            # token again

    def update_port(self, data):
        for row in data:
            table = data[row]
            new_port = None
            old_port = None
            if "new" in table:
                new_port = OVSPort(row, table['new'])
            if "old" in table:
                old_port = OVSPort(row, table['old'])

            if old_port == new_port:
                continue
            if not new_port:
                port_type = old_port.get_port_type()
                if port_type == PORT_ERROR:
                    continue
                elif port_type == PORT_UNKNOWN:
                    # LOG.info("delete external port: %s", old_port)
                    self.update_external_port(old_port, delete=True)
                else:
                    # LOG.info("delete port: %s", old_port)
                    if port_type != PORT_TUNNEL:
                        self.update_vif_port(old_port, delete=True)
                continue
            if new_port.ofport == -1:
                continue
            if not old_port or old_port.ofport == -1:
                port_type = new_port.get_port_type()
                if port_type == PORT_ERROR:
                    continue
                elif port_type == PORT_UNKNOWN:
                    # LOG.info("create external port: %s", new_port)
                    self.update_external_port(new_port)
                else:
                    # LOG.info("create port: %s", new_port)
                    if port_type != PORT_TUNNEL:
                        self.update_vif_port(new_port)
                continue
            if new_port.get_port_type() in (PORT_GUEST,
                                            PORT_GATEWAY, PORT_VETH_GATEWAY):
                # LOG.info("update port: %s", new_port)
                self.update_vif_port(new_port)

    def update_dpid(self, data):
        for row in data:
            table = data[row]
            if "new" in table:
                table_new = table['new']
                int_bridge = table_new['name']
                dpid = dpid_lib.str_to_dpid(table_new['datapath_id'])
                if dpid == self.dpid:
                    # LOG.debug("datapath_id=%s name=%s", dpid, int_bridge)
                    self.dpid_row = row
                    self.int_bridge = int_bridge
                    self.start_set_controller(table_new)
                    break

    def monitor_port(self, msg):
        _key, args = msg.params
        if not "Interface" in args:
            return
        data = args['Interface']
        self.update_port(data)

    def receive_port(self, msg):
        if not "Interface" in msg.result:
            return
        data = msg.result['Interface']
        self.update_port(data)
        self.state = S_MONITOR

    def start_port_monitor(self):
        self.state = S_PORT_GET
        params = json.from_string(
            '["Open_vSwitch", '
            ' "port_monitor", '
            ' {"Interface": '
            '   [{"columns": '
            '     ["name", "ofport", "type", "external_ids", "options"]}]}]')
        self.send_request("monitor", params)

    def receive_set_controller(self, msg):
        LOG.debug("set controller: %s", msg)
        for row in msg.result:
            if "error" in row:
                err = str(row["error"])
                if "details" in row:
                    err += ": " + str(row["details"])
                LOG.error("could not set controller: %s", err)
                self.is_active = False
                return
        self.start_port_monitor()

    def start_set_controller(self, _table_row):
        self.state = S_CTRL_SET
        if not self.ctrl_addr:
            self.start_port_monitor()
            return

        # TODO:XXX
        # check duplication and don't delete other controller.
        uuid_ = str(uuid.uuid4()).replace('-', '_')
        params = json.from_string(
            '["Open_vSwitch", '
            ' {"op": "insert", '
            '  "table": "Controller", '
            '  "row": {"target": "%s"}, '
            '  "uuid-name": "row%s"}, '
            ' {"op": "update", '
            '  "table": "Bridge", '
            '  "row": {"controller": ["named-uuid", "row%s"]}, '
            '  "where": [["_uuid", "==", ["uuid", "%s"]]]}]' %
            (str(self.ctrl_addr), uuid_, uuid_, str(self.dpid_row)))
        self.send_request("transact", params)

    def receive_dpid(self, msg):
        LOG.debug('recieve_dpid_monitor %s', msg)
        if not "Bridge" in msg.result:
            return
        data = msg.result['Bridge']
        self.update_dpid(data)  # update_dpid() calls start_set_controller()

    def start_dpid_monitor(self):
        self.state = S_DPID_GET
        params = json.from_string(
            '["Open_vSwitch", '
            ' "dpid_monitor", '
            ' {"Bridge": {"columns": ["datapath_id", "name"]}}]')
        self.send_request("monitor", params)

    def handle_rpc(self, msg):
        _handler = None
        try:
            _handler = self.handlers[self.state][msg.type]
        except KeyError:
            pass

        if msg.type == Message.T_REQUEST:
            if msg.method == "echo":
                reply = Message.create_reply(msg.params, msg.id)
                self.send(reply)
            elif _handler:
                _handler(msg)
            else:
                reply = Message.create_error({"error": "unknown method"},
                                             msg.id)
                self.send(reply)
                LOG.warn("unknown request: %s", msg)
        elif msg.type == Message.T_REPLY:
            if _handler:
                _handler(msg)
            else:
                LOG.warn("unknown reply: %s", msg)
        elif msg.type == Message.T_NOTIFY:
            if msg.method == "shutdown":
                self.shutdown()
            elif _handler:
                if msg.method == "update":
                    key, _args = msg.params
                    if key in _handler:
                        _handler[key](msg)
            else:
                LOG.warn("unknown notification: %s", msg)
        else:
            LOG.warn("unsolicited JSON-RPC reply or error: %s", msg)

        self.db.commit()
        return

    def process_msg(self):
        _json = self.parser.finish()
        self.parser = None
        if isinstance(_json, basestring):
            LOG.warn("error parsing stream: %s", _json)
            return
        msg = Message.from_json(_json)
        if not isinstance(msg, Message):
            LOG.warn("received bad JSON-RPC message: %s", msg)
            return
        return msg

    def recv_loop(self):
        while self.is_active:
            buf = ""
            ret = self.socket.recv(4096)
            if len(ret) == 0:
                self.is_active = False
                return
            buf += ret
            while buf:
                if self.parser is None:
                    self.parser = json.Parser()
                buf = buf[self.parser.feed(buf):]
                if self.parser.is_done():
                    msg = self.process_msg()
                    if msg:
                        self.handle_rpc(msg)

    def send(self, msg):
        if msg.is_valid():
            LOG.warn("not a valid JSON-RPC request: %s", msg)
            return
        buf = json.to_string(msg.to_json())
        self.socket.sendall(buf)

    def send_request(self, method, params):
        msg = Message.create_request(method, params)
        self.send(msg)

    def close(self):
        if self.socket:
            self.socket.close()

    def set_ovsdb_addr(self, address):
        _proto, _host, _port = address.split(':')
        self.address = address

    def shutdown(self):
        LOG.info("shutdown: %s: dpid=%s", self.address, self.dpid)
        self.is_active = False
        self.close()    # to exit recv_loop()

    def serve(self):
        if not self.address:
            return
        self.network_api.update_network(rest_nw_id.NW_ID_EXTERNAL)
        self.network_api.update_network(rest_nw_id.NW_ID_VPORT_GRE)

        proto, host, port = self.address.split(':')
        if proto not in ['tcp', 'ssl']:
            proto = 'tcp'
        self.close()
        socket_ = gevent.socket.socket()
        if proto == 'ssl':
            socket_ = gevent.ssl.wrap_socket(self.socket)
        try:
            socket_.connect((host, int(port)))
        except (socket.error, socket.timeout) as e:
            LOG.error("TCP connection failure: %s", e)
            raise e
        except ssl.SSLError as e:
            LOG.error("SSL connection failure: %s", e)
            raise e
        LOG.info("connect: %s", self.address)
        if not self.is_active:
            socket_.close()
            return
        self.socket = socket_

        self.start_dpid_monitor()
        self.recv_loop()
        self.close()

    def create_serve_thread(self):
        self.is_active = True
        return gevent.spawn_later(0, self.serve)

    @staticmethod
    def create(dpid, nw):
        db = SqlSoup(FLAGS.sql_connection,
                     session=scoped_session(
                         sessionmaker(autoflush=True,
                                      expire_on_commit=False,
                                      autocommit=False)))
        token = None
        if FLAGS.quantum_auth_strategy:
            token = _get_auth_token()
        q_api = _get_quantum_client(token)
        return OVSMonitor(dpid, nw, db, q_api, FLAGS.quantum_controller_addr)


class QuantumAdapter(app_manager.RyuApp):
    _CONTEXTS = {
        'conf_switch': conf_switch.ConfSwitchSet,
        'network': network.Network,
    }
    _LOCK = 'lock'

    def __init__(self, *_args, **kwargs):
        super(QuantumAdapter, self).__init__()
        self.cs = kwargs['conf_switch']
        self.nw = kwargs['network']

        # protects self.monitors
        setattr(self, self._LOCK, gevent.coros.Semaphore())
        self.monitors = {}

        # just connect to sql server to detect wrong parameter early.
        LOG.debug('sql_connection %s', FLAGS.sql_connection)
        db = SqlSoup(FLAGS.sql_connection,
                     session=scoped_session(
                         sessionmaker(autoflush=True,
                                      expire_on_commit=False,
                                      autocommit=False)))
        db.commit()

    @synchronized.synchronized(_LOCK)
    def _conf_switch_set_ovsdb_addr(self, dpid, value):
        if dpid in self.monitors:
            mon = self.monitors[dpid]
            mon.shutdown()
        mon = OVSMonitor.create(dpid, self.nw)
        mon.set_ovsdb_addr(value)
        mon_thr = mon.create_serve_thread()
        self.monitors[dpid] = (mon, mon_thr)

    @synchronized.synchronized(_LOCK)
    def _conf_switch_del_ovsdb_addr(self, dpid):
        mon_mon_thr = self.monitors.pop(dpid, None)
        if mon_mon_thr is None:
            LOG.error("no monitor found: %s", dpid)
            return
        mon, mon_thr = mon_mon_thr
        mon.shutdown()
        mon_thr.join()

    @handler.set_ev_cls(conf_switch.EventConfSwitchSet,
                        conf_switch.CONF_SWITCH_EV_DISPATCHER)
    def conf_switch_set_handler(self, ev):
        LOG.debug("conf_switch set: %s", ev)
        if ev.key == cs_key.OVSDB_ADDR:
            self._conf_switch_set_ovsdb_addr(ev.dpid, ev.value)
        else:
            LOG.debug("unknown event: %s", ev)

    @handler.set_ev_cls(conf_switch.EventConfSwitchDel,
                        conf_switch.CONF_SWITCH_EV_DISPATCHER)
    def conf_switch_del_handler(self, ev):
        LOG.debug("conf_switch del: %s", ev)
        if ev.key == cs_key.OVSDB_ADDR:
            self._conf_switch_del_ovsdb_addr(ev.dpid)
        else:
            LOG.debug("unknown event: %s", ev)
