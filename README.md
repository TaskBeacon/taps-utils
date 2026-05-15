# taps-utils

`taps-utils` provides strict tooling for TAPS task packages.

It does not include TAPS contract source files. Contract source files live in
`TaskBeacon/taps`.

Common usage:

```bash
taps-migrate-metadata E:/orgnize/03_tools/TaskBeacon --write
taps-validate E:/orgnize/03_tools/TaskBeacon/T000001-ax-cpt --contracts-root E:/orgnize/03_tools/TaskBeacon/taps/contracts --contracts-version v0.1.0
```
