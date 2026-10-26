#!/usr/bin/env python3
"""Makes the VPS's .env from your local .env: `python3 deploy/make_env.py <VPS IP or domain>` -> .env.production (mode 600, never committed).
With only an IP (no domain) the address becomes <ip-with-dashes>.sslip.io.

- the connector secret is replaced by a NEW random one (the old one lives in chat logs and on your Mac: do not reuse it on the internet)
- ALLOWED_HOSTS and PUBLIC_BASE_URL point at the domain, DOMAIN is added for Caddy
- settings that only make sense on the Mac (the automation Chrome address, Ofran-through-browser) are dropped: docker-compose.yml sets them
- everything else (MYT_API_KEY, ARBITRIP_CONTRACT_ID, MINISITE_AUTH_CODE, GYG_FIND_READ_IN_SERVER...) is copied as it is
Nothing secret is printed except the new connector URL at the end.
"""

import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DROP = {"HOST", "PORT", "BROWSER_CDP_URL", "OFRAN_BROWSER_CDP", "OFRAN_USE_BROWSER", "ALLOWED_HOSTS", "PUBLIC_BASE_URL", "MCP_SECRET", "DOMAIN"}


def main() -> None:
    arg = sys.argv[1].lower() if len(sys.argv) == 2 else ""
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", arg):        # a bare IP: no domain needed, sslip.io turns 203.0.113.7 into 203-0-113-7.sslip.io (it resolves to that IP)
        arg = arg.replace(".", "-") + ".sslip.io"
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", arg):
        sys.exit("usage: python3 deploy/make_env.py <the VPS IP, or a domain you own>      (example: 203.0.113.7 -> https://203-0-113-7.sslip.io)")
    domain = arg
    source = ROOT / ".env"
    if not source.exists():
        sys.exit("no .env here to start from")
    kept = []
    for line in source.read_text().splitlines():
        key = line.split("=", 1)[0].strip()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line and key not in DROP:
            kept.append(line)
    secret = secrets.token_urlsafe(32)
    lines = [
        "# made by deploy/make_env.py: do not commit",
        f"DOMAIN={domain}",
        f"MCP_SECRET={secret}",
        f"ALLOWED_HOSTS=127.0.0.1:*,localhost:*,{domain}",
        f"PUBLIC_BASE_URL=https://{domain}",
        "OFRAN_USE_BROWSER=false",
        *kept,
    ]
    target = ROOT / ".env.production"
    target.write_text("\n".join(lines) + "\n")
    os.chmod(target, 0o600)
    print(f"wrote {target.name} ({len(kept)} settings copied, new MCP_SECRET)")
    print(f"connector URL once the server is up:  https://{domain}/mcp/{secret}")
    if not any(k.startswith("MYT_API_KEY=") and len(k) > len("MYT_API_KEY=") for k in kept):
        print("WARNING: MYT_API_KEY is empty in your .env")


if __name__ == "__main__":
    main()
