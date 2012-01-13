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

import gflags
import logging

from ryu import utils

LOG = logging.getLogger('ryu.app.event_dumper')

FLAGS = gflags.FLAGS
gflags.DEFINE_multistring('dump_dispatcher',
                          ['ryu.controller.handler.main_dispatcher'],
                          'list of dispatchers to dump event')


class EventDumper(object):
    def __init__(self, *args, **kwargs):
        for d in FLAGS.dump_dispatcher:
            d = utils.import_object(d)
            d.register_all_handler(self._dump_event)

    def _dump_event(self, ev):
        LOG.info('event %s' % ev)
