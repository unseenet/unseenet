"""The council's room (UN-RFC 0054 section 21, #819): its key is handed on by the
replicas themselves - a first epoch for the founding members, a grant to each newcomer,
and a new epoch without anybody who left - and nodes take only full members' keys,
the first one for each epoch."""

from datetime import timedelta

import pytest

from unseenet import names as nm
from unseenet.core.groups import envelope_tag

from tests.test_replica import net  # noqa: F401  - the fixture


async def rounds(reps, n=1):
    for _ in range(n):
        for r in reps:
            await r.run_once()


async def readable(s, room):
    return [m.body.strip() for m in await s.fetch_group(room) if m.readable and m.body.strip()]


async def test_the_replicas_hand_on_the_rooms_key(net, monkeypatch):  # noqa: F811
    a, b, c, founder = (net.session(n) for n in ("a", "b", "c", "project"))
    group, claims, room = await net.found([a, b, c], founder=founder, room=True)
    monkeypatch.setattr(nm, "NAMES_GROUP", group)
    reps = [net.replica(s, group) for s in (a, b, c)]
    first = min((a, b, c), key=lambda s: s.identity().key_text)

    # the first epoch: the full member whose key sorts first issues it, at once; the
    # others take their key at their next round
    await rounds(reps, 2)
    keys = await a.council_room_keys(room)
    assert [(k["kind"], k["epoch"], k["author"]) for k in keys] == [
        ("key-update", 1, first.identity().key_text)]
    # every member can read what another writes there
    await b.post(room, "Hej", "Kun for rådet\n")
    assert "Kun for rådet" in await readable(c, room)
    assert "Kun for rådet" in await readable(a, room)

    # nodes take keys only from full members, and one key update per epoch
    from unseenet.client.session import SessionError
    stranger = net.session("stranger")
    with pytest.raises(SessionError):
        await stranger.council_room_issue(room, 2, [stranger.identity().public_key])
    with pytest.raises(SessionError, match="set already"):
        await b.council_room_issue(room, 1, [b.identity().public_key])

    # a newcomer gets the key by a grant (the founder's way in, section 19)
    shadow = net.session("shadow")
    sh = net.replica(shadow, group)
    await founder.council_act(group, "admit", shadow.identity().key_text)
    for _ in range(20):
        net.clock = net.clock.replace(hour=21)
        await rounds([*reps, sh])
        if (await a.council_chain(group)).current.member(shadow.identity().public_key):
            break
        net.clock = net.clock.replace(minute=30) + timedelta(hours=4)
    await rounds(reps, 2)                       # the room in step, then the grant
    keys = await a.council_room_keys(room)
    assert keys[-1]["kind"] == "key-grant" and keys[-1]["epoch"] == 1
    assert envelope_tag(room, 1, shadow.identity().public_key) in keys[-1]["tags"]
    assert "Kun for rådet" in await readable(shadow, room)

    # a member leaves: a new epoch without it, closing the one before
    forged = nm.make_certificate(c.identity(), "microsoft", a.identity().key_text, 1,
                                 claim="<nothing@x>", claimed=net.clock)
    await reps[2].reg._post_json("name microsoft", forged.to_json() + "\n")
    net.clock += timedelta(days=9)
    await rounds([reps[0], reps[1], sh], 3)
    cur = (await a.council_chain(group)).current
    assert cur.member(c.identity().public_key) is None
    keys = await a.council_room_keys(room)
    new = [k for k in keys if k["kind"] == "key-update" and k["epoch"] == 2]
    assert len(new) == 1 and new[0]["closes"]
    assert envelope_tag(room, 2, c.identity().public_key) not in new[0]["tags"]
    assert envelope_tag(room, 2, shadow.identity().public_key) in new[0]["tags"]
    await a.fetch_group(room)
    await a.post(room, "Ny nøgle", "Efter Carl\n")
    assert "Efter Carl" in await readable(shadow, room)
    assert "Efter Carl" not in await readable(c, room)
