 Demo ke liye 3 Terminal windows chahiye. Inhe isi order mein chalao.

      Terminal 1: Automation Chrome (SATA, Viator aur Aspire ke liye)
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        --user-data-dir="$HOME/myt-ofran-chrome" \
        --remote-debugging-port=9333 --remote-debugging-address=127.0.0.1
      Jo Chrome window khulegi, use demo ke dauraan band mat karna.

      Terminal 2: Cloudflare tunnel
      cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000
      Output mein ek URL aayega, jaise https://abc-xyz.trycloudflare.com. Woh copy kar lo. Har baar naya URL banta hai.

      Terminal 3: Naya tunnel URL .env mein daalo, phir server chalao
      cd ~/Desktop/project/myt-mcp
      TUNNEL=abc-xyz.trycloudflare.com   # Terminal 2 wala host, bina https://
      sed -i '' "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=127.0.0.1:*,localhost:*,$TUNNEL|" .env
      env -u MCP_SECRET -u MYT_API_KEY -u PORT -u ALLOWED_TRIP_IDS -u BROWSER_CDP_URL -u OFRAN_USE_BROWSER -u ALLOWED_HOSTS .venv/bin/python server.py
      (env -u … isliye hai taaki shell mein pehle se set koi purani value .env ko override na kare.)

      Check aur connector URL (Terminal 4 ya koi bhi naya tab):
      cd ~/Desktop/project/myt-mcp
      curl -s https://$TUNNEL/health          # {"ok":true} aana chahiye
      echo "https://$TUNNEL/mcp/$(grep '^MCP_SECRET=' .env | cut -d= -f2)"
      .venv/bin/python scripts/live_check.py   # saare sources PASS/FAIL
      Pehli command {"ok":true} deni chahiye. Doosri connector ka URL deti hai. Teesri saare sources pe ek live check chalati hai.

      Zaroori tips:
      - Yeh sab client ke join karne se 15–20 minute pehle kar lo. Tunnel ka URL naya hota hai, isliye Claude mein connector ka URL bhi update karna padega (Settings → Connectors). Yeh client ke saamne mat karna.
      - echo wali command screen share pe mat chalana, kyunki URL mein secret hai.
      - Client ke saamne bas live_check.py ka PASS/FAIL dikhana kaafi hai, achha lagta hai.
      - MYT mein quote bharne aur hotels ke liye apna normal Chrome (Claude in Chrome extension wala, Profile 5) bhi khula aur MYT mein logged-in rakhna.
      - Ofran (cars) India se FAIL hi dikhayega. Client ko pehle se bata dena ki yeh hosting ke baad chalega.

    ↑/↓ to scroll · c to copy · f to fork · Esc to close    