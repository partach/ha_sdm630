## Changelog

### [0.3.5] - Direction correction and connection hardening
- Meter not reachable at startup: setup no longer fails; sensors stay unavailable and the connection is retried every 5 minutes
- Connection lost while running: retried after 30 s, 1 min, 2 min, then every 5 min until it is back; one error in the log when it drops and one message when it recovers
- A silent meter costs one request timeout per attempt instead of one per register group (was up to several minutes per poll)
- pymodbus' own background reconnect is turned off so it no longer competes with the integration, and request retries are lowered from 3 to 1
- Meters sharing one serial bus or TCP gateway no longer poll at the same time, so one meter can't drop the connection while another is reading
- Fixed a crash (`await` on a non-async `close()`) when the connection was lost mid-poll
- Fixed invalid units: reactive power now uses `var` (was `VAr`), VAh counter no longer claims the energy device class
- Config flow: the same meter (connection + Modbus address) can't be added twice; serial ports are offered by their stable `/dev/serial/by-id` path and a path can be typed in; connection test fails fast and reuses an already open bus instead of opening the port twice
- Labels and error messages for the setup dialogs
- Switching to a smaller register set removes the sensors that are no longer read
- Code clean-up: shared hub module, `entry.runtime_data`, entity naming per HA guidelines (entity IDs unchanged), lint passes in CI
- manifest: `pyserial` listed as requirement, pymodbus capped below 4.0
- Option "Invert power sign": flips phase and total power for meters wired or clamped the wrong way round
- Option "Swap import and export counters": reports export energy as import and vice versa
- Labels and help text for the options form

### [0.3.2] - Profiles added
- entry for setting update time

### [0.2.0] - First working version
- Serial tested and confirmed

### [0.1.0] - First version
- first code
