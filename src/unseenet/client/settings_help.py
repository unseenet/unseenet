"""Help for Edit group (unseenet-gui#178): per setting, what it does, whom it affects and
what changes later - the same text in every client, as the HELP for your own rules is.

Belongs here: the words only. Not here: the settings themselves (localapi.api.running,
``group_settings``) or the manifest fields they become (core.groups, the UN-RFCs named).
"""

from __future__ import annotations

INTRO = ("Every save is a new version of the group's manifest, signed with your key. What it "
         "says about posting applies to what is posted after it: what nodes already carry "
         "stays as it is. The type, the owner and the Group ID never change (UN-RFC 0004).")

# key: the field in POST /api/groups/<id>/settings; label: as the clients name it;
# what: what it does; affects: who or what it acts on; later: what changing it does
GROUP_SETTINGS_HELP: tuple[dict, ...] = (
    {"key": "title", "label": "Title and description",
     "what": "The name and the line shown under the group's ID.",
     "affects": "Readers: shown in group lists and searches.",
     "later": "Change them any time."},
    {"key": "view", "label": "Shown as",
     "what": "Threads (posts and replies) or chat (messages in order) - how clients show it "
             "by default (UN-RFC 0008).",
     "affects": "Readers: clients only; nodes do not care. A reader may still switch.",
     "later": "Change it any time; nothing posted changes."},
    {"key": "kinds", "label": "Takes",
     "what": "Posts with a subject, chat lines, or both (UN-RFC 0028).",
     "affects": "Writers: nodes refuse other kinds in open, moderated and channel groups; "
                "in a closed group clients do.",
     "later": "Applies to what is posted after it; what is there stays."},
    {"key": "files", "label": "Files",
     "what": "Whether posts may carry pictures or files, which kinds and how big (UN-RFC 0027).",
     "affects": "Writers and nodes: nodes refuse files the group does not take, and each "
                "node decides whether it carries files at all.",
     "later": "Applies to new posts; files already posted stay until they expire."},
    {"key": "reactions", "label": "Reactions",
     "what": "The view's default, none, any emoji, or your own set of up to 12 (UN-RFC 0048).",
     "affects": "Readers and nodes: nodes refuse reactions the group does not take.",
     "later": "Applies to reactions given after it; those given before stay."},
    {"key": "comments", "label": "Comments",
     "what": "On a channel or feed: whether others may comment on what you publish, and "
             "for how many days after it (UN-RFC 0030, 0034).",
     "affects": "Readers who would comment; nodes enforce it.",
     "later": "Applies to comments after it; earlier comments stay."},
    {"key": "min_pow", "label": "Postage",
     "what": "The proof-of-work every post here must carry, against spam (UN-RFC 0001).",
     "affects": "Writers: higher postage takes longer to send. Nodes enforce it, and may "
                "ask for more than the group does.",
     "later": "Applies to what is posted after it."},
    {"key": "retention_days", "label": "Kept for",
     "what": "How long nodes are asked to keep posts (UN-RFC 0004, 0012).",
     "affects": "Nodes: a suggestion; each node keeps what its operator decides.",
     "later": "Change it any time; nodes follow it as they see fit."},
    {"key": "low_latency", "label": "Fast forwarding",
     "what": "Nodes pass posts on without the random delay that hides when they were "
             "written (UN-RFC 0008).",
     "affects": "Everyone here: quicker, but it tells more about when people write.",
     "later": "Change it any time."},
    {"key": "charter", "label": "Charter",
     "what": "What the group is for and what it asks of those who write here, shown to "
             "people before they post (UN-RFC 0014).",
     "affects": "Writers: shown, never enforced by machines - moderators act on it. Each "
                "reader's own rules decide what they see.",
     "later": "Change it any time."},
    {"key": "report_issuers", "label": "Spam reports here",
     "what": "Spam report issuers readers follow here by default, so spam is hidden from "
             "the start (UN-RFC 0045).",
     "affects": "Readers: each can turn them off; a hidden post always says who hid it.",
     "later": "Change the list any time; readers' own choices stay theirs."},
    {"key": "languages", "label": "Languages",
     "what": "The languages written here, the first the main one (UN-RFC 0052).",
     "affects": "Writers: clients suggest them for new posts. Readers: found by language.",
     "later": "Change them any time; posts keep the language they were written in."},
    {"key": "tags", "label": "Tags",
     "what": "Up to 8 tags every post here has - a topic, or a warning such as sexual "
             "(UN-RFC 0052).",
     "affects": "Readers: their clients and rules treat every post as having them, shown "
                "apart from the author's own.",
     "later": "Change them any time; they apply to every post, old ones too."},
    {"key": "labellers", "label": "Labellers",
     "what": "Labellers named for this group, whose labels readers see here (UN-RFC 0053).",
     "affects": "Readers: each decides whether to use them.",
     "later": "Change the list any time."},
    {"key": "index", "label": "Search engines",
     "what": "On a site: whether search engines may index it through a web entrance "
             "(UN-RFC 0035).",
     "affects": "The whole web: copies in search engines are outside Unseenet.",
     "later": "Turning it off stops new indexing, but copies can outlive the pages."},
    {"key": "team_name", "label": "Team name",
     "what": "In a team inbox: the name replies go out under (UN-RFC 0047).",
     "affects": "The people you answer: they see the team's name, not yours.",
     "later": "Change it any time; replies already sent keep the old name."},
)


def group_settings_help() -> dict:
    """``{"intro", "settings": [{key, label, what, affects, later}]}``, the text for a help
    panel beside Edit group - the same in every client."""
    return {"intro": INTRO, "settings": [dict(s) for s in GROUP_SETTINGS_HELP]}
