"""Redfish (BMC REST API) transport."""

import logging
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

BASE = "/redfish/v1"


class RedfishTransport:
    """Redfish client for OpenBMC on BF3."""

    def __init__(self, host: str, user: str = "root",
                 password: str = "0penBmc",
                 timeout: int = 30):
        self.host = host
        self.user = user
        self.password = password
        self.timeout = timeout
        self.base_url = f"https://{host}{BASE}"
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.session.verify = False
        self.session.headers.update({
            "Content-Type": "application/json",
        })

    def _url(self, uri: str) -> str:
        if uri.startswith("http"):
            return uri
        return f"{self.base_url}{uri}"

    def get(self, uri: str) -> dict:
        resp = self.session.get(
            self._url(uri), timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def post(self, uri: str, payload: dict) -> dict:
        resp = self.session.post(
            self._url(uri), json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def patch(self, uri: str, payload: dict) -> dict:
        resp = self.session.patch(
            self._url(uri), json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def is_alive(self) -> bool:
        try:
            self.get("/")
            return True
        except Exception:
            return False

    def wait_for_redfish(self, timeout: int = 300,
                         interval: int = 10) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_alive():
                return True
            time.sleep(interval)
        return False

    def wait_for_task(self, task_uri: str,
                      timeout: int = 900,
                      interval: int = 15) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data = self.get(task_uri)
                state = data.get("TaskState", "")
                if state in ("Completed", "CompletedOK"):
                    return True
                if state in ("Exception", "Killed"):
                    logger.error(
                        f"Task failed: {data.get('Messages')}"
                    )
                    return False
            except Exception:
                pass
            time.sleep(interval)
        return False

