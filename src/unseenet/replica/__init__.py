"""``unseenet-replica``: a replica of a council registrar (UN-RFC 0054 Part II).

A council registrar has no owner: its members' replicas each decide the public name
claims the same way and sign the same certificates, and they also run the council
itself - admitting a shadow that has decided like them for 60 days, promoting it after
its probation, removing a member that misbehaves, falls silent or steps down - each
change one council manifest that every full member's replica computes alike and posts.
Anybody can start one: it begins as a **shadow** that issues nothing and only reports
what it would have decided.

- ``rules.py``: what every replica computes the same way, from public articles alone
- ``run.py``: one round over a ``Session``, and the loop
- ``cli.py``: ``unseenet-replica setup|run|status|agree|resign``
"""
