#!/usr/bin/env python3
"""pam_local_auth_probe.py — drive one interactive PAM login (su) on a pty and report the outcome.

Used by tests/tests_pam_account_control.yml to prove that a LOCAL user still authenticates through
the himmelblau-wired PAM stack — right password in, wrong password refused — with the himmelblau
daemons down (the lock-out failure mode). PAM reads the credential through a conversation on the
TTY, so a pipe is not enough: this drives a real pty. Python 3 stdlib only (pty/select/pwd).

Design constraints:
  * The password arrives on STDIN (one line) — never argv or the environment, so it is
    invisible to `ps`/`/proc`. The pty has echo off during the PAM password read, so it never
    appears in the captured transcript either.
  * pam_himmelblau sits FIRST in the SUSE auth stack and may prompt for a password on EVERY
    login, including local users it will never authenticate. A local login can therefore show
    two (or more) "password" prompts: himmelblau's (which fails for a non-Entra user and falls
    through) and pam_unix's (which succeeds). So the probe answers EVERY distinct password prompt
    with the same password, up to --max-sends.
  * `--run-as USER` drops privileges in the child before exec'ing su: `su` only prompts for the
    target's password when the caller is non-root, and the caller (ansible) runs as root.
  * A hard deadline bounds the whole conversation; a stalled flow is killed and reported 124 with
    the captured transcript for diagnosis.

Exit codes: 0 = login succeeded; 1 = login refused; 124 = conversation timed out; 2 = usage.
"""

# The maintainers keep a near-identical probe for their live-tenant runs; the role ships this copy
# so the test suite stays self-contained. Patch both together.
import argparse
import os
import pty
import pwd
import re
import select
import signal
import sys
import time

SU = "/usr/bin/su"
# Matches a PAM password prompt waiting at the very end of the stream, e.g. "Password: ",
# "Entra Id Password: ", "<user>'s password: " — case-insensitive. The tail is [ \t]*\Z, NOT
# \s*$: \Z is the true end of the buffer and \s/$ would also match across the newline su prints
# once a prompt has been answered, so the same prompt would be answered a second time.
PROMPT = re.compile(rb"(?i)password[^\n]*:[ \t]*\Z")


def drop_privileges(username):
    """Drop to USER before exec: su only prompts when the caller is non-root."""
    ent = pwd.getpwnam(username)
    os.initgroups(username, ent.pw_gid)
    os.setgid(ent.pw_gid)
    os.setuid(ent.pw_uid)
    os.environ["HOME"] = ent.pw_dir
    os.environ["USER"] = username
    # PROMPT is an English-only regex. Force the C locale in the child so a localized image
    # cannot translate the prompt out from under it — the probe would otherwise time out at
    # rc 124 and be read as a lock-out on a perfectly healthy host.
    os.environ["LC_ALL"] = "C"
    os.environ["LANG"] = "C"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user", help="target account to log in as (su -)")
    parser.add_argument(
        "-c",
        "--command",
        default="id",
        help="command run in the target's login shell (default: id)",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=120.0,
        help="hard deadline for the whole conversation in seconds",
    )
    parser.add_argument(
        "--max-sends",
        type=int,
        default=4,
        help="max password prompts to answer (stack prompts + pam_unix)",
    )
    parser.add_argument(
        "--run-as",
        default=None,
        metavar="USER",
        help="drop to this local user before exec'ing su (root callers)",
    )
    parser.add_argument(
        "--log",
        default=None,
        metavar="PATH",
        help="write the (password-free) pty transcript here for diagnosis",
    )
    args = parser.parse_args()

    password = sys.stdin.readline().rstrip("\n")
    if not password:
        print("ERROR: expected the password as one line on stdin", file=sys.stderr)
        return 2

    pid, fd = pty.fork()
    if pid == 0:  # child: becomes the prompting su on the new pty
        try:
            if args.run_as:
                drop_privileges(args.run_as)
            os.execv(SU, ["su", "-", args.user, "-c", args.command])
        except Exception as exc:  # pragma: no cover - child reports via the pty
            print(f"EXEC FAILED: {exc}", file=sys.stderr)
            os._exit(127)

    deadline = time.monotonic() + args.timeout
    buf = b""
    sends = 0
    last_end = -1
    timed_out = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        ready, _, _ = select.select([fd], [], [], min(remaining, 1.0))
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:  # EIO: child closed its side (exited)
            break
        if not chunk:
            break
        buf += chunk
        # Answer each NEW password prompt (its end position moves as the stream grows) with the
        # same password, up to --max-sends. The same prompt with no new output keeps the same end
        # position, so it is not answered twice.
        match = PROMPT.search(buf)
        if match and sends < args.max_sends and match.end() != last_end:
            os.write(fd, password.encode() + b"\n")
            sends += 1
            last_end = match.end()

    if timed_out:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    _, status = os.waitpid(pid, 0)
    os.close(fd)

    transcript = buf.decode("utf-8", "replace")
    # Defense in depth: the pty normally keeps echo off during the password read, but a broken
    # conversation (e.g. su cannot init PAM because the himmelblau daemon is down) can echo the
    # typed password back into the stream. Scrub it before it reaches any log or stdout.
    if password:
        transcript = transcript.replace(password, "***REDACTED***")
    if args.log:
        try:
            # This runs as root against a fixed path: unlink first, then O_EXCL | O_NOFOLLOW,
            # so a symlink pre-created at that name cannot redirect the write.
            try:
                os.unlink(args.log)
            except FileNotFoundError:
                pass
            fdlog = os.open(
                args.log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fdlog, "w") as handle:
                handle.write(f"# {args.user} (sends={sends}, timed_out={timed_out})\n")
                handle.write(transcript)
        except OSError:
            pass
    print(transcript)
    if timed_out:
        print(
            f"PROBE: TIMEOUT after {sends} password send(s) - conversation did not complete",
            file=sys.stderr,
        )
        return 124
    # Decode the wait status with the W* macros (present in every Python 3).
    if os.WIFEXITED(status):
        rc = os.WEXITSTATUS(status)
    elif os.WIFSIGNALED(status):
        rc = 128 + os.WTERMSIG(status)
    else:
        rc = 1
    print(f"PROBE: su exited with {rc} after {sends} password send(s)", file=sys.stderr)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
