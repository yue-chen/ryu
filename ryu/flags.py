# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011 Isaku Yamahata <yamahata at valinux co jp>
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
global flags
"""

import gflags

FLAGS = gflags.FLAGS

# GLOBAL flags
gflags.DEFINE_boolean('monkey_patch', False, 'do monkey patch')

# ryu.contrib.ovs.dirs
# TODO: once ryu.contrib.ovs is removed, eliminate those.
gflags.DEFINE_string('ovs_pkgdatadir', '/usr/share/openvswitch',
                     'openvswitch package direcotry. can be overrided '
                     'by the environment variable, OVS_PKGDATADIR')
gflags.DEFINE_string('ovs_rundir', '/var/run/openvswitch',
                     'openvswitch runtime directory. can be overrided '
                     'by the environment variable, OVS_RUNDIR')
gflags.DEFINE_string('ovs_logdir', '/var/log/openvswitch',
                     'openvswitch log direcotry can be overrided '
                     'by the environment variable, OVS_LOGDIR')
gflags.DEFINE_string('ovs_bindir', '/usr/bin',
                     'openvswitch binary directory, can be overrided '
                     'by the environment variable, OVS_BINDIR')
gflags.DEFINE_string('ovs_dbdir', '/etc/openvswitch',
                     'openvswitch db directory, can be overrided '
                     'by the environment variable, OVS_SYSCONFDIR or OVS_DBDIR')
