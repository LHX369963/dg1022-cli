# DG1022 Validation

Validation began 2026-07-19 on:

```text
RIGOL TECHNOLOGIES,DG1022,DG1D124605159,00.02.00.06.00.02.07
```

The recorded `/dev/usbtmc3` was only that session's dynamic node; the same
unit later appeared as `/dev/usbtmc2`. Prefer serial selection. Use `list` or
`info` only if selection or identity is uncertain. The physical fixture was DG
CH1 → DS1152E CH1 and DG CH2 → DS1152E CH2.

- [Catalog and transport validation](validation-catalog.md)
- [Functional checks and representative measurements](validation-functional.md)
- [Connected acceptance and final baseline](validation-acceptance.md)
- [2026-07-27 output-readback regression](validation-output-readback.md)

Machine-readable runs are in `../validation/*.json`. These reports are connected
development evidence, not required daily-use preflight.
