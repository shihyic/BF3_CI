"""SSH transport using Paramiko."""

import logging
import time
from dataclasses import dataclass, field

import paramiko

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    rc: int = -1
    duration: float = 0.0


class SSHTransport:
    """SSH connection wrapper for BF3 CI."""

    def __init__(self, host: str, user: str = "root",
                 password: str | None = None,
                 key_path: str | None = None,
                 port: int = 22,
                 connect_timeout: int = 30):
        self.host = host
        self.user = user
        self.password = password
        self.key_path = key_path
        self.port = port
        self.connect_timeout = connect_timeout
        self._client: paramiko.SSHClient | None = None

    def connect(self):
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )
        kwargs: dict = dict(
            hostname=self.host,
            port=self.port,
            username=self.user,
            timeout=self.connect_timeout,
        )
        if self.key_path:
            kwargs["key_filename"] = self.key_path
        elif self.password:
            kwargs["password"] = self.password
            kwargs["allow_agent"] = False
            kwargs["look_for_keys"] = False
        try:
            self._client.connect(**kwargs)
            logger.info(f"SSH connected to {self.host}")
        except paramiko.AuthenticationException:
            self._client = None
            raise
        except Exception as e:
            self._client = None
            raise ConnectionError(
                f"SSH connect to {self.host} failed: {e}"
            ) from e

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None

    def is_alive(self) -> bool:
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return transport is not None and transport.is_active()

    def execute(self, command: str,
                timeout: int = 60) -> CommandResult:
        if not self.is_alive():
            try:
                self.connect()
            except (ConnectionError,
                    paramiko.AuthenticationException):
                return CommandResult(
                    stderr="SSH not connected", rc=-1
                )
        start = time.time()
        try:
            _, stdout_ch, stderr_ch = self._client.exec_command(
                command, timeout=timeout
            )
            rc = stdout_ch.channel.recv_exit_status()
            return CommandResult(
                stdout=stdout_ch.read().decode(errors="replace").strip(),
                stderr=stderr_ch.read().decode(errors="replace").strip(),
                rc=rc,
                duration=time.time() - start,
            )
        except Exception as e:
            logger.error(f"Command failed on {self.host}: {e}")
            return CommandResult(
                stderr=str(e), rc=-1,
                duration=time.time() - start,
            )

    def scp_put(self, local_path: str, remote_path: str):
        if not self.is_alive():
            self.connect()
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def _interactive_password_change(
        self, temp_pw: str
    ) -> bool:
        """Change expired password via keyboard-interactive auth.

        OpenSSH 9.6+ rejects password auth for expired accounts
        and requires keyboard-interactive for the change dialog.
        """
        transport = paramiko.Transport(
            (self.host, self.port))
        transport.connect()

        stage = {"idx": 0}

        def handler(title, instructions, prompt_list):
            responses = []
            for prompt_text, _ in prompt_list:
                p = prompt_text.lower()
                logger.info(
                    f"KBD-INT[{stage['idx']}]: {prompt_text!r}")
                if "current" in p or "(current)" in p:
                    responses.append(self.password)
                elif "new" in p or "retype" in p or "again" in p:
                    responses.append(temp_pw)
                else:
                    responses.append(
                        self.password
                        if stage["idx"] == 0 else temp_pw)
                stage["idx"] += 1
            return responses

        try:
            transport.auth_interactive(self.user, handler)
        except paramiko.AuthenticationException:
            transport.close()
            raise

        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy())
        self._client._transport = transport
        self.password = temp_pw
        logger.info(
            f"Keyboard-interactive password change "
            f"succeeded on {self.host}")
        return True

    def change_expired_password(self, new_password: str) -> bool:
        """Handle forced password change on the DPU.

        Two paths:
        1. Already connected (older OpenSSH) -- use PTY shell
        2. Not connected / auth rejected (OpenSSH 9.6+) --
           use keyboard-interactive auth to change during login
        """
        temp_pw = "CiTmp_Xk9$mNv2024!z"

        if not self.is_alive():
            try:
                self._interactive_password_change(temp_pw)
            except Exception as e:
                logger.error(
                    f"Keyboard-interactive auth failed on "
                    f"{self.host}: {e}")
                return False
        else:
            try:
                transport = self._client.get_transport()
                chan = transport.open_session()
                chan.get_pty()
                chan.invoke_shell()

                def _read(wait: float = 3.0) -> str:
                    out = ""
                    deadline = time.time() + wait
                    while time.time() < deadline:
                        if chan.recv_ready():
                            out += chan.recv(4096).decode(
                                errors="replace")
                        else:
                            time.sleep(0.2)
                    return out

                prompt = _read(5)
                logger.debug(f"PTY[1]: {prompt!r}")

                if ("current" in prompt.lower()
                        or "(current)" in prompt.lower()):
                    chan.send(self.password + "\n")
                    prompt = _read(3)
                    logger.debug(f"PTY[2]: {prompt!r}")

                chan.send(temp_pw + "\n")
                prompt = _read(3)
                logger.debug(f"PTY[3]: {prompt!r}")

                if "bad password" in prompt.lower():
                    chan.send(temp_pw + "\n")
                    prompt = _read(3)
                    logger.debug(f"PTY[3b]: {prompt!r}")

                chan.send(temp_pw + "\n")
                prompt = _read(5)
                logger.debug(f"PTY[4]: {prompt!r}")

                chan.close()

                self.password = temp_pw
                self.disconnect()
                self.connect()
            except Exception as e:
                logger.error(
                    f"PTY password change failed: {e}")
                return False

        try:
            self.execute(
                "sed -i 's/^.*dictcheck.*/dictcheck = 0/' "
                "/etc/security/pwquality.conf; "
                "sed -i 's/^.*minlen.*/minlen = 6/' "
                "/etc/security/pwquality.conf; "
                "grep -q dictcheck /etc/security/pwquality.conf "
                "|| echo 'dictcheck = 0' >> "
                "/etc/security/pwquality.conf; "
                "grep -q minlen /etc/security/pwquality.conf "
                "|| echo 'minlen = 6' >> "
                "/etc/security/pwquality.conf",
                timeout=10,
            )

            self.execute(
                f"echo '{self.user}:{new_password}' | chpasswd",
                timeout=10,
            )
            self.execute(
                f"chage -I -1 -m 0 -M 99999 -E -1 {self.user}",
                timeout=10,
            )

            self.password = new_password
            self.disconnect()
            self.connect()
            logger.info(f"Password changed on {self.host}")
            return True
        except Exception as e:
            logger.error(f"Password finalization failed: {e}")
            return False

    def wait_for_ssh(self, timeout: int = 600,
                     interval: int = 10) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.connect()
                return True
            except paramiko.AuthenticationException:
                logger.info(
                    f"SSH reachable on {self.host} "
                    "(auth failed, likely expired password)")
                return True
            except ConnectionError:
                time.sleep(interval)
        return False

