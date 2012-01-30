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

#
# datapath type
# At this moment, this information is not used yet.
# switches are categorized by its rolls
# openflow controller may want to handle switch differently depending
# on it role
#
# core network switch:  switch that connects only internal network entities.
#                       OF controller sees this kinds of switch as
#                       internal routing
#
# edge network switch:  switch that connects public network entity to
#                       our internal network.
#
# VM network switch:    switch that connects VM to our internal network.
#                       typically OVS in host OS.
#
# unknown:
#

CORE_NETWORK = 'CORE_NETWORK'
EDGE_NETWORK = 'EDGE_NETWORK'
EDGE_VM = 'EDGE_VM'
UNKNOWN = 'UNKNOWN'
