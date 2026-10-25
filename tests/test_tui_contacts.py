"""The address book (c) and writing a private post to a contact by name (UN-RFC 0028)."""

from unseenet.client.session import Session
from unseenet.client.tui import ContactsDialog, UnseenetApp
from unseenet.core import crypto
from unseenet.core.vault import Vault

from tuihelp import app_ready, stack, wait_for

KDF = {"ops": 1, "mem": 8192 * 1024}


async def test_contacts_and_recipient_by_name(tmp_path, monkeypatch):
    s = Session(Vault.open(tmp_path / "me.vault", "pw", **KDF), status=lambda *_: None)
    s.new_identity("me", "Me")
    s.add_node("127.0.0.1:1")      # without a node the first-run setup dialog opens on top
    sonia, mikkel, mia = (crypto.Identity.generate().key_text for _ in range(3))
    s.add_contact(sonia, "Sonia"); s.add_contact(mikkel, "Mikkel"); s.add_contact(mia, "Mia")
    s.save()
    monkeypatch.setenv("UNSEENET_PASSPHRASE", "pw")
    monkeypatch.setenv("UNSEENET_INSECURE_FAST_KDF", "1")
    app = UnseenetApp(tmp_path / "me.vault")
    async with app.run_test(size=(120, 36)) as pilot:
        assert await app_ready(pilot, app), stack(app)
        assert app._recipient("sonia") == sonia                 # a name, any case
        assert app._recipient("Mik") == mikkel                  # the start of one
        assert app._recipient("Mi") is None                     # Mikkel and Mia: say which
        assert app._recipient("nobody") is None
        assert app._recipient(mia) == mia                       # a key still works
        # the keys are random, so the words searched for are long enough not to be in one
        assert [n for _, n in s_contacts(app, "IKKEL")] == ["Mikkel"]      # any part, any case
        assert s_contacts(app, sonia.split(":", 1)[1][:12]) == [(sonia, "Sonia")]  # a key
        assert s_contacts(app, "nobody") == []

        app.action_contacts()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ContactsDialog)), stack(app)
        dlg = app.screen
        assert dlg.query_one("#find").has_focus
        await pilot.press(*"ikkel")                             # Mikkel only
        assert await wait_for(pilot, lambda: [n for _, n in dlg.shown] == ["Mikkel"], 400), \
            (dlg.query_one("#find").value, dlg.shown)
        assert "1 of 3" in str(dlg.query_one("#count").render())
        await pilot.press("escape")                             # clears the filter first
        assert await wait_for(pilot, lambda: len(dlg.shown) == 3, 400)
        assert app.screen is dlg
        await pilot.press("down")                               # Mia, Mikkel, Sonia
        assert dlg._chosen() == mikkel
        await pilot.press("escape")                             # now it closes
        assert await wait_for(pilot, lambda: not isinstance(app.screen, ContactsDialog), 400)

        app.action_contacts()
        assert await wait_for(pilot, lambda: isinstance(app.screen, ContactsDialog)), stack(app)
        await pilot.press(*"sonia", "enter")                    # Enter chats with Sonia
        assert await wait_for(pilot, lambda: app.current_group and sonia in app.current_group), \
            (app.current_group, stack(app))
        await pilot.press("q")


def s_contacts(app, q):
    return app.session.contacts(q)
