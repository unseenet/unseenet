"""A council's machine groups are data groups (#928, UN-RFC 0008 section 3.1.1): its
claims, proposals, log, reports, lists and announcement groups are hidden like the
project's data groups and not counted as unread, while talk and room stay for people.
A manifest cannot hide somebody else's group."""

from unseenet.client.session import Session
from unseenet.known_nodes import DATA_GROUPS

COUNCIL = "unseenet.lists@aaaaaaaaaaaaaaaa"
PARTS = {
    "claims": "unseenet.lists.claims@bbbbbbbbbbbbbbbb",
    "proposals": "unseenet.lists.proposals@cccccccccccccccc",
    "log": "unseenet.lists.log@dddddddddddddddd",
    "reports": "unseenet.lists.reports@eeeeeeeeeeeeeeee",
}
TALK = "unseenet.lists.talk@ffffffffffffffff"
NODES = "unseenet.nodes@gggggggggggggggg"
GATEWAYS = "unseenet.gateways@hhhhhhhhhhhhhhhh"


def _council(**fields):
    return {"name": "unseenet.lists", "type": "channel", "v": 1, "serial": 1,
            "council": {"seq": 1, "members": []}, **fields}


def _session(groups: dict) -> Session:
    s = Session.__new__(Session)
    s.vault = type("V", (), {"data": {"groups": {gid: {"manifest": m}
                                                 for gid, m in groups.items()}}})()
    return s


def test_what_a_council_keeps_for_programs():
    s = _session({COUNCIL: _council(**PARTS, talk=TALK, lists={"nodes": NODES},
                                    announce={"gateways": GATEWAYS})})
    for gid in (COUNCIL, NODES, GATEWAYS, *PARTS.values()):
        assert s.is_data_group(gid), gid
    assert not s.is_data_group(TALK)                   # for people


def test_talk_and_room_alone_are_not_a_council_of_data():
    s = _session({TALK: _council(name="unseenet.lists.talk")})
    assert not s.is_data_group(TALK)


def test_a_council_cannot_hide_somebody_elses_group():
    snak = "dk.snak@iiiiiiiiiiiiiiii"
    own = "unseenet.lists.chat@jjjjjjjjjjjjjjjj"
    s = _session({COUNCIL: _council(proposals=snak, log=own),
                  own: {"name": "unseenet.lists.chat", "owner": "ed25519:x", "view": "chat"}})
    assert not s.is_data_group(snak)                   # not under the council's name
    assert not s.is_data_group(own)                    # under it, but not a council's group


def test_a_group_that_is_not_a_council_names_nothing():
    s = _session({"alt.x@kkkkkkkkkkkkkkkk": {"name": "alt.x", "owner": "ed25519:x",
                                             "proposals": "alt.x.y@llllllllllllllll"}})
    assert not s.is_data_group("alt.x.y@llllllllllllllll")


def test_the_projects_councils_are_known_before_their_manifests():
    for gid in ("unseenet.lists.proposals@oekxy7cbxvezla4f", "unseenet.names@xvchjwehdhfptpza",
                "unseenet.nodes@gjv472lkhc375x4h"):
        assert gid in DATA_GROUPS
    assert not any(".talk@" in g for g in DATA_GROUPS)
