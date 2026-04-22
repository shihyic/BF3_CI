"""Host server device (the x86 machine hosting the BF3 DPU)."""

import logging
from bf3_ci.transport.ssh import SSHTransport

logger = logging.getLogger(__name__)


class HostDevice:
    """Represents the host server that contains the BF3 card."""

    def __init__(self, config: dict):
        self.config = config
        self.ssh = SSHTransport(
            host=config["ip"],
            user=config.get("user", "root"),
            key_path=config.get("key"),
            password=config.get("password"),
        )

    def connect(self):
        try:
            self.ssh.connect()
        except ConnectionError:
            logger.warning("Host SSH not available")

    def disconnect(self):
        self.ssh.disconnect()

    def is_alive(self) -> bool:
        return self.ssh.is_alive()

    def execute(self, command: str, timeout: int = 60):
        return self.ssh.execute(command, timeout=timeout)

    def reboot(self, timeout: int = 10):
        self.execute("reboot", timeout=timeout)

