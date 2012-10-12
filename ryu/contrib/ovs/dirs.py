import gflags
import os


FLAGS = gflags.FLAGS

PKGDATADIR = os.environ.get("OVS_PKGDATADIR", FLAGS.ovs_pkgdatadir)
RUNDIR = os.environ.get("OVS_RUNDIR", FLAGS.ovs_rundir)
LOGDIR = os.environ.get("OVS_LOGDIR", FLAGS.ovs_logdir)
BINDIR = os.environ.get("OVS_BINDIR", FLAGS.ovs_bindir)

DBDIR = os.environ.get("OVS_DBDIR")
if not DBDIR:
    sysconfdir = os.environ.get("OVS_SYSCONFDIR")
    if sysconfdir:
        DBDIR = "%s/openvswitch" % sysconfdir
    else:
        DBDIR = FLAGS.ovs_dbdir
