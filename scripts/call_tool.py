"""Call one tool of the running local server and print its JSON answer: .venv/bin/python scripts/call_tool.py <tool> '{"arg": 1}'"""
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
env = dict(l.strip().split("=",1) for l in open(".env") if "=" in l and not l.startswith("#"))
URL = f"http://127.0.0.1:{env.get('PORT','8000')}/mcp/{env['MCP_SECRET']}"
async def main(name, args):
    async with streamable_http_client(URL) as (r, w, *_):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(name, args, read_timeout_seconds=240.0)
            print(res.content[0].text)
asyncio.run(main(sys.argv[1], json.loads(sys.argv[2])))
