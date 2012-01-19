# Copyright (C) 2012 Nippon Telegraph and Telephone Corporation.
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

from ryu.controller import event
from ryu.controller import dispatcher
from ryu.controller import dp_type


class EventDP(event.EventBase):
    def __init__(self, dp, enter_leave):
        # enter_leave
        # True: dp entered
        # False: dp leaving
        super(EventDP, self).__init__()
        self.dp = dp
        self.enter = enter_leave


class DPSet(object):
    def __init__(self, ev_q, dispatcher_):
        # dp registration and type setting can be occur in any order
        # Sometimes the sw_type is set before dp connection
        self.dp_types = {}

        self.dps = set()
        self.ev_q = ev_q
        self.dispatcher = dispatcher_

    def register(self, dp):
        assert dp not in self.dps
        assert dp.id is not None

        dp_type_ = self.dp_types.pop(dp.id, None)
        if dp_type_ is not None:
            dp.dp_type = dp_type_

        self.ev_q.queue(EventDP(dp, True))
        self.dps.add(dp)

    def unregister(self, dp):
        if dp in self.dps:
            self.dps.remove(dp)
            self.ev_q.queue(EventDP(dp, False))

    def set_type(self, dp_id, dp_type_=dp_type.UNKNOWN):
        for dp in self.dps:
            if dp_id == dp.id:
                dp.dp_type = dp_type_
                break
        else:
            assert dp not in self.dp_types
            self.dp_types[dp_id] = dp_type_

    def get_all(self):
        return self.dps


DPSET_EV_DISPATCHER = dispatcher.EventDispatcher('dpset')
_DPSET_EV_Q = dispatcher.EventQueue(DPSET_EV_DISPATCHER)
DPSET = DPSet(_DPSET_EV_Q, DPSET_EV_DISPATCHER)
