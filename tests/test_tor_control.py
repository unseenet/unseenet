"""TorControl keeps one command at a time on its connection (issue #127)."""

import asyncio

from unseenet.core.tor import TorControl


async def fake_tor(delay: float = 0.05):
    """A control port that answers each GETINFO slowly, echoing the key back."""

    async def handle(reader, writer):
        try:
            while line := await reader.readline():
                key = line.decode().split()[-1]
                await asyncio.sleep(delay)
                writer.write(f"250-{key}=a\r\n".encode())
                await writer.drain()
                await asyncio.sleep(delay)
                writer.write(b"250 OK\r\n")
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()  # Server.wait_closed() waits for every connection (3.12+)

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


async def fake_onion_tor(knows_pow: bool):
    """A control port that answers ADD_ONION, with or without the PoW argument
    (Tor before 0.4.9.2 answers 512 to an argument it does not know)."""
    seen = []

    async def handle(reader, writer):
        try:
            while line := await reader.readline():
                cmd = line.decode().strip()
                seen.append(cmd)
                if "PoWDefensesEnabled" in cmd and not knows_pow:
                    writer.write(b"512 Unrecognized option PoWDefensesEnabled\r\n")
                else:
                    writer.write(b"250-ServiceID=abc\r\n250-PrivateKey=ED25519-V3:k\r\n250 OK\r\n")
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], seen


async def test_the_onion_gets_the_pow_defence_when_tor_has_it():
    """#869, UN-RFC 0005: ADD_ONION with PoWDefensesEnabled=1; an older Tor answers 512
    and the service is made without it, and pow_defense says so."""
    for knows, want in ((True, True), (False, False)):
        server, port, seen = await fake_onion_tor(knows)
        async with server:
            ctl = await TorControl.connect("127.0.0.1", port)
            try:
                onion, key = await ctl.add_onion(None, 119, "127.0.0.1:1119", pow=True)
                assert onion == "abc.onion" and key == "ED25519-V3:k"
                assert ctl.pow_defense is want
                assert "PoWDefensesEnabled=1 Port=119,127.0.0.1:1119" in seen[0]
                assert len(seen) == (1 if knows else 2) and "PoW" not in seen[-1] or knows
            finally:
                await ctl.close()
    server, port, seen = await fake_onion_tor(True)
    async with server:
        ctl = await TorControl.connect("127.0.0.1", port)
        try:
            await ctl.add_onion(None, 119, "127.0.0.1:1119")            # not asked for
            assert "PoW" not in seen[0] and ctl.pow_defense is False
        finally:
            await ctl.close()
