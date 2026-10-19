# Commitment — 2026-10-19

SHA-256 of a tar archive containing 39 equal-circle packings found with
circlepack 0.1.0, each exact-verified (`circlepack verify --exact`), and
improving on the best-known radii published by Packomania on 2026-10-19.

693868112e2dfdf6f4542fa4e8b2ac71dace972d73fd04015bb863af7d4544db  candidates-2026-10-19.tar

The archive (solution JSON files plus a summary table) will be published
here after the packings have been submitted to Packomania. It was built
deterministically with:

    tar --sort=name --mtime='2026-10-19 00:00:00Z' --owner=0 --group=0 \
        --numeric-owner --format=gnu -cf candidates-2026-10-19.tar ...
