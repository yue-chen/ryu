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

import inspect
from functools import wraps


def desc_equal_one(desc_in_msg, desc):
    return not desc or desc_in_msg.rstrip('\x00') == desc


def desc_equal(desc_stat, mfr_desc=None, hw_desc=None, dp_desc=None):
    return (desc_equal_one(desc_stat.mfr_desc, mfr_desc) and
            desc_equal_one(desc_stat.hw_desc, hw_desc) and
            desc_equal_one(desc_stat.dp_desc, dp_desc))


def desc_specific(mfr_desc=None, hw_desc=None, dp_desc=None):
    "Decorator to execute only when the given datapath has specific desc stat"
    def desc_specific_decorator(func):
        if len(inspect.getargspec(func).args) == 2:     # == {'self', 'ev'}

            # class method case
            @wraps(func)
            def wrapped_meth(self, ev):
                if desc_equal(ev.msg.datapath.desc,
                              mfr_desc, hw_desc, dp_desc):
                    return func(self, ev)
            return wrapped_meth

        # function case
        @wraps(func)
        def wrapped(ev):
            if desc_equal(ev.msg.datapath.desc, mfr_desc, hw_desc, dp_desc):
                return func(ev)
        return wrapped

    return desc_specific_decorator
