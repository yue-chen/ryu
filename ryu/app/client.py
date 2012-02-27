# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
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

import httplib
import urlparse


class RyuClientBase(object):
    def __init__(self, version, address):
        super(RyuClientBase, self).__init__()
        self.version = version
        res = urlparse.SplitResult('', address, '', '', '')
        self.host = res.hostname
        self.port = res.port
        self.url_prefix = '/' + self.version + '/'

    def _do_request(self, method, action):
        conn = httplib.HTTPConnection(self.host, self.port)
        url = self.url_prefix + action
        conn.request(method, url)
        res = conn.getresponse()
        if res.status in (httplib.OK,
                          httplib.CREATED,
                          httplib.ACCEPTED,
                          httplib.NO_CONTENT):
            return res

        raise httplib.HTTPException(
            res, 'code %d reason %s' % (res.status, res.reason),
            res.getheaders(), res.read())

    def _do_request_read(self, method, action):
        res = self._do_request(method, action)
        return res.read()


class OFPClientV1_0(RyuClientBase):
    version = 'v1.0'

    # /networks/{network_id}/{dpid}_{port}/macs/{mac_address}
    path_networks = 'networks'
    path_network = path_networks + '/%s'
    path_port = path_network + '/%s_%s'
    path_macs = path_port + '/macs'
    path_mac = path_macs + '/%s'

    def __init__(self, address):
        super(OFPClientV1_0, self).__init__(OFPClientV1_0.version, address)

    def get_networks(self):
        return self._do_request_read('GET', self.path_networks)

    def create_network(self, network_id):
        self._do_request('POST', self.path_network % network_id)

    def update_network(self, network_id):
        self._do_request('PUT', self.path_network % network_id)

    def delete_network(self, network_id):
        self._do_request('DELETE', self.path_network % network_id)

    def get_ports(self, network_id):
        return self._do_request_read('GET', self.path_network % network_id)

    def create_port(self, network_id, dpid, port):
        self._do_request('POST', self.path_port % (network_id, dpid, port))

    def update_port(self, network_id, dpid, port):
        self._do_request('PUT', self.path_port % (network_id, dpid, port))

    def delete_port(self, network_id, dpid, port):
        self._do_request('DELETE', self.path_port % (network_id, dpid, port))

    def list_macs(self, network_id, dpid, port):
        return self._do_request_read('GET',
                                     self.path_macs % (network_id, dpid, port))

    def create_mac(self, network_id, dpid, port, mac_address):
        self._do_request('POST', self.path_mac % (network_id, dpid, port,
                                                  mac_address))

    def update_mac(self, network_id, dpid, port, mac_address):
        self._do_request('PUT', self.path_mac % (network_id, dpid, port,
                                                 mac_address))


OFPClient = OFPClientV1_0


class GRETunnelClientV1_0(RyuClientBase):
    version = 'v1.0'

    # /tunnels/gre/networks/{network-id}/key/{tunnel_key}
    # /tunnels/gre/switches/{dpid}/ports/{port-id}/{remote_dpip}
    path_gre = 'tunnels/gre'
    path_key = path_gre + '/networks/%(network_id)s/key'
    path_tunnel_key = path_key + '/%(tunnel_key)s'
    path_ports = path_gre + '/switches/%(dpid)s/ports'
    path_port = path_ports + '/%(port_no)s'
    path_remote_dpid = path_port + '/%(remote_dpid)s'

    def __init__(self, address):
        super(GRETunnelClientV1_0, self).__init__(self.version, address)

    def get_tunnel_key(self, network_id):
        return self._do_request_read('GET', self.path_key % locals())

    def delete_tunnel_key(self, network_id):
        return self._do_request_read('DELETE', self.path_key % locals())

    def create_tunnel_key(self, network_id, tunnel_key):
        self._do_request('POST', self.path_tunnel_key % locals())

    def update_tunnel_key(self, network_id, tunnel_key):
        self._do_request('PUT', self.path_tunnel_key % locals())

    def list_ports(self, dpid):
        return self._do_request_read('GET', self.path_ports % locals())

    def delete_port(self, dpid, port_no):
        return self._do_request_read('DELETE', self.path_port % locals())

    def get_remote_dpid(self, dpid, port_no):
        return self._do_request_read('GET', self.path_port % locals())

    def create_remote_dpid(self, dpid, port_no, remote_dpid):
        self._do_request('POST', self.path_remote_dpid % locals())

    def update_remote_dpid(self, dpid, port_no, remote_dpid):
        self._do_request('PUT', self.path_remote_dpid % locals())


GRETunnelClient = GRETunnelClientV1_0


class SwitchClientV1_0(RyuClientBase):
    version = 'v1.0'

    path_switches = 'switches'
    path_switch = 'switches/%s'
    path_switch_type = 'switches/%s/type'
    path_switch_current_version = 'switches/%s/current_version'
    path_switch_stats = 'switches/%s/stats'
    path_switch_desc_stats = 'switches/%s/stats/desc'
    path_switch_tables_stats = 'switches/%s/stats/tables'

    path_ports = 'switches/%s/ports/'
    path_port = 'switches/%s/ports/%s'
    path_port_type = 'switches/%s/ports/%s/type'
    path_port_network_id = 'switches/%s/ports/%s/network_id'
    path_port_stats = 'switches/%s/ports/%s/stats'
    path_queues = 'switches/%s/ports/%s/queues'
    path_queue_properties = 'switches/%s/ports/%s/queues/%s/properties'
    path_queue_stats = 'switches/%s/ports/%s/queues/%s/stats'

    def __init__(self, address):
        super(SwitchClientV1_0, self).__init__(SwitchClientV1_0.version,
                                               address)

    def list_switches(self):
        return self._do_request_read('GET', self.path_switches)

    def get_switch(self, dpid):
        return self._do_request_read('GET', self.path_switch % dpid)

    def get_switch_type(self, dpid):
        return self._do_request_read('GET', self.path_switch_type % dpid)

    def get_switch_current_version(self, dpid):
        return self._do_request_read('GET',
                                     self.path_switch_current_version % dpid)

    def get_switch_desc_stats(self, dpid):
        return self._do_request_read('GET', self.path_switch_desc_stats % dpid)

    def get_switch_tables_stats(self, dpid):
        return self._do_request_read('GET',
                                     self.path_switch_tables_stats % dpid)

    def list_ports(self, dpid):
        return self._do_request_read('GET', self.path_ports % dpid)

    def get_port(self, dpid, port_no):
        return self._do_request_read('GET', self.path_port % (dpid, port_no))

    def get_port_type(self, dpid, port_no):
        return self._do_request_read('GET',
                                     self.path_port_type % (dpid, port_no))

    def get_port_network_id(self, dpid, port_no):
        return self._do_request_read(
            'GET', self.path_port_network_id % (dpid, port_no))

    def get_port_stats(self, dpid, port_no):
        return self._do_request_read('GET',
                                     self.path_port_stats % (dpid, port_no))

    def get_queues(self, dpid, port_no):
        return self._do_request_read('GET',
                                     self.path_queues % (dpid, port_no))

    def get_queue_properties(self, dpid, port_no, queue_id):
        return self._do_request_read(
            'GET', self.path_queue_properties % (dpid, port_no, queue_id))

    def get_queue_stats(self, dpid, port_no, queue_id):
        return self._do_request_read(
            'GET', self.path_queue_stats % (dpid, port_no, queue_id))


SwitchClient = SwitchClientV1_0


def ignore_http_not_found(func):
    """
    Ignore http not found(404) with Ryu client library.
    Ryu client raises httplib.HTTPException with an error in args[0]
    """
    try:
        func()
    except httplib.HTTPException as e:
        res = e.args[0]
        if res.status != httplib.NOT_FOUND:
            raise
