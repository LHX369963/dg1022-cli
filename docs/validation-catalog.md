# Catalog and transport validation

- 21/21 programming-guide subsystems represented
- 106 merged catalog entries
- 214 operations after expanding channel and query/write variants
- 98 live query instances audited; 95 returned directly
- Empty nonvolatile catalog and unnamed memory-slot responses account for two
  device-state-dependent cases
- CH2 pulse duty required `PULSe:DCYC:CH2`; that rendering is modeled explicitly

Original-value query-set writeback produced 66 direct passes from 82 instances.
The other 16 were internal parameters of disabled AM/FM/PM/FSK/sweep/burst modes.
After enabling each owning mode, all six mode families wrote and read back correctly.

The transport omits `USBTMC_IOCTL_EOM_ENABLE`, which makes this instrument time
out. It uses 2 ms query delay and 100 ms ordinary command delay. High-level phase
configuration adds a device-specific settling interval before `PHASe:ALIGN`.
