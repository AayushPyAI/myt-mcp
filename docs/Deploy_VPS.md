# Deploying the MCP server to a Hostinger KVM 2 VPS with Docker

## Demo today, no domain: the fast track
No domain is needed: the address is `https://<ip-with-dashes>.sslip.io` (for the IP 203.0.113.7: `https://203-0-113-7.sslip.io`). sslip.io is a free service that resolves such a name to that IP; Caddy then gets a real HTTPS certificate for it.
1. **hPanel:** buy or open the KVM 2, OS **Ubuntu 24.04 with Docker**, location **Europe** (not India), add your SSH key. Note the **IP**. (Provisioning takes a few minutes.)
2. **Mac, in the project folder** (replace `<IP>`):
```bash
scp deploy/bootstrap.sh root@<IP>:/root/ && ssh root@<IP> 'bash /root/bootstrap.sh'
python3 deploy/make_env.py <IP>            # prints the new connector URL: keep it
rsync -az --exclude .git --exclude .venv --exclude '.env' --exclude '.env.*' --exclude __pycache__ --exclude .pytest_cache ./ root@<IP>:/opt/myt-mcp/
scp .env.production root@<IP>:/opt/myt-mcp/.env
ssh root@<IP> 'chmod 600 /opt/myt-mcp/.env && cd /opt/myt-mcp && docker compose up -d --build'
```
The build takes 5 to 10 minutes (it downloads Chrome). Do it at least an hour before the demo.
3. **Check:** `curl -s https://<ip-with-dashes>.sslip.io/health` answers `{"ok":true}`.
4. **claude.ai:** remove the old connector, add the new URL (`https://<ip-with-dashes>.sslip.io/mcp/<secret>`), open a new chat and ask for `task_plan`.
5. **The link for the client** is that connector URL. It carries the secret: send it only to the people who use it, and replace it (step 4 of the full guide) after the demo.

If something fails (certificate, a port, a build step) send me the output of `ssh root@<IP> 'cd /opt/myt-mcp && docker compose ps && docker compose logs --tail 60'`. Fallback for the demo only: run `scripts/start_all.sh` on the Mac (a quick-tunnel address, a new one each start).

The full guide follows.

---

Written 26 Oct 2026. Not tested on a real VPS yet (no access from the Mac): follow the steps and tell me where something differs. Files: `Dockerfile`, `docker-compose.yml`, `deploy/` (Caddyfile, `chrome/`, `make_env.py`, `bootstrap.sh`).

## What goes where
| Part | Today (Mac) | On the VPS |
|---|---|---|
| MCP server (`server.py`, port 8000) | `python server.py` | container `app` |
| Public HTTPS address | Cloudflare quick tunnel, a new URL at every start | container `caddy`, a fixed name and its own certificate |
| Automation Chrome (SATA, CP, Viator list, Aspire...) | Chrome on port 9333 | container `chrome` (a real Chrome in a virtual screen, profile kept in a volume) |
| **Claude in Chrome** (RateHawk, Skyscanner, TAP, El Al, GetYourGuide, Arbitrip, Ofran...) | the operator's own Chrome | **unchanged: it stays in the operator's browser.** Its scripts post their answers to `PUBLIC_BASE_URL/ingest/<token>`, which is now the VPS |

So the VPS replaces `start_all.sh` (Chrome 9333 + tunnel + server). The operator still needs Claude in Chrome on her own machine.

## Why a VPS also helps
- A fixed URL: the connector in claude.ai is added once and no longer has to be removed and added when the tunnel changes (a tool change still does).
- Ofran refuses Indian IPs (403). A server outside India can read Ofran by itself.
- It keeps running when the Mac is closed.
Risk to know: some sites treat datacenter IPs more strictly than a home line (the server-side reads: SATA, CP, Viator list, Aspire). Test them (step 7) before relying on it; GetYourGuide stays read in Claude in Chrome (`GYG_FIND_READ_IN_SERVER=0`).

## 1. Decide two things
1. **Location** (when you buy the VPS): pick Europe (Lithuania, Netherlands, Germany or France), not India.
2. **Name for the HTTPS address:** with no domain (today): `<ip-with-dashes>.sslip.io`, which `make_env.py <IP>` builds for you. Later, a subdomain you own (such as `mcp.yourdomain.com`, an A record to the IP) is nicer and has no third party in the name: run `make_env.py mcp.yourdomain.com` and replace the connector.

## 2. Create the VPS (hPanel)
1. VPS, KVM 2 (2 vCPU, 8 GB). Operating system: **Ubuntu 24.04 with Docker** if the list has it, otherwise plain Ubuntu 24.04 (the bootstrap installs Docker).
2. Add your SSH public key (Mac: `cat ~/.ssh/id_ed25519.pub`; if you have none: `ssh-keygen -t ed25519`). Set a root password too, but SSH keys will be the only way in.
3. Write down the IP address.
4. DNS (if you own a domain): an **A record** `mcp` to that IP. Check with `dig +short mcp.yourdomain.com`.
5. hPanel firewall (if enabled): allow TCP 22, 80, 443 and UDP 443. The bootstrap script sets the same on the machine.

## 3. First login and bootstrap (about 3 minutes)
From the Mac, in the project folder:
```bash
scp deploy/bootstrap.sh root@<IP>:/root/
ssh root@<IP> 'bash /root/bootstrap.sh'
```
It updates Ubuntu, installs Docker if missing, opens only 22, 80 and 443, starts fail2ban and automatic security updates. Then switch password login off (keys only):
```bash
ssh root@<IP> "sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && systemctl restart ssh"
```
(Open a second terminal and check `ssh root@<IP>` still works before you close the first one.)

## 4. Make the VPS's `.env`
On the Mac:
```bash
python3 deploy/make_env.py mcp.yourdomain.com        # or 203-0-113-7.sslip.io
```
It reads your local `.env` (MYT key, Arbitrip contract id, minisite code...), makes `.env.production` (mode 600, ignored by git), puts in a **new** connector secret, and prints the new connector URL. Keep that URL private. The old secret is not reused on the internet.

## 5. Copy the project and start it
```bash
rsync -az --exclude .git --exclude .venv --exclude '.env' --exclude '.env.*' --exclude __pycache__ --exclude .pytest_cache ./ root@<IP>:/opt/myt-mcp/
scp .env.production root@<IP>:/opt/myt-mcp/.env
ssh root@<IP> 'chmod 600 /opt/myt-mcp/.env && cd /opt/myt-mcp && docker compose up -d --build'
```
`myt_mcp/myt/suppliers.json` (client supplier directory, not in git) goes along with rsync. The first build takes a few minutes (it downloads Chrome). Watch it:
```bash
ssh root@<IP> 'cd /opt/myt-mcp && docker compose ps && docker compose logs --tail 40 app'
```
All three services should be `running`/`healthy`. Caddy needs ports 80 and 443 reachable to get its certificate.

## 6. Check it from outside
```bash
curl -s https://mcp.yourdomain.com/health                 # {"ok":true}
curl -s -o /dev/null -w "%{http_code}\n" https://mcp.yourdomain.com/    # 404: only /mcp, /ingest and /health are passed on
```
Then in claude.ai: Settings, Connectors, remove the old connector and add the new URL (`https://<name>/mcp/<new secret>`). Open a new chat and ask for `task_plan` (any kind): it should answer.

## 7. Test the server-side reads from the VPS
One chat per source, as in the prompt tests: a CP train (Lisbon to Porto), a SATA flight (Lisbon to Ponta Delgada), an Aspire lounge, a Viator list. If one shows a human check or "Access Denied" from the VPS's address, put it in `not_checked` as the answer says; do not try to get around it. Compare with the same search on the Mac. Ofran: with the server tools off, Ofran is still read in the operator's Chrome.

## 8. One-time manual setup in the VPS's Chrome (only if a site needs it)
The Chrome container has a screen you can see through noVNC, **only through an SSH tunnel** (port 6080 is published to the VPS's own 127.0.0.1):
```bash
ssh -L 6080:127.0.0.1:6080 root@<IP>
# then open http://localhost:6080/vnc.html in your browser and click Connect
```
Use it for things like setting Viator's currency to EUR, or a login a site asks for. **Type passwords yourself; Claude never does.** The profile is kept in the `chrome-profile` volume, so it survives restarts and updates.

## 9. Everyday use
```bash
cd /opt/myt-mcp      # on the VPS
docker compose logs -f app                                   # live log
docker compose logs --since 30m app | grep -E "TOOL |CHECK" # what a test run did
docker compose restart app                                   # restart only the server (in-memory ingest runs are lost, so do it between chats)
docker compose ps
```
**Update after a code change** (from the Mac):
```bash
rsync -az --exclude .git --exclude .venv --exclude '.env' --exclude '.env.*' --exclude __pycache__ --exclude .pytest_cache ./ root@<IP>:/opt/myt-mcp/
ssh root@<IP> 'cd /opt/myt-mcp && docker compose up -d --build app'
```
A tool signature or description change still needs the connector removed and added again in claude.ai.

**Rotate the connector secret:** run `make_env.py` again, copy the new `.env`, `docker compose up -d`, and replace the connector.
**Backups:** nothing precious lives only on the VPS except the Chrome profile (logins) and Caddy's certificates (they renew by themselves). `docker run --rm -v myt-mcp_chrome-profile:/d -v $PWD:/b alpine tar czf /b/chrome-profile.tgz -C /d .` saves the profile.
**Stop everything:** `docker compose down` (add `-v` to also delete the volumes).

## 10. What to do with the Mac setup
Keep `scripts/start_all.sh` as a fallback for a while. Do not run both at once against the same connector. Use only one `PUBLIC_BASE_URL` at a time: the Chrome scripts post to the address in the recipe they were given.

## Security notes
- Only 80 and 443 face the internet; the server and the Chrome DevTools port are on a private Docker network; noVNC is on 127.0.0.1 behind SSH.
- The connector secret in the URL is the lock on `/mcp/...`; `/ingest/<token>` takes one answer per token (96 bits, 3 hours). Caddy answers 404 to everything else.
- `.env` holds the MYT API key: mode 600, never in git or in an image (`.dockerignore` excludes it).
- The MYT key can read client trips: treat the VPS like the client's data (SSH keys only, updates on, no extra users).
- Hostinger's terms and the sites' terms: keep the rate limits already in the code (they are the same on the VPS).
