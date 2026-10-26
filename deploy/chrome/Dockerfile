# The automation Chrome the server drives over the DevTools protocol (SATA, CP, Viator list, Aspire...). A real, visible Chrome inside a virtual screen
# (not headless: many sites treat headless Chrome as a bot). The profile lives in a volume, so logins and settings survive a restart.
# Google Chrome is amd64 only: build this image on the VPS (amd64), not on an Apple-silicon Mac.
FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg xvfb x11vnc novnc websockify socat dbus-x11 procps \
      fonts-liberation fonts-noto-core fonts-noto-color-emoji \
 && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
 && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 chrome && mkdir -p /data/profile && chown -R chrome:chrome /data
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER chrome
ENV DISPLAY=:99 TZ=Asia/Jerusalem
# 9333: DevTools protocol (Docker network only); 6080: noVNC, to see and log in by hand (published to the VPS's own 127.0.0.1 only: reach it with an SSH tunnel)
EXPOSE 9333 6080
ENTRYPOINT ["/entrypoint.sh"]
