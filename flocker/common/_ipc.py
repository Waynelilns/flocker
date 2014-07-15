# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Inter-process communication for flocker.
"""

from subprocess import Popen, PIPE, check_output, CalledProcessError
from contextlib import contextmanager
from io import BytesIO
from threading import current_thread

from zope.interface import Interface, implementer

from characteristic import with_cmp, with_repr


class INode(Interface):
    """
    A remote node with which this node can communicate.
    """

    def run(remote_command):
        """Context manager that runs a remote command and return its stdin.

        The returned file-like object will be closed by this object.

        :param remote_command: ``list`` of ``bytes``, the command to run
            remotely along with its arguments.

        :return: file-like object that can be written to.
        """

    def get_output(remote_command):
        """Run a remote command and return its stdout.

        :param remote_command: ``list`` of ``bytes``, the command to run
            remotely along with its arguments.

        :return: ``bytes`` of stdout from the remote command.
        """


@with_cmp(["initial_command_arguments"])
@with_repr(["initial_command_arguments"])
@implementer(INode)
class ProcessNode(object):
    """Communicate with a remote node using a subprocess.

    :ivar initial_command_arguments: ``tuple`` of ``bytes``, initial
        command arguments to prefix to whatever arguments get passed to
        ``run()``.
    """
    def __init__(self, initial_command_arguments):
        self.initial_command_arguments = tuple(initial_command_arguments)

    @contextmanager
    def run(self, remote_command):
        process = Popen(
            self.initial_command_arguments + tuple(remote_command),
            stdin=PIPE)
        try:
            yield process.stdin
        finally:
            process.stdin.close()
            exit_code = process.wait()
            if exit_code:
                # We should really capture this and stderr better:
                # https://github.com/ClusterHQ/flocker/issues/155
                raise IOError("Bad exit", remote_command, exit_code)

    def get_output(self, remote_command):
        try:
            return check_output(
                self.initial_command_arguments + tuple(remote_command))
        except CalledProcessError as e:
            # We should really capture this and stderr better:
            # https://github.com/ClusterHQ/flocker/issues/155
            raise IOError("Bad exit", remote_command, e.returncode, e.output)

    @classmethod
    def using_ssh(cls, host, port, username, private_key):
        """Create a ``ProcessNode`` that communicate over SSH.

        :param bytes host: The hostname or IP.
        :param int port: The port number of the SSH server.
        :param bytes username: The username to SSH as.
        :param FilePath private_key: Path to private key to use when talking to
            SSH server.

        :return: ``ProcessNode`` instance that communicates over SSH.
        """
        return cls(initial_command_arguments=(
            b"ssh",
            b"-q",  # suppress warnings
            b"-i", private_key.path,
            b"-l", username,
            # We're ok with unknown hosts; we'll be switching away from
            # SSH by the time Flocker is production-ready and security is
            # a concern.
            b"-o", b"StrictHostKeyChecking=no",
            # On some Ubuntu versions (and perhaps elsewhere) not
            # disabling this leads for mDNS lookups on every SSH, which
            # can slow down connections very noticeably:
            b"-o", b"GSSAPIAuthentication=no",
            b"-p", b"%d" % (port,), host))


@implementer(INode)
class FakeNode(object):
    """
    Pretend to run a command.

    This is useful for testing.

    :ivar remote_command: The arguments to the last call to ``run()`` or
        ``get_output()``.

    :ivar stdin: `BytesIO` returned from last call to ``run()``.

    :ivar thread_id: The ID of the thread ``run()`` or ``get_output()``
        ran in.
    """
    def __init__(self, outputs=()):
        """
        :param outputs: Sequence of results for ``get_output()``.
        """
        self._outputs = list(outputs)

    @contextmanager
    def run(self, remote_command):
        """
        Store arguments and in-memory "stdin".
        """
        self.thread_id = current_thread().ident
        self.stdin = BytesIO()
        self.remote_command = remote_command
        yield self.stdin
        self.stdin.seek(0, 0)

    def get_output(self, remote_command):
        """
        Return the outputs passed to the constructor.
        """
        self.thread_id = current_thread().ident
        self.remote_command = remote_command
        return self._outputs.pop(0)
