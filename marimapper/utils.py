import os
import sys


def _drain_stdin():
    """Discard any keystrokes the user typed before we got to this prompt.
    Async status output (e.g. SFM progress messages) used to repaint the
    'Start scan?' prompt mid-scan; users would answer the apparent second
    prompt, and that 'y' would sit in stdin and trigger an unwanted scan
    when the next prompt iteration ran. Flushing input here makes the
    prompt strictly synchronous: we only accept what's typed *after* it
    appears."""
    try:
        import termios

        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (ImportError, OSError, AttributeError):
        pass  # not a TTY or non-POSIX; harmless to skip


def get_user_confirmation(prompt):  # pragma: no coverage

    try:
        _drain_stdin()
        uin = input(prompt)

        while uin.lower() not in ("y", "n"):
            _drain_stdin()
            uin = input(prompt)

    except KeyboardInterrupt:
        return False

    return uin == "y"


class SupressLogging(object):
    def __enter__(self):
        self.outnull_file = open(os.devnull, "w")
        self.errnull_file = open(os.devnull, "w")

        self.old_stdout_fileno_undup = sys.stdout.fileno()
        self.old_stderr_fileno_undup = sys.stderr.fileno()

        self.old_stdout_fileno = os.dup(sys.stdout.fileno())
        self.old_stderr_fileno = os.dup(sys.stderr.fileno())

        self.old_stdout = sys.stdout
        self.old_stderr = sys.stderr

        os.dup2(self.outnull_file.fileno(), self.old_stdout_fileno_undup)
        os.dup2(self.errnull_file.fileno(), self.old_stderr_fileno_undup)

        sys.stdout = self.outnull_file
        sys.stderr = self.errnull_file
        return self

    def __exit__(self, *_):
        sys.stdout = self.old_stdout
        sys.stderr = self.old_stderr

        os.dup2(self.old_stdout_fileno, self.old_stdout_fileno_undup)
        os.dup2(self.old_stderr_fileno, self.old_stderr_fileno_undup)

        os.close(self.old_stdout_fileno)
        os.close(self.old_stderr_fileno)

        self.outnull_file.close()
        self.errnull_file.close()
