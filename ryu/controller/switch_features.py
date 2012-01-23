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

import collections


class SwitchFeatures(collections.namedtuple('SwitchFeatures',
        ('datapath_id', 'n_buffers', 'n_tables', 'capabilities', 'actions'))):

    def __new__(cls, *args):
        assert len(args) == 1
        msg = args[0]
        tmp = (msg.datapath_id, msg.n_buffers, msg.n_tables,
               msg.capabilities_str(), msg.actions_str())
        return super(cls, SwitchFeatures).__new__(cls, *tmp)
