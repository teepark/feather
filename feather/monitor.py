from __future__ import absolute_import

import errno
import fcntl
import grp
import logging
import os
import pwd
import signal
import stat
import struct
import sys
import tempfile
import time

from greenhouse import io, scheduler, util as gutil

from . import util


master_log = logging.getLogger("feather.monitor.master")
worker_log = logging.getLogger("feather.monitor.worker")


class Monitor(object):

    WORKER_TIMEOUT = 2.0
    WORKER_CHECK_INTERVAL = WORKER_TIMEOUT / 2

    ZOMBIE_CHECK_INTERVAL = 2.0

    def __init__(self, server, worker_count, user=None, group=None,
            notify_fifo=None, daemonize=False):
        self.server = server
        self.count = worker_count
        self.notify_fifo = notify_fifo
        self.daemonize = daemonize
        self.master_pid = None
        self.workers = {}
        self.do_not_revive = set()
        self.die_with_last_worker = False
        self.done = gutil.Event()
        self.zombie_checker = None
        self.readiness_notifier = None
        self.original = True

        # if the user or group name is not a valid one,
        # just let that exception propogate up
        if isinstance(user, str):
            user = pwd.getpwnam(user)[2]
        self.worker_uid = user

        if isinstance(group, str):
            group = grp.getgrnam(group)[2]
        self.worker_gid = group

    @property
    def log(self):
        if self.is_master:
            return master_log
        return worker_log

    ##
    ## Main Entry Point
    ##

    def serve(self):
        if self.daemonize and os.environ.get('DAEMON', None) != 'yes':
            os.environ['DAEMON'] = 'yes'
            util.background()
        self.master_pid = os.getpid()
        self.log.info("starting")
        self._pre_worker_fork()
        self.fork_workers()
        if self.is_master:
            self._post_worker_fork()

        self.done.wait()

    ##
    ## Cooperative Signal Dispatching
    ##

    def signal_handler(self, signum):
        was_master = self.is_master
        @scheduler.schedule
        def handle():
            if not self.is_master == was_master:
                self.log.warn(
                        "signal handler set by master being used by worker")
                return
            if signum not in self.signal_handlers:
                self.log.warn("errant signal handler execution")
                return
            getattr(self, self.signal_handlers[signum])()

    def master_signal_handler(self, signum, frame):
        if not self.is_master:
            self.log.warn("master signal handler called in worker")
            return
        self.signal_handler(signum)

    def worker_signal_handler(self, signum, frame):
        if self.is_master:
            self.log.warn("worker signal handler called in master")
            return
        self.signal_handler(signum)

    ##
    ## Signal Handler Registries
    ##

    worker_signal_handlers = {
        signal.SIGQUIT: "worker_sigquit",
        signal.SIGINT: "worker_sigint",
        signal.SIGTERM: "worker_sigint",
        signal.SIGUSR1: "worker_sigusr1",
    }

    master_signal_handlers = {
        signal.SIGQUIT: "master_sigquit",
        signal.SIGWINCH: "master_sigwinch",
        signal.SIGHUP: "master_sighup",
        signal.SIGINT: "master_sigint",
        signal.SIGTERM: "master_sigint",
        signal.SIGTTIN: "master_sigttin",
        signal.SIGTTOU: "master_sigttou",
        signal.SIGUSR1: "master_sigusr1",
        signal.SIGUSR2: "master_sigusr2",
        signal.SIGCHLD: "master_sigchld",
    }

    ##
    ## Master Signal Actions
    ##

    def apply_master_signals(self):
        self.log.info("applying master signal handlers")
        self.signal_handlers = self.master_signal_handlers

        # this is required to prevent signals from clobbering emulated
        # syscalls like accept() and recv()
        scheduler.set_ignore_interrupts()

        for signum in self.master_signal_handlers:
            signal.signal(signum, self.master_signal_handler)

    def clear_master_signals(self):
        self.log.info("clearing master signal handlers")
        for signum in self.master_signal_handlers:
            if signum == signal.SIGINT:
                signal.signal(signum, signal.default_int_handler)
            else:
                signal.signal(signum, signal.SIG_DFL)

    def master_sigquit(self):
        # gracefully shutdown workers, then exit
        self.log.info("SIGQUIT received. gracefully shutting down")
        self.do_not_revive.update(self.workers.keys())
        self.die_with_last_worker = True
        if not self.workers:
            self.log.info("last worker done, exiting")
            self.done.set()
        self.signal_workers(signal.SIGQUIT)

    def master_sigwinch(self):
        # gracefully shutdown workers but stay up
        if os.getppid() != 1 and os.getpgrp() == os.getpid():
            # ignore when not daemonized, it could just be a window size change
            self.log.info(
                    "SIGWINCH received. ignoring; in foreground")
            return
        self.log.info(
                "SIGWINCH received. gracefully closing workers")
        self.do_not_revive.update(self.workers.keys())
        self.die_with_last_worker = False
        self.signal_workers(signal.SIGQUIT)

    def master_sighup(self):
        # gracefully shutdown and then re-fork workers
        self.log.info("SIGHUP received. bouncing workers")
        self.die_with_last_worker = False

        workers = self.workers.keys()

        self.fork_workers()

        self.signal_workers(signal.SIGQUIT, pids=workers)

    def master_sigint(self):
        # immediately kill workers, then exit
        self.log.info(
                "SIGINT/TERM received. killing workers and exiting")
        self.do_not_revive.update(self.workers.keys())
        self.die_with_last_worker = True
        if not self.workers:
            self.log.info("last worker done, exiting")
            self.done.set()
        self.signal_workers(signal.SIGKILL)

    def master_sigttin(self):
        # increment workers
        self.log.info("SIGTTIN received. incrementing worker count")
        self.count += 1
        self.fork_workers()

    def master_sigttou(self):
        # decrement workers
        self.log.info(
                "SIGTTOU received. gracefully closing one worker")
        self.count -= 1

        lucky = sorted(self.workers.keys())[0]
        self.do_not_revive.add(lucky)
        os.kill(lucky, signal.SIGQUIT)

    def master_sigusr1(self):
        # reopen logs
        self.log.info("SIGUSR1 received")
        pass

    def master_sigusr2(self):
        # fork/exec new master with new workers
        self.log.info("SIGUSR2 received. fork/execing a new master")
        self.new_master()

    def master_sigchld(self):
        # clean up after a dead worker
        pid, status = os.waitpid(-1, os.WNOHANG)
        self.log.info("SIGCHLD received. cleaning up dead worker %d" % pid)
        self._worker_exited(pid)

    ##
    ## Worker Signal Actions
    ##

    def apply_worker_signals(self):
        self.log.info("applying worker signals")
        self.signal_handlers = self.worker_signal_handlers

        # this is required to prevent signals from clobbering emulated
        # syscalls like accept() and recv()
        scheduler.set_ignore_interrupts()

        for signum in self.worker_signal_handlers:
            signal.signal(signum, self.worker_signal_handler)

    def clear_worker_signals(self):
        self.log.info("clearing worker signals")
        for signum in self.worker_signal_handlers:
            if signum == signal.SIGINT:
                signal.signal(signum, signal.default_int_handler)
            else:
                signal.signal(signum, signal.SIG_DFL)

    def worker_sigquit(self):
        # gracefully shutdown
        self.log.info("SIGQUIT received. gracefully closing")
        self.server.shutdown()
        self.server.done.wait()
        self.done.set()

    def worker_sigint(self):
        # ungracefully shutdown
        self.log.info("SIGINT/TERM received. closing hard")
        sys.exit(1)

    def worker_sigusr1(self):
        # reopen log files
        self.log.info("SIGUSR1 received")
        pass

    ##
    ## Worker Forking and Management
    ##

    @property
    def is_master(self):
        return os.getpid() == self.master_pid

    def pre_worker_fork(self):
        pass

    def _pre_worker_fork(self):
        if (self.worker_uid is not None and
                os.geteuid() not in (0, self.worker_uid)):
            raise RuntimeError("workers can't setuid from non-root")

        if (self.worker_gid is not None and
                os.getegid() not in (0, self.worker_gid)):
            raise RuntimeError("workers can't setgid from non-root")

        self.ready_r, self.ready_w = io.pipe()
        self.ready_lockfd, lockfile = tempfile.mkstemp()

        self.apply_master_signals()
        self.server.worker_count = 1
        self.server.setup()
        self.zombie_monitor()

        self.pre_worker_fork()

    def fork_worker(self):
        if not self.is_master:
            self.log.warn("tried to fork a worker from a worker")
            return True

        tmpfd, tmpfname = tempfile.mkstemp()
        if self.worker_uid is not None:
            os.fchown(tmpfd, self.worker_uid, os.getegid())

        pid = os.fork()

        if pid and self.is_master:
            self.log.info("worker forked: %d" % pid)
            self._worker_forked(pid, tmpfd)
            return False

        if self.workers is None:
            self.log.error("forked a worker from a worker, exiting")
            sys.exit(1)

        self._worker_postfork(tmpfd)

        self.server.serve()

    def fork_workers(self):
        self.log.info("forking %d workers" % (self.count - len(self.workers)))
        for i in xrange(self.count - len(self.workers)):
            if self.fork_worker():
                break

    def _post_worker_fork(self):
        self.original = False
        self.readiness_notifier = scheduler.greenlet(self.notify_readiness)
        scheduler.schedule(self.readiness_notifier)

    def notify_readiness(self):
        pids = set(self.workers.keys())

        while pids:
            pid = struct.unpack("!I", self.ready_r.read(4))[0]
            if not self.is_master:
                self.log.warn(
                        "got a readiness notification in a worker, resending")
                self.ready_w.write(struct.pack("!I", pid))
                return
            pids.remove(pid)
            self.log.info("got readiness notification from %d, %d remaining" %
                    (pid, len(pids)))

        if self.notify_fifo:
            try:
                os.mknod(self.notify_fifo, 0644, stat.S_IFIFO)
            except EnvironmentError, exc:
                if exc.args[0] != errno.EEXIST:
                    raise
                self.log.info("couldn't create notify fifo, already exists")

            self.log.info("notifying of readiness at %s" % self.notify_fifo)

            try:
                with io.File(self.notify_fifo, 'a') as fp:
                    fp.write('\x00')
            except EnvironmentError, exc:
                self.log.warn("feather cluster ready; " +
                        "notify fifo could not be opened")
                if exc.args[0] != errno.ENXIO:
                    raise
        else:
            self.log.info("feather cluster ready; no notify fifo configured")

    def worker_forked(self):
        pass

    def _worker_forked(self, pid, tmpfd):
        self.log.info("starting health monitor for %d" % pid)
        self.health_monitor(pid, tmpfd)
        self.worker_forked()

    def worker_postfork(self):
        pass

    def _worker_postfork(self, tmpfd):
        self.log.info("initializing worker")

        if self.worker_uid is not None:
            self.log.info("setting worker uid")
            os.setuid(self.worker_uid)

        if self.worker_gid is not None:
            self.log.info("setting worker gid")
            os.setgid(self.worker_gid)

        if self.readiness_notifier is not None:
            scheduler.end(self.readiness_notifier)

        scheduler.reset_poller()

        if self.original:
            scheduler.schedule(self.worker_inform_ready)

        self.clear_master_signals()
        self.apply_worker_signals()

        for t in self.workers.values():
            t.cancel()
        self.workers = None

        self.log.info("starting health timer")
        self.worker_health_timer(tmpfd)
        self.zombie_checker.cancel()

        self.worker_postfork()

    def worker_inform_ready(self):
        self.server.ready.wait()
        self.log.info("indicating readiness to master")

        send = struct.pack("!I", os.getpid())

        # unless monkeypatching is in place,
        # this will temporarily block the whole worker process
        fcntl.flock(self.ready_lockfd, fcntl.LOCK_EX)

        try:
            self.ready_w.write(send)
        finally:
            fcntl.flock(self.ready_lockfd, fcntl.LOCK_UN)

    def signal_workers(self, signum, pids=None):
        if not self.is_master:
            self.log.warn("tried signaling workers from a worker")
            return
        pids = pids or self.workers.keys()
        self.log.info("signaling all %d workers with %d" % (len(pids), signum))

        for pid in pids:
            os.kill(pid, signum)

    def worker_crashed(self):
        pass

    def _worker_exited(self, pid):
        if pid not in self.workers:
            # this could be another master that was created
            # by a SIGUSR2 handler and then killed off
            return
        self.workers.pop(pid).cancel()
        if pid in self.do_not_revive:
            self.do_not_revive.discard(pid)
        else:
            self.log.fatal("worker %d crashed, starting replacement" % pid)
            self.worker_crashed()
            if self.fork_worker():
                return

        if self.die_with_last_worker and not self.workers:
            self.log.info("last worker done, exiting")
            self.done.set()

    ##
    ## New Master Fork/Exec
    ##

    def new_master(self):
        server = self.server
        os.environ[server.environ_fd_name] = str(server.socket.fileno())

        if not os.fork():
            self.log.info("in forked child, execing new master")
            os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

    ##
    ## Health Checking
    ##

    def health_monitor(self, pid, tmpfd):
        timer = gutil.Timer(
                self.WORKER_TIMEOUT,
                self.health_monitor_check,
                args=(pid, tmpfd))
        timer.start()
        self.workers[pid] = timer

    def health_monitor_check(self, pid, tmpfd):
        now = time.time()
        checkin = os.fstat(tmpfd).st_ctime
        if now - checkin > self.WORKER_TIMEOUT:
            self.log.critical("health monitor check failed for %d" % pid)
            try:
                os.kill(pid, signal.SIGKILL)
            except EnvironmentError, exc:
                if exc.args[0] != errno.ESRCH:
                    raise
            self._worker_exited(pid)
        else:
            self.log.debug("health monitor check passed for %d" % pid)
            self.health_monitor(pid, tmpfd)

    def worker_health_timer(self, tmpfd):
        timer = gutil.Timer(
                self.WORKER_CHECK_INTERVAL,
                self.worker_health_check,
                args=(tmpfd,))
        timer.start()
        return timer

    def worker_health_check(self, tmpfd):
        self.log.debug("checking in with health monitor")
        os.fchmod(tmpfd, 0644)
        self.worker_health_timer(tmpfd)

    ##
    ## Extra Zombie Cleanup
    ##

    def zombie_monitor(self):
        timer = gutil.Timer(
                self.ZOMBIE_CHECK_INTERVAL,
                self.zombie_check)
        timer.start()
        self.zombie_checker = timer

    def zombie_check(self):
        self.log.debug("checking for zombie processes")
        try:
            while 1:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                except EnvironmentError, err:
                    if err.args[0] == errno.ECHILD:
                        break
                    raise
                if not pid:
                    break
                self.log.warn(
                        "unexpected zombie found (%d) and cleaned up" % pid)
                self._worker_exited(pid)
        finally:
            self.zombie_monitor()
