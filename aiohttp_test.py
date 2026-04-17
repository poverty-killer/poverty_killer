import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.kraken.com/0/public/Time") as r:
            print(r.status)
            print(await r.text())

asyncio.run(main())
