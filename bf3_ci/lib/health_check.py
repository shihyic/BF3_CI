"""Health check utilities for BF3 CI."""

import logging

logger = logging.getLogger(__name__)


class HealthCheck:
    """Runs connectivity and health checks against the DUT."""

    def __init__(self, bf3, bmc, host):
        self.bf3 = bf3
        self.bmc = bmc
        self.host = host

    def check_all(self) -> dict:
        return {
            "bf3_alive": self.bf3.is_alive(),
            "bmc_alive": self.bmc.is_alive(),
            "host_alive": self.host.is_alive(),
        }

    def check_bf3(self) -> bool:
        alive = self.bf3.is_alive()
        logger.info(f"BF3 ARM alive: {alive}")
        return alive

    def check_bmc(self) -> bool:
        alive = self.bmc.is_alive()
        logger.info(f"BMC alive: {alive}")
        return alive

    def check_host(self) -> bool:
        alive = self.host.is_alive()
        logger.info(f"Host alive: {alive}")
        return alive

