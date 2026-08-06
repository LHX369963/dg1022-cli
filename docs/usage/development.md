# Compatibility, development, and evidence

The `*IDN?` model and `DG...` serial are authoritative. USB product text can
mislabel this tested `1ab1:0588` DG1022 as DG3000 or DS1000. Do not issue
`USBTMC_IOCTL_EOM_ENABLE`; it times out on this unit. The transport normally
does not USBTMC-CLEAR; recovery is failure-only.

Known unit details: CH2 pulse duty requires `PULSe:DCYC:CH2`; coupling does not
make later SCPI frequency writes dynamically follow; `APPLy` is replayed by the
high-level output helper because unchanged function/frequency can retain stale
amplitude.

For code changes run `python -m pytest`. Connected acceptance is development
work, not a prerequisite for daily use; use `tools/live_acceptance.py` groups
instead of ad-hoc transport calls. Its reports and cross-instrument evidence are
in [`../validation.md`](../validation.md). Do not claim calibrated accuracy,
bandwidth, flatness, or endpoints beyond physical evidence.

Keep README and Skill as short navigation; put feature examples in `docs/usage/`.
