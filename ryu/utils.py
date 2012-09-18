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


import inspect
import logging
import os
import os.path
import sys

LOG = logging.getLogger('ryu.utils')


def _import(modname):
    if modname.endswith('.py'):
        modname = modname[:-3]
    __import__(modname)
    return sys.modules[modname]


def import_module(modname):
    try:
        __import__(modname)
    except ImportError:
        modname = os.path.normpath(modname)
        if not os.path.isabs(modname):
            name = modname.replace(os.sep, '.')
            try:
                return _import(name)
            except ImportError:
                pass

        dirname = os.path.dirname(modname)
        name = os.path.basename(modname)
        if dirname not in sys.path:
            sys.path.append(dirname)
        return _import(name)
    return sys.modules[modname]


RYU_DEFAULT_FLAG_FILE = ('ryu.conf', 'etc/ryu/ryu.conf' '/etc/ryu/ryu.conf')


def find_flagfile(default_path=RYU_DEFAULT_FLAG_FILE):
    if '--flagfile' in sys.argv:
        return

    script_dir = os.path.dirname(inspect.stack()[-1][1])

    for filename in default_path:
        if not os.path.isabs(filename):
            if os.path.exists(filename):
                # try relative to current path
                filename = os.path.abspath(filename)
            elif os.path.exists(os.path.join(script_dir, filename)):
                # try relative to script dir
                filename = os.path.join(script_dir, filename)

        if not os.path.exists(filename):
            continue

        flagfile = '--flagfile=%s' % filename
        sys.argv.insert(1, flagfile)
        LOG.debug('flagfile = %s', filename)
        return


def round_up(x, y):
    return ((x + y - 1) / y) * y
