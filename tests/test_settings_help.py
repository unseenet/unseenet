"""unseenet-gui#178: the help for Edit group - the same text in every client."""

from unseenet.client.localapi import LocalAPI
from unseenet.client.localapi.api import SETTINGS_FIELDS
from unseenet.client.settings_help import GROUP_SETTINGS_HELP, group_settings_help


def test_every_help_names_a_setting_and_says_all_three():
    keys = [s["key"] for s in GROUP_SETTINGS_HELP]
    assert len(keys) == len(set(keys))
    for s in GROUP_SETTINGS_HELP:
        assert s["key"] in SETTINGS_FIELDS, s["key"]
        assert all(s[k].strip() for k in ("label", "what", "affects", "later")), s["key"]
    # the main settings of Edit group all have help
    assert {"title", "view", "kinds", "files", "reactions", "rules", "min_pow",
            "report_issuers", "tags", "languages", "team_name", "index"} <= set(keys)


def test_from_the_local_api_without_a_vault(tmp_path):
    d = LocalAPI(tmp_path / "me.vault").group_settings_help()      # locked: still there
    assert d == group_settings_help() and "never change" in d["intro"]
    d["settings"][0]["label"] = "changed"                    # a copy: the text stays
    assert group_settings_help()["settings"][0]["label"] != "changed"
