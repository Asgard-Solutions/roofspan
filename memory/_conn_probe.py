"""Connection-latency probe: logs TCP+TLS connect and request time to the public preview URL vs local backend.
Used to investigate intermittent ConnectTimeoutError in the suite (is it the app or the ingress?)."""
import os
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

url = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
host = urlparse(url).hostname
out = open(sys.argv[1], "a", buffering=1)
ctx = ssl.create_default_context()
while True:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    t0 = time.time()
    try:
        s = socket.create_connection((host, 443), timeout=20)
        tcp = time.time() - t0
        ctx.wrap_socket(s, server_hostname=host).close()
        tls = time.time() - t0
    except Exception as e:
        tcp = tls = -1
        out.write(f"{ts} CONNECT_FAIL {type(e).__name__} after {time.time() - t0:.1f}s\n")
    t1 = time.time()
    try:
        code = requests.get("http://localhost:8001/api/health", timeout=20).status_code
    except Exception as e:
        code = type(e).__name__
    local = time.time() - t1
    if tcp > 2 or tls > 3 or local > 2 or tcp < 0:
        out.write(f"{ts} SLOW tcp={tcp:.2f}s tls={tls:.2f}s local_api={local:.2f}s ({code})\n")
    else:
        out.write(f"{ts} ok tcp={tcp:.2f} tls={tls:.2f} local={local:.2f}\n")
    time.sleep(2)
