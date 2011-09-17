import errno
import grp
import os
import pwd
import signal
import sys
import tempfile
import time

from greenhouse import poller, scheduler, utils


class Monitor(object):
    def __init__(self, server, worker_count, user=None, group=None):
        self.server = server
        self.count = worker_count
        self.master_pid = os.getpid()
        self.workers = {}
        self.do_not_revive = set()
        self.die_with_last_worker = False
        self.done = utils.Event()

        # if the user or group name is not a valid one,
        # just let that exception propogate up
        if isinstance(user, str):
            user = pwd.getpwnam(user)[2]
        self.worker_uid = user

        if isinstance(group, str):
            group = grp.getgrnam(group)[2]
        self.worker_gid = group

    ##
    ## Main Entry Point
    ##

    def serve(self):
        self.pre_worker_fork()
        self.fork_workers()

        self.done.wait()

    ##
    ## Cooperative Signal Dispatching
    ##

    def signal_handler(self, signum):
        was_master = self.is_master
        @scheduler.schedule
        def handle():
            if not self.is_master == was_master:
                return
            if signum not in self.signal_handlers:
                return
            getattr(self, self.signal_handlers[signum])()

    def master_signal_handler(self, signum, frame):
        if not self.is_master:
            return
        self.signal_handler(signum)

    def worker_signal_handler(self, signum, frame):
        if self.is_master:
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
        self.signal_handlers = self.master_signal_handlers

        for signum in self.master_signal_handlers:
            signal.signal(signum, self.master_signal_handler)

    def clear_master_signals(self):
        for signum in self.master_signal_handlers:
            if signum == signal.SIGINT:
                signal.signal(signum, signal.default_int_handler)
            else:
                signal.signal(signum, signal.SIG_DFL)

    def master_sigquit(self):
        # gracefully shutdown workers, then exit
        self.do_not_revive.update(self.workers.keys())
        self.die_with_last_worker = True
        if not self.workers:
            self.done.set()
        self.signal_workers(signal.SIGQUIT)

    def master_sigwinch(self):
        # gracefully shutdown workers but stay up
        if os.getppid() != 1 and os.getpgrp() == os.getpid():
            # ignore when not daemonized, it could just be a window size change
            return
        self.do_not_revive.update(self.workers.keys())
        self.die_with_last_worker = False
        self.signal_workers(signal.SIGQUIT)

    def master_sighup(self):
        # gracefully shutdown and then re-fork workers
        self.die_with_last_worker = False

        workers = self.workers.keys()

        self.fork_workers()

        self.signal_workers(signal.SIGQUIT, pids=workers)

    def master_sigint(self):
        # immediately kill workers, then exit
        self.do_not_revive.update(self.workers.keys())
        self.die_with_last_worker = True
        if not self.workers:
            self.done.set()
        self.signal_workers(signal.SIGKILL)

    def master_sigttin(self):
        # increment workers
        self.count += 1
        self.fork_workers()

    def master_sigttou(self):
        # decrement workers
        self.count -= 1

        lucky = sorted(self.workers.keys())[0]
        self.do_not_revive.add(lucky)
        os.kill(lucky, signal.SIGQUIT)

    def master_sigusr1(self):
        # reopen logs
        pass

    def master_sigusr2(self):
        # fork/exec new master with new workers
        self.new_master()

    def master_sigchld(self):
        # clean up after a dead worker
        pid, status = os.waitpid(-1, os.WNOHANG)
        self.worker_exited(pid)

    ##
    ## Worker Signal Actions
    ##

    def apply_worker_signals(self):
        self.signal_handlers = self.worker_signal_handlers

        for signum in self.worker_signal_handlers:
            signal.signal(signum, self.worker_signal_handler)

    def clear_worker_signals(self):
        for signum in self.worker_signal_handlers:
            if signum == signal.SIGINT:
                signal.signal(signum, signal.default_int_handler)
            else:
                signal.signal(signum, signal.SIG_DFL)

    def worker_sigquit(self):
        # gracefully shutdown
        self.server.shutdown()
        self.server.done.wait()
        self.done.set()

    def worker_sigint(self):
        # ungracefully shutdown
        sys.exit(1)

    def worker_sigusr1(self):
        # reopen log files
        pass

    ##
    ## Worker Forking and Management
    ##

    @property
    def is_master(self):
        return os.getpid() == self.master_pid

    def pre_worker_fork(self):
        if (self.worker_uid is not None and
                os.geteuid() not in (0, self.worker_uid)):
            raise RuntimeError("workers can't setuid from non-root")

        if (self.worker_gid is not None and
                os.getegid() not in (0, self.worker_gid)):
            raise RuntimeError("workers can't setgid from non-root")

        self.apply_master_signals()
        self.server.worker_count = 1
        self.server.setup()

    def fork_worker(self):
        if not self.is_master:
            return True

        scheduler.pause()

        tmpfd, tmpfname = tempfile.mkstemp()
        if self.worker_uid is not None:
            os.fchown(tmpfd, self.worker_uid, os.getegid())

        pid = os.fork()

        if pid and self.is_master:
            self.worker_forked(pid, tmpfd)
            return False

        if self.workers is None:
            sys.exit(1)

        self.worker_postfork(tmpfd)
        return True

    def fork_workers(self):
        for i in xrange(self.count - len(self.workers)):
            if self.fork_worker():
                break

    def worker_forked(self, pid, tmpfd):
        self.workers[pid] = self.health_monitor(pid, tmpfd)

    def worker_postfork(self, tmpfd):
        if self.worker_uid is not None:
            os.setuid(self.worker_uid)

        if self.worker_gid is not None:
            os.setgid(self.worker_gid)

        poller.set()

        self.clear_master_signals()
        self.apply_worker_signals()

        for t in self.workers.values():
            t.cancel()
        self.workers = None

        self.worker_health_timer(tmpfd)

        self.server.serve()

    def signal_workers(self, signum, pids=None):
        if not self.is_master:
            return
        pids = pids or self.workers.keys()

        for pid in pids:
            os.kill(pid, signum)

    def worker_exited(self, pid):
        if pid not in self.workers:
            return
        self.workers.pop(pid).cancel()
        if pid in self.do_not_revive:
            self.do_not_revive.discard(pid)
        else:
            if self.fork_worker():
                return

        if self.die_with_last_worker and not self.workers:
            self.done.set()

    ##
    ## New Master Fork/Exec
    ##

    def new_master(self):
        server = self.server
        os.environ[server.environ_fd_name] = str(server.socket.fileno())

        pid = os.fork()
        if not pid:
            os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

    ##
    ## Health Checking
    ##

    WORKER_TIMEOUT = 2.0

    def health_monitor(self, pid, tmpfd):
        timer = utils.Timer(
                self.WORKER_TIMEOUT,
                self.health_monitor_check,
                args=(pid, tmpfd))
        timer.start()
        return timer

    def health_monitor_check(self, pid, tmpfd):
        now = time.time()
        checkin = os.fstat(tmpfd).st_ctime
        if now - checkin > self.WORKER_TIMEOUT:
            try:
                os.kill(pid, signal.SIGKILL)
            except EnvironmentError, exc:
                if exc.args[0] != errno.ESRCH:
                    raise
            self.worker_exited(pid)
        else:
            self.workers[pid] = self.health_monitor(pid, tmpfd)

    def worker_health_timer(self, tmpfd):
        timer = utils.Timer(
                self.WORKER_TIMEOUT / 2.0,
                self.worker_health_check,
                args=(tmpfd,))
        timer.start()
        return timer

    def worker_health_check(self, tmpfd):
        os.fchmod(tmpfd, 0644)
        self.worker_health_timer(tmpfd)
