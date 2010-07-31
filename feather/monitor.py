import os
import signal
import sys
import tempfile
import time

from greenhouse import io, poller, scheduler, utils


class Monitor(object):
    def __init__(self, server, worker_count):
        self.server = server
        self.count = worker_count
        self.is_master = True
        self.workers = {}
        self.do_not_revive = set()
        self.die_with_last_worker = False
        self.done = utils.Event()

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

    def signal_handler(self, signum, frame):
        was_master = self.is_master
        @scheduler.schedule
        def handle():
            if not self.is_master == was_master:
                return
            getattr(self, self.signal_handlers[signum])()

    ##
    ## Master Signal Actions
    ##

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

    def apply_master_signals(self):
        self.signal_handlers = self.master_signal_handlers

        for signum in self.signal_handlers:
            signal.signal(signum, self.signal_handler)

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

    worker_signal_handlers = {
        signal.SIGQUIT: "worker_sigquit",
        signal.SIGINT: "worker_sigint",
        signal.SIGTERM: "worker_sigint",
        signal.SIGUSR1: "worker_sigusr1",
    }

    def apply_worker_signals(self):
        self.signal_handlers = self.worker_signal_handlers

        for signum in self.signal_handlers:
            signal.signal(signum, self.signal_handler)

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

    def pre_worker_fork(self):
        self.apply_master_signals()
        self.server.worker_count = 1
        self.server.setup()

    def fork_worker(self):
        if not self.is_master:
            return True

        scheduler.pause()

        tmpfd, tmpfname = tempfile.mkstemp()
        pid = os.fork()

        if pid:
            self.worker_forked(pid, tmpfd)
            return False

        self.worker_postfork(tmpfd)
        return True

    def fork_workers(self):
        for i in xrange(self.count - len(self.workers)):
            if self.fork_worker():
                break

    def worker_forked(self, pid, tmpfd):
        self.workers[pid] = self.health_monitor(pid, tmpfd)

    def worker_postfork(self, tmpfd):
        poller.set()

        [t.cancel() for t in self.workers.values()]
        self.workers = None

        self.worker_health_timer(tmpfd)

        self.is_master = False

        self.clear_master_signals()
        self.apply_worker_signals()

        self.server.serve()

    def signal_workers(self, signum, pids=None):
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
            os.execvpe(sys.argv[0], sys.argv, os.environ)

    ##
    ## Health Checking
    ##

    WORKER_TIMEOUT = 2.0

    def health_monitor(self, pid, tmpfd):
        return utils.Timer(
                self.WORKER_TIMEOUT,
                self.health_monitor_check,
                args=(pid, tmpfd))

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
        return utils.Timer(
                self.WORKER_TIMEOUT / 2.0,
                self.worker_health_check,
                args=(tmpfd,))

    def worker_health_check(self, tmpfd):
        os.fchmod(tmpfd, 0644)
        self.worker_health_timer(tmpfd)
