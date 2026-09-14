import time

import requests

from config import UA


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return s


class Http:
    def __init__(self):
        self.s = session()
        self._nse_ready = False

    def get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 40)
        headers = kwargs.pop("headers", {})
        last = None
        for attempt in range(3):
            try:
                r = self.s.get(url, headers=headers, **kwargs)
                last = r
                if r.status_code in (429, 403, 502, 503) and attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                return r
            except requests.RequestException as exc:
                last = exc
                time.sleep(1.2 * (attempt + 1))
        if isinstance(last, requests.Response):
            return last
        raise last

    def nse_json(self, url: str) -> dict | list:
        if not self._nse_ready:
            home = self.get(
                "https://www.nseindia.com/",
                headers={"Accept": "text/html"},
            )
            if home.status_code >= 400:
                raise RuntimeError(f"NSE homepage {home.status_code}")
            self._nse_ready = True
            time.sleep(0.4)
        r = self.get(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nseindia.com/",
            },
        )
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or "json" not in ctype:
            self._nse_ready = False
            raise RuntimeError(f"NSE JSON failed {r.status_code} {ctype[:40]}")
        return r.json()
