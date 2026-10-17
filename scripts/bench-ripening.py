#!/usr/bin/env python3
"""Measure key-ripening speed (UN-RFC 0025) on this machine.

Runs the Wesolowski VDF over 1024-bit class groups (chiavdf) for a few
iteration counts on ONE core, then times verification. Prints iterations
per second and how long each ripening level would take here.

    pip install chiavdf
    python3 scripts/bench-ripening.py            # ~1-2 minutes
    python3 scripts/bench-ripening.py --quick    # ~15 seconds

Please post the output in issue #121 together with the machine you ran it on.
"""
import argparse, hashlib, os, platform, statistics, time

import chiavdf

DISC_BITS = 1024
GENERATOR = bytes([0x08]) + bytes(99)   # compressed form (2, 1, c), as in chiavdf
LEVELS = [(0, 27), (1, 30), (2, 33), (3, 36), (4, 38)]   # level, log2(t) - UN-RFC 0025 section 4


def human(seconds):
    for unit, size in (("days", 86400), ("hours", 3600), ("minutes", 60)):
        if seconds >= size:
            return f"{seconds / size:.1f} {unit}"
    return f"{seconds:.1f} seconds"


def cpu_name():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith(("model name", "Model", "Hardware")):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    seed = hashlib.sha256(b"UNSEENET-RIPEN-1\x00" + os.urandom(32)).digest()
    disc = chiavdf.create_discriminant(seed, DISC_BITS)
    exps = [18, 20] if args.quick else [18, 20, 22, 23]

    print(f"Machine: {cpu_name()} ({platform.machine()}), {platform.system()} {platform.release()}")
    print(f"chiavdf, {DISC_BITS}-bit discriminant, one core\n")

    rates = []
    for e in exps:
        t = 2 ** e
        start = time.perf_counter()
        result = chiavdf.prove(seed, GENERATOR, DISC_BITS, t, "")
        elapsed = time.perf_counter() - start
        size = len(result) // 2
        y, proof = result[:size], result[size:]

        vt = []
        for _ in range(5):
            v0 = time.perf_counter()
            ok = chiavdf.verify_wesolowski(disc, GENERATOR, y, proof, t)
            vt.append(time.perf_counter() - v0)
        if not ok:
            raise SystemExit(f"verification FAILED at t=2^{e}")
        rate = t / elapsed
        rates.append(rate)
        print(f"t = 2^{e:<2}  prove {elapsed:7.2f} s  {rate:>10,.0f} it/s   "
              f"verify {statistics.median(vt) * 1000:6.2f} ms   proof {len(result)} bytes")

    rate = rates[-1]   # largest run: least start-up overhead
    print(f"\nRipening time here at {rate:,.0f} iterations/second:")
    for level, e in LEVELS:
        print(f"  level {level}  t = 2^{e}  {human(2 ** e / rate)}")


if __name__ == "__main__":
    main()
