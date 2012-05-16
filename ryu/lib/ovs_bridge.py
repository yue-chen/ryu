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

"""
slimmed down version of OVSBridge in quantum agent
"""

import functools
import gflags
import logging
import signal
from subprocess import PIPE, Popen


import ryu.exception as ryu_exc

LOG = logging.getLogger(__name__)

FLAGS = gflags.FLAGS
gflags.DEFINE_integer('ovsdb_timeout', 2, 'ovsdb timeout')


class VifPort(object):
    def __init__(self, port_name, ofport, vif_id, vif_mac, switch):
        super(VifPort, self).__init__()
        self.port_name = port_name
        self.ofport = ofport
        self.vif_id = vif_id
        self.vif_mac = vif_mac
        self.switch = switch

    def __str__(self):
        return ('iface-id=%s, '
                'vif_mac=%s, '
                'port_name=%s, '
                'ofport=%d, '
                'bridge_name=%s' % (self.vif_id,
                                    self.vif_mac,
                                    self.port_name,
                                    self.ofport,
                                    self.switch.br_name))


class TunnelPort(object):
    def __init__(self, port_name, ofport, tunnel_type, local_ip, remote_ip):
        super(TunnelPort, self).__init__()
        self.port_name = port_name
        self.ofport = ofport
        self.tunnel_type = tunnel_type
        self.local_ip = local_ip
        self.remote_ip = remote_ip

    def __eq__(self, other):
        return (self.port_name == other.port_name and
                self.ofport == other.ofport and
                self.tunnel_type == other.tunnel_type and
                self.local_ip == other.local_ip and
                self.remote_ip == other.remote_ip)

    def __str__(self):
        return ('port_name=%s, '
                'ofport=%s, '
                'type=%s, '
                'local_ip=%s, '
                'remote_ip=%s' % (self.port_name,
                                  self.ofport,
                                  self.tunnel_type,
                                  self.local_ip,
                                  self.remote_ip))


class OVSBridge(object):
    def __init__(self, datapath_id, ovsdb_addr):
        super(OVSBridge, self).__init__()
        self.datapath_id = datapath_id
        self.ovsdb_addr = ovsdb_addr
        self.br_name = self._get_bridge_name()

    def _get_bridge_name(self):
        """ get Bridge name of a given 'datapath_id' """
        res = self.run_vsctl(['find', 'Bridge',
                              'datapath_id=%s' % self.datapath_id])
        for line in res.splitlines():
            (column, _colon, val) = list.strip().split()
            if column == 'name':
                return val

        raise ryu_exc.OVSBridgeNotFound(datapath_id=self.datapath_id)

    @staticmethod
    def run_cmd(args):
        LOG.debug('## running command: %s' + ' '.join(args))
        pipe = Popen(args, stdout=PIPE)
        retval = pipe.communicate()[0]
        if pipe.returncode == -(signal.SIGALRM):
            LOG.debug('## timeout running command: ' + ' '.join(args))
        return retval

    def run_vsctl(self, args):
        full_args = ['ovs-vsctl', '--db=%s' % self.ovsdb_addr,
                     '--timeout=%d' % FLAGS.ovsdb_timeout]
        full_args += args
        return self.run_cmd(full_args)

    def set_db_attribute(self, table_name, record, column, value):
        args = ['set', table_name, record, '%s=%s' % (column, value)]
        self.run_vsctl(args)

    def clear_db_attribute(self, table_name, record, column):
        args = ["clear", table_name, record, column]
        self.run_vsctl(args)

    def db_get_val(self, table, record, column):
        return self.run_vsctl(['get', table, record, column]).rstrip('\n\r')

    def db_get_map(self, table, record, column):
        return self.db_str_to_map(self.db_get_val(table, record, column))

    @staticmethod
    def db_str_to_map(full_str):
        list_ = full_str.strip('{}').split(', ')
        ret = {}
        for e in list_:
            if e.find('=') == -1:
                continue
            arr = e.split('=')
            ret[arr[0]] = arr[1].strip('"')
        return ret

    def get_datapath_id(self):
        res = self.db_get_val('Bridge', self.br_name, 'datapath_id')
        return res.strip().strip('"')

    def delete_port(self, port_name):
        self.run_vsctl(['--', '--if-exists', 'del-port', self.br_name,
                        port_name])

    def get_ofport(self, port_name):
        return self.db_get_val('Interface', port_name, 'ofport')

    def get_port_name_list(self):
        res = self.run_vsctl(['list-ports', self.br_name])
        return res.split('\n')[0:-1]

    def add_tunnel_port(self, name, tunnel_type, local_ip, remote_ip,
                        key=None):
        options = 'local_ip=%(local_ip)s,remote_ip=%(remote_ip)s' % locals()
        if key:
            options += ',key=%(key)s' % locals()

        return self.run_vsctl(['add-port', self.br_name, name, '--',
                               'set', 'Interface', name,
                               'type=%s' % tunnel_type,
                               'options=%s' % options])

    def add_gre_port(self, name, local_ip, remote_ip, key=None):
        self.add_tunnel_port(name, 'gre', local_ip, remote_ip, key=key)

    def del_port(self, port_name):
        return self.run_vsctl(['del-port', self.br_name, port_name])

    def _get_ports(self, get_port):
        ports = []
        port_names = self.get_port_name_list()
        for name in port_names:
            if self.get_ofport(name) < 0:
                continue
            port = get_port(name)
            if port:
                ports.append(port)

        return ports

    def _vifport(self, name, external_ids):
        ofport = self.get_ofport(name)
        return VifPort(name, ofport, external_ids['iface-id'],
                       external_ids['attached-mac'], self)

    def _get_vif_port(self, name):
        external_ids = self.db_get_map('Interface', name, 'external_ids')
        if 'iface-id' in external_ids and 'attached-mac' in external_ids:
            return self._vifport(name, external_ids)

    def get_vif_ports(self):
        'returns a VIF object for each VIF port'
        return self._get_ports(self._get_vif_port)

    def _get_external_port(self, name):
        # exclude vif ports
        external_ids = self.db_get_map('Interface', name, 'external_ids')
        if external_ids:
            return

        # exclude tunnel ports
        options = self.db_get_map('Interface', name, 'options')
        if 'remote_ip' in options:
            return

        ofport = self.get_ofport(name)
        return VifPort(name, ofport, None, None, self)

    def get_external_ports(self):
        return self._get_ports(self._get_external_port)

    def get_tunnel_port(self, name, tunnel_type='gre'):
        type_ = self.db_get_val('Interface', name, 'type')
        if type_ != tunnel_type:
            return

        options = self.db_get_map('Interface', name, 'options')
        if 'local_ip' in options and 'remote_ip' in options:
            ofport = self.get_ofport(name)
            return TunnelPort(name, ofport, tunnel_type,
                              options['local_ip'], options['remote_ip'])

    def get_tunnel_ports(self, tunnel_type='gre'):
        get_tunnel_port = functools.partial(self.get_tunnel_port,
                                            tunnel_type=tunnel_type)
        return self._get_ports(get_tunnel_port)
