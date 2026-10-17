"""TorControl keeps one command at a time on its connection (issue #127)."""

import asyncio

from unseenet.core.tor import TorControl


async def fake_tor(delay: float = 0.05):
    """A control port that answers each GETINFO slowly, echoing the key back."""

    async def handle(reader, writer):
        while line := await reader.readline():
            key = line.decode().split()[-1]
            await asyncio.sleep(delay)
            writer.write(f"250-{key}=a\r\n".encode())
            await writer.drain()
            await asyncio.sleep(delay)
            writer.write(b"250 OK\r\n")
            await writer.drain()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_concurrent_commands_get_their_own_replies():
    server, port = await fake_tor()
    async with server:
        ctl = await TorControl.connect("127.0.0.1", port)
        try:
            keys = [f"key{i}" for i in range(5)]
            replies = await asyncio.wait_for(
                asyncio.gather(*(ctl.command(f"GETINFO {k}") for k in keys)), 5)
            assert [r[0] for r in replies] == [f"{k}=a" for k in keys]
        finally:
            await ctl.close()


async def test_a_timed_out_shielded_command_does_not_leak_its_reply():
    server, port = await fake_tor(delay=0.1)
    async with server:
        ctl = await TorControl.connect("127.0.0.1", port)
        try:
            try:
                await asyncio.wait_for(asyncio.shield(ctl.command("GETINFO first")), 0.05)
            except asyncio.TimeoutError:
                pass
            assert (await asyncio.wait_for(ctl.command("GETINFO second"), 5))[0] == "second=a"
        finally:
            await ctl.close()
