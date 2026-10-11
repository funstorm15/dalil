"""Switch the existing ngrok endpoint, preserving its settings and rollback target."""

import argparse
import copy
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = "https://cornbread-left-licking.ngrok-free.dev"
AGENT = "http://127.0.0.1:4040"


def request(url, payload=None, method=None):
    headers = {"ngrok-skip-browser-warning": "true"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers, method=method or ("PUT" if payload is not None else "GET"),
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8013, choices=[8012, 8013])
    args = parser.parse_args()
    local = f"http://127.0.0.1:{args.port}"
    health = json.loads(request(local + "/api/health"))
    if health.get("status") != "ok":
        raise RuntimeError("V2 is not healthy; leaving the tunnel unchanged")
    expected = (ROOT / "frontend/dist/index.html").read_bytes()
    if request(local + "/") != expected:
        raise RuntimeError("Local endpoint does not serve the V2 build")
    endpoints = json.loads(request(AGENT + "/api/endpoints"))["endpoints"]
    matches = [endpoint for endpoint in endpoints if endpoint.get("url") == PUBLIC]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one existing DALIL endpoint")
    old = {k: v for k, v in matches[0].items() if k not in {"uri", "metrics"}}
    backup_dir = ROOT / "work/deployment"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / f"endpoint-before-{time.time_ns()}.json").write_text(json.dumps(old, indent=2))
    updated = copy.deepcopy(old)
    updated["upstream"]["url"] = local
    print(f"Switching {PUBLIC} from {old['upstream']['url']} to {local}", flush=True)
    def apply(endpoint):
        # This installed agent exposes endpoints but rejects PUT (405).
        # Use its supported tunnel stop/start API with the same domain.
        tunnels = json.loads(request(AGENT + "/api/tunnels"))["tunnels"]
        for tunnel in tunnels:
            if tunnel["public_url"] == PUBLIC:
                request(AGENT + "/api/tunnels/" + urllib.parse.quote(tunnel["name"], safe=""), method="DELETE")
        request(AGENT + "/api/tunnels", {
            "name": endpoint["name"], "proto": "http",
            "addr": endpoint["upstream"]["url"],
            "domain": urllib.parse.urlparse(PUBLIC).hostname,
            "schemes": ["https"], "inspect": endpoint.get("inspect", True),
        }, method="POST")

    unsupported = set(old) - {"name", "url", "upstream", "inspect"}
    if unsupported:
        raise RuntimeError(f"Cannot safely copy endpoint settings: {unsupported}")
    try:
        apply(updated)
        for attempt in range(10):
            try:
                if request(PUBLIC + "/") != expected:
                    raise RuntimeError("Public HTML does not match V2")
                public_health = json.loads(request(PUBLIC + "/api/health"))
                if public_health.get("llm", {}).get("base_url") != health["llm"]["base_url"]:
                    raise RuntimeError("Public API does not match V2")
                for asset in re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', expected):
                    path = asset.decode()
                    if request(PUBLIC + path) != request(local + path):
                        raise RuntimeError("Public asset does not match V2")
                print("Verified: public HTML, assets and API all serve V2.", flush=True)
                return
            except Exception:
                if attempt == 9:
                    raise
                time.sleep(1)
    except BaseException:
        print("Verification failed; restoring the previous endpoint.", flush=True)
        apply(old)
        raise


if __name__ == "__main__":
    main()
