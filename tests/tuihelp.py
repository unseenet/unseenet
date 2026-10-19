"""Shared waiting for the TUI tests (#231).

The app does its work in workers: unlocking the vault, the first-run setup,
every dialog. A test that waits a fixed time, or only until ``app.session`` is
set, races them - and loses on a slow CI runner. Wait for the condition instead:

- :func:`app_ready` - the startup worker has finished, so no unlock or setup
  dialog can still appear on top of what the test opens next;
- :func:`wait_for` - any condition, polled every 50 ms;
- :func:`laid_out` / :func:`press` - a dialog's widget is on screen *with a place*
  (a dialog pushed from a worker is in the DOM before its first layout, and a click
  then lands on nothing), pressed through its own handler.
"""

from __future__ import annotations

STARTUP_SCREENS = ("UnlockDialog", "SetupDialog")


async def wait_for(pilot, cond, tries: int = 200) -> bool:
    for _ in range(tries):
        if cond():
            return True
        await pilot.pause(0.05)
    return False


def stack(app) -> str:
    """The screen stack, for assertion messages."""
    return " > ".join(type(s).__name__ for s in app.screen_stack)


def startup_done(app) -> bool:
    if app.session is None:
        return False
    if any(w.group == "startup" and not w.is_finished for w in app.workers):
        return False
    return not any(type(s).__name__ in STARTUP_SCREENS for s in app.screen_stack)


async def app_ready(pilot, app, tries: int = 300) -> bool:
    """True once the app has unlocked its vault and finished starting up."""
    ok = await wait_for(pilot, lambda: startup_done(app), tries)
    if ok:
        await pilot.pause()                     # let the first refresh settle
    return ok


def laid_out(app, selector: str) -> bool:
    found = app.screen.query(selector)
    return bool(found) and found.first().region.area > 0


async def press(pilot, app, selector: str) -> None:
    """Press a button on the current screen once it is laid out."""
    from textual.widgets import Button
    assert await wait_for(pilot, lambda: laid_out(app, selector)), stack(app)
    app.screen.query_one(selector, Button).press()
    await pilot.pause()
