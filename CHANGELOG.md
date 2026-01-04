# Changelog

All notable changes to Solis Smart Charging will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.0] - 2025-12-07

### Added - Six-Slot Firmware Support
- **Six-slot firmware support** for HMI version >= 4B00 (0x4B00 hex)
- **Automatic firmware detection** via `inverterDetail` API HMI version check
- **Force mode configuration**: `force_mode` parameter (`auto`, `legacy`, `six_slot`)
- **Per-slot CID programming** using CIDs from hultenvp/solis-sensor mapping
- **Optional per-slot settings**: `set_charge_current` and `set_charge_soc` parameters
- **Six-slot readback verification**: Optional verification after each CID write

### Added - Safety & Diagnostics
- **Diagnostics mode**: `diagnostics_only` parameter for safe testing
- **Enhanced logging**: Structured, detailed logging throughout entire flow
- **Firmware detection logging**: Clear messages showing HMI version and detected mode
- **Operation logging**: Six-slot mode logs each CID operation before execution
- **Failed operation tracking**: Sensor attributes show which operations failed

### Added - Configuration
- `force_mode`: Override firmware auto-detection
- `max_slots`: Configure maximum charging windows (3 or 6)
- `diagnostics_only`: Test without writing to inverter
- `verify_readback`: Toggle readback verification (six-slot only)
- `control_retries`: Configurable retry attempts (default: 3)
- `control_delay`: Delay before readback verification (default: 0.1s)
- `inter_write_delay`: Delay between CID writes (default: 0.25s)
- `set_charge_current`: Enable per-slot current writes
- `charge_current`: Charge current value for per-slot writes
- `set_charge_soc`: Enable per-slot SOC writes
- `charge_soc`: Target SOC for per-slot writes

### Changed - Sensor Attributes
- Added `mode` attribute: Shows `"legacy"` or `"six_slot"`
- Added `hmi_version` attribute: Shows detected HMI firmware version
- Added `operations` attribute: (six-slot) List of executed CID operations
- Added `failed_operations` attribute: (six-slot) List of failed operations
- Enhanced `last_api_response`: More detailed status messages

### Retained from v3.2.0
- ✅ Automatic inverter time synchronization (CID 56)
- ✅ Timezone support via `inverter_timezone` parameter
- ✅ Enhanced multi-inverter selection logging
- ✅ Graceful handling of undefined secrets (unknown/unavailable/none)
- ✅ API response validation
- ✅ Unchanged window detection (skip update if schedule unchanged)

### Fixed
- Multi-inverter selection now logs all available inverters on failure
- Better error messages for API failures with last response text
- Improved JSON parsing with trailing comma handling

### Technical Details
- Six-slot time format: `"HH:MM-HH:MM"` per CID
- Six-slot CID ranges:
  - Charge time: 5946, 5949, 5952, 5955, 5958, 5961
  - Charge current: 5948, 5951, 5954, 5957, 5960, 5963
  - Charge SOC: 5928-5933
- Legacy mode: Single CID 103 with 3-window payload unchanged
- HMI detection threshold: >= 0x4B00 (decimal 19200)

### Backward Compatibility
- ✅ Existing automations work without modification
- ✅ Legacy 3-slot behavior unchanged
- ✅ All configuration parameters optional (safe defaults)
- ✅ Drop-in replacement for v3.2.0

### Documentation
- Comprehensive README with examples
- Migration guide from v3.x
- Troubleshooting section expanded
- Configuration reference complete
- Six-slot testing guide added

---

## [3.2.0] - 2025-12-03

### Added - Time Synchronization
- **Automatic inverter time sync** using CID 56 (NTP-based)
- Runs before every charging schedule update
- Prevents charging window drift due to inverter clock inaccuracies
- Default: enabled (can be disabled with `sync_inverter_time: false`)

### Added - Timezone Support
- **`inverter_timezone` parameter**: Configure timezone for time sync
- Supports all IANA timezone names (e.g., "Europe/London")
- Handles DST transitions automatically via Python zoneinfo
- Default: UTC (safe fallback)
- Graceful fallback to UTC if invalid timezone specified

### Added - Multi-Inverter Enhancements
- Enhanced diagnostic logging when inverter selection fails
- Logs all available inverters with ID, SN, Name, and ProductModel
- Helps users identify correct inverter for configuration

### Added - Configuration
- `sync_inverter_time`: Enable/disable time synchronization (default: true)
- `inverter_timezone`: IANA timezone for time sync (default: "UTC")

### Changed - Secret Handling
- Undefined secrets (unknown/unavailable/none) now treated as empty strings
- Allows auto-selection to work when secrets not defined
- No longer need to define inverter_sn/inverter_id if not using them

### Changed - API Validation
- Enhanced API response validation with better error messages
- Checks for unexpected data formats before processing
- Clearer error logging when API returns malformed JSON

### Changed - Sensor Attributes
- Added `time_sync` attribute: Shows "enabled" or "disabled"
- Added `timezone` attribute: Shows configured timezone

### Fixed
- Auto-selection now works correctly when inverter_sn/inverter_id undefined
- Better handling of API responses with missing or malformed data
- Improved error messages for troubleshooting

---

## [3.1.0] - 2025-11-15

### Added
- **Multi-inverter support**: Explicit inverter selection via SN or ID
- Auto-selection for storage inverters (ProductModel == 2)
- Fallback to single inverter if only one present
- Enhanced API robustness with better error handling

### Changed
- Improved inverter selection logic
- Better logging for inverter identification

---

## [3.0.0] - 2025-10-01

### Changed - Complete Rewrite
- **Complete rewrite** of window handling logic
- **Enhanced midnight crossover** handling
- **Better window merging** for contiguous dispatch blocks
- **Improved logging** throughout

### Added
- WindowProcessor class for cleaner dispatch logic
- Enhanced core window extension logic
- Better handling of overnight charging periods

### Fixed
- Midnight boundary issues
- Window merge edge cases
- Core hour protection logic

---

## [2.0.0] - 2025-08-15

### Changed
- Enhanced overnight charging behavior
- Improved early morning dispatch processing
- Better timezone-aware operations
- More robust window merging

### Added
- Timezone-aware datetime processing
- Smart handling of early morning dispatches (00:00-12:00)

---

## [1.0.0] - 2025-06-01

### Added - Initial Release
- Basic Octopus Intelligent dispatch synchronization
- Core charging hours (23:30-05:30)
- 3-slot charging window support (CID 103)
- Basic window normalization to 30-minute boundaries
- Simple contiguous window merging
- SolisCloud API authentication
- Basic logging

### Features
- Login authentication with SolisCloud
- Inverter list retrieval
- Single inverter control via CID 103
- Core window protection
- Dispatch window processing
- Local sensor updates

---

## Version Numbering

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** version: Incompatible API changes or significant functionality changes
- **MINOR** version: Added functionality in backward-compatible manner
- **PATCH** version: Backward-compatible bug fixes

### Version History Summary

- **4.x**: Six-slot firmware support, enhanced diagnostics
- **3.x**: Time sync, timezone support, multi-inverter improvements
- **2.x**: Overnight charging improvements, timezone handling
- **1.x**: Initial release, basic functionality

---

## Upgrade Recommendations

### From 3.2.0 → 4.0.0
- **Required**: Replace script file
- **Required**: Reload PyScript
- **Recommended**: First run with `diagnostics_only: true`
- **Optional**: Review new configuration parameters
- **Breaking changes**: None

### From 3.1.0 → 3.2.0
- **Required**: Replace script file
- **Required**: Reload PyScript
- **Recommended**: Add `inverter_timezone` if not in UTC
- **Breaking changes**: None

### From 3.0.0 → 3.1.0
- **Required**: Replace script file
- **Required**: Reload PyScript
- **Recommended**: Add `inverter_sn` if multi-inverter plant
- **Breaking changes**: None

### From 2.0.0 → 3.0.0
- **Required**: Replace script file
- **Required**: Reload PyScript
- **Breaking changes**: Window processing logic changed (improved)

---

## Support

For issues, please provide:
- Version number
- Firmware mode (legacy/six_slot)
- HMI version
- Full logs from one run
- Automation configuration (redacted)

## Links

- [GitHub Repository](https://github.com/your-repo/solis-smart-charging)
- [Home Assistant Community](https://community.home-assistant.io/)
- [Octopus Energy Integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy)
- [PyScript](https://github.com/custom-components/pyscript)
