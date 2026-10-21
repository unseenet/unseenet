# Ripening chains of the project's CI keys

Key ripening (UN-RFC 0025) is computed once, not in every CI run. These files
hold the **public** ripening chain of the keys CI posts with (the announce and
canary key, `UNSEENET_ANNOUNCE_SEED`); the workflows point `UNSEENET_STATE_DIR`
here. They contain no secret: the chain is published in the key's `ripe@` group
anyway.

To make or extend one, on any machine, from the public key alone:

    unseenet ripen --public-key ed25519:... --to 0 --state tools/ripening/<fingerprint>.state.json

then commit the file. Level 0 takes about 7-11 minutes.
