import asyncio, logging, json, sys
logging.disable(logging.CRITICAL)
from dotenv import load_dotenv; load_dotenv(".env")
from mcp.client import Client
from myt_mcp.config import Settings
from myt_mcp.app import create_server
S="/private/tmp/claude-501/-Users-etech-Desktop-project/f648b16e-8ba7-4718-ae97-17a0b3651493/scratchpad/ref_"
async def main(name,args,tag):
    async with Client(create_server(Settings.from_env())) as c:
        r=await c.call_tool(name,args)
        t=r.content[0].text
        open(S+tag+".json","w").write(t)
        print("ERR" if r.is_error else "OK", len(t))
        if r.is_error: print(t[:400])
asyncio.run(main(sys.argv[1],json.loads(sys.argv[2]),sys.argv[3]))
