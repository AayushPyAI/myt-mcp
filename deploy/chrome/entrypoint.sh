#!/bin/sh
# Virtual screen, a VNC view of it (for a one-time manual login), the DevTools port, then Chrome.
set -e
rm -f /tmp/.X99-lock

Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
for _ in 1 2 3 4 5 6 7 8 9 10; do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.5; done

x11vnc -display :99 -localhost -forever -shared -nopw -rfbport 5900 -quiet &      # reachable only inside this container
websockify --web /usr/share/novnc 6080 localhost:5900 &                         # noVNC: the compose file publishes 6080 to 127.0.0.1 of the VPS only
# Chrome listens on 127.0.0.1:9222 only and refuses a Host header that is not an IP address or localhost: socat gives the Docker network port 9333
socat TCP-LISTEN:9333,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:9222 &

exec google-chrome-stable \
  --user-data-dir=/data/profile \
  --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --no-sandbox --no-first-run --no-default-browser-check \
  --window-size=1440,900 --lang=en-US \
  about:blank
