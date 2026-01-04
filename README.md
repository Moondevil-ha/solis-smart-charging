# Solis Smart Charging for Home Assistant

PyScript for synchronizing Solis inverter charging windows with Octopus Energy Intelligent dispatch periods. Automatically adjusts battery charging schedules to maximize use of cheaper dispatch periods while maintaining protected core charging hours.

**Version 4.0.0** - Now with 6-slot firmware support!

---

## 🆕 What's New in v4.0.0

- **Six-slot firmware support** (HMI version >= 4B00) - program up to 6 charging windows
- **Automatic firmware detection** - script detects your firmware and uses the correct mode
- **Backward compatible** - works seamlessly with legacy 3-slot firmware
- **Enhanced diagnostics mode** - safely test without writing to your inverter
- **Automatic time synchronization** - keeps inverter clock accurate (v3.2.0 feature retained)
- **Timezone support** - configure time sync for your location
- **Enhanced multi-inverter logging** - better troubleshooting when selection fails

---

## Quick Start

**For most users (3-slot firmware):**
1. Install script → Add automation → Done!

**For 6-slot firmware users:**
1. Install script
2. First run with `"diagnostics_only": true`
3. Check logs to verify detection
4. Remove diagnostics flag and run normally

---

## Features

### Core Functionality
* Automatically syncs Solis inverter charge windows with Octopus Energy Intelligent dispatch periods
* Protected core charging hours (default 23:30–05:30, auto-extends if dispatches overlap)
* Smart window management:
  - Normalizes dispatches to 30-minute boundaries
  - Merges contiguous windows automatically
  - Selects optimal additional windows based on duration

### Firmware Support
* **Legacy firmware (3 slots)**: Programs schedule via CID 103
* **New firmware (6 slots, HMI >= 4B00)**: Programs via per-slot CIDs
* **Auto-detection**: Examines HMI version and chooses correct mode
* **Manual override**: Force legacy or six-slot mode if needed

### Advanced Features
* **Multi-inverter support**: Auto-selects storage inverters or use explicit SN/ID
* **Automatic time sync**: Keeps inverter clock accurate using NTP
* **Timezone-aware**: Configure time sync for your location
* **Diagnostics mode**: Validate detection and schedule without writing to inverter
* **Unchanged detection**: Only updates inverter when schedule changes
* **Comprehensive logging**: Detailed feedback for troubleshooting

---

## Prerequisites

- Home Assistant installation
- Solis inverter with battery storage
- Octopus Energy Intelligent tariff
- [Octopus Energy Integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy) installed
- [PyScript Integration](https://github.com/custom-components/pyscript) installed

---

## Installation

### 1. Enable PyScript

Add to `configuration.yaml`:

```yaml
pyscript:
  allow_all_imports: true
  hass_is_global: true
```

### 2. Create Input Text Entities

Add to `configuration.yaml`:

```yaml
input_text:
  solis_api_secret:
    name: Solis API Secret
    initial: !secret solis_api_secret
  solis_api_key:
    name: Solis API Key
    initial: !secret solis_api_key
  solis_username:
    name: Solis Username
    initial: !secret solis_username
  solis_password:
    name: Solis Password
    initial: !secret solis_password
  solis_plant_id:
    name: Solis Plant ID
    initial: !secret solis_plant_id

  # Optional (for multi-inverter plants)
  solis_inverter_sn:
    name: Solis Inverter Serial (optional)
    initial: !secret solis_inverter_sn
  solis_inverter_id:
    name: Solis Inverter ID (optional)
    initial: !secret solis_inverter_id
```

### 3. Add Secrets

Add to `secrets.yaml`:

```yaml
solis_api_secret: "your_api_secret"
solis_api_key: "your_api_key_id"
solis_username: "your_soliscloud_username"
solis_password: "your_soliscloud_password"
solis_plant_id: "your_plant_id"

# Optional (only needed for multi-inverter plants)
# You can omit these entirely if you have a single inverter
solis_inverter_sn: "your_hybrid_inverter_sn"
# OR
solis_inverter_id: "your_hybrid_inverter_id"
```

### 4. Copy the Script

Copy `solis_smart_charging.py` to:
```
config/pyscript/solis_smart_charging.py
```

### 5. Reload PyScript

Developer Tools → YAML → Reload PyScript (or restart Home Assistant)

---

## Configuration

The script is executed via Home Assistant automation and receives configuration as a JSON block.

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `secret` | Solis API Secret | From SolisCloud API Management |
| `key_id` | Solis API Key ID | From SolisCloud API Management |
| `username` | SolisCloud username | Your login email |
| `password` | SolisCloud password | Your login password |
| `plantId` | Solis station/plant ID | Found in SolisCloud URL |
| `dispatch_sensor` | Entity ID with `planned_dispatches` | `binary_sensor.octopus_energy_xxx_intelligent_dispatching` |

### Optional Parameters - Multi-Inverter

| Parameter | Default | Description |
|-----------|---------|-------------|
| `inverter_sn` | auto-detect | Explicit inverter serial number (recommended for multi-inverter) |
| `inverter_id` | auto-detect | Explicit inverter ID (alternative to SN) |

**Note:** If neither `inverter_sn` nor `inverter_id` is specified, the script will:
1. Auto-select if there's only one storage inverter (ProductModel=2)
2. Auto-select if there's only one inverter total
3. Otherwise, fail with error showing available inverters

### Optional Parameters - Firmware Mode

| Parameter | Default | Description |
|-----------|---------|-------------|
| `force_mode` | `"auto"` | `"auto"` (detect), `"legacy"` (force 3-slot), or `"six_slot"` (force 6-slot) |
| `max_slots` | `3` | Maximum charging windows: `3` or `6` |

### Optional Parameters - Safety & Diagnostics

| Parameter | Default | Description |
|-----------|---------|-------------|
| `diagnostics_only` | `false` | If `true`, calculates schedule but doesn't write to inverter |
| `verify_readback` | `true` | If `true`, reads back each CID after writing (six-slot only) |
| `control_retries` | `3` | Number of retry attempts for failed control writes |
| `control_delay` | `0.1` | Seconds to wait before readback verification |
| `inter_write_delay` | `0.25` | Seconds between consecutive CID writes (six-slot only) |

### Optional Parameters - Time Sync (v3.2.0+)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sync_inverter_time` | `true` | Enable automatic time synchronization |
| `inverter_timezone` | `"UTC"` | IANA timezone name (e.g., `"Europe/London"`) |

**Timezone Examples:**
- UK: `"Europe/London"` (handles BST automatically)
- Europe: `"Europe/Paris"`, `"Europe/Berlin"`
- US: `"America/New_York"`, `"America/Los_Angeles"`
- [Full list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

### Optional Parameters - Six-Slot Per-Window Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `set_charge_current` | `false` | Write charge current to each slot |
| `charge_current` | `"60"` | Charge current value (amps) |
| `set_charge_soc` | `false` | Write charge SOC to each slot |
| `charge_soc` | `"100"` | Target SOC percentage |

---

## Automation Examples

### Basic Configuration (Auto-Detect)

**Replace `<YOUR_ACCOUNT>` with your Octopus account ID!**

```yaml
alias: Sync Solis Charging with Octopus Dispatch
description: ""
trigger:
  - platform: state
    entity_id: binary_sensor.octopus_energy_<YOUR_ACCOUNT>_intelligent_dispatching
    attribute: planned_dispatches
condition:
  - condition: template
    value_template: >
      {% set d = state_attr('binary_sensor.octopus_energy_<YOUR_ACCOUNT>_intelligent_dispatching', 'planned_dispatches') %}
      {{ d is not none }}
action:
  - service: pyscript.solis_smart_charging
    data:
      config: |-
        {
          "secret": "{{ states('input_text.solis_api_secret') }}",
          "key_id": "{{ states('input_text.solis_api_key') }}",
          "username": "{{ states('input_text.solis_username') }}",
          "password": "{{ states('input_text.solis_password') }}",
          "plantId": "{{ states('input_text.solis_plant_id') }}",
          "dispatch_sensor": "binary_sensor.octopus_energy_<YOUR_ACCOUNT>_intelligent_dispatching"
        }
mode: single
```

### Multi-Inverter Configuration

Add `inverter_sn` parameter:

```yaml
action:
  - service: pyscript.solis_smart_charging
    data:
      config: |-
        {
          "secret": "{{ states('input_text.solis_api_secret') }}",
          "key_id": "{{ states('input_text.solis_api_key') }}",
          "username": "{{ states('input_text.solis_username') }}",
          "password": "{{ states('input_text.solis_password') }}",
          "plantId": "{{ states('input_text.solis_plant_id') }}",
          "dispatch_sensor": "binary_sensor.octopus_energy_<YOUR_ACCOUNT>_intelligent_dispatching",
          "inverter_sn": "{{ states('input_text.solis_inverter_sn') }}"
        }
```

### First-Time Six-Slot Testing

Add diagnostics mode for safe testing:

```yaml
action:
  - service: pyscript.solis_smart_charging
    data:
      config: |-
        {
          "secret": "{{ states('input_text.solis_api_secret') }}",
          "key_id": "{{ states('input_text.solis_api_key') }}",
          "username": "{{ states('input_text.solis_username') }}",
          "password": "{{ states('input_text.solis_password') }}",
          "plantId": "{{ states('input_text.solis_plant_id') }}",
          "dispatch_sensor": "binary_sensor.octopus_energy_<YOUR_ACCOUNT>_intelligent_dispatching",
          "diagnostics_only": true
        }
```

**After verifying logs and sensor attributes, remove `"diagnostics_only": true` line**

### Force Six-Slot Mode

If auto-detection fails:

```yaml
{
  "secret": "{{ states('input_text.solis_api_secret') }}",
  "key_id": "{{ states('input_text.solis_api_key') }}",
  "username": "{{ states('input_text.solis_username') }}",
  "password": "{{ states('input_text.solis_password') }}",
  "plantId": "{{ states('input_text.solis_plant_id') }}",
  "dispatch_sensor": "binary_sensor.octopus_energy_<YOUR_ACCOUNT>_intelligent_dispatching",
  "force_mode": "six_slot",
  "max_slots": 6
}
```

### UK Time Sync Configuration

```yaml
{
  "secret": "{{ states('input_text.solis_api_secret') }}",
  "key_id": "{{ states('input_text.solis_api_key') }}",
  "username": "{{ states('input_text.solis_username') }}",
  "password": "{{ states('input_text.solis_password') }}",
  "plantId": "{{ states('input_text.solis_plant_id') }}",
  "dispatch_sensor": "binary_sensor.octopus_energy_<YOUR_ACCOUNT>_intelligent_dispatching",
  "inverter_timezone": "Europe/London"
}
```

---

## Upgrading from v3.x

### Do I Need to Change Anything?

**No!** Version 4.0.0 is fully backward compatible.

- Existing automations continue to work without modification
- Legacy 3-slot firmware operates exactly as before
- New features are opt-in

### Recommended First Steps

1. **Update the script** - Replace `solis_smart_charging.py` with v4.0.0
2. **Reload PyScript** - Developer Tools → YAML → Reload PyScript
3. **First run with diagnostics** - Temporarily add `"diagnostics_only": true`
4. **Check the logs** - Look for firmware detection messages
5. **Check the sensor** - Review `sensor.solis_charge_schedule` attributes
6. **Remove diagnostics flag** - Remove the diagnostics line and run normally

### What to Look For in Logs

```
INFO Firmware detection complete: HMI=4b05, six_slot=True, force_mode=auto, final_max_slots=6
```

This tells you:
- Your HMI version (4b05 in example)
- Whether six-slot was detected (True/False)
- How many slots will be used (6 in example)

### Sensor Attributes Added in v4.0.0

Check `sensor.solis_charge_schedule` attributes:
- `mode`: `"legacy"` or `"six_slot"`
- `hmi_version`: Detected HMI version
- `operations`: (six-slot only) List of CID operations executed
- `time_sync`: `"enabled"` or `"disabled"`
- `timezone`: Configured timezone for time sync

---

## How It Works

### High-Level Flow

1. **Login** - Authenticates with SolisCloud API
2. **Inverter Selection** - Identifies the controllable inverter
3. **Time Sync** - Syncs inverter clock with Home Assistant (CID 56)
4. **Firmware Detection** - Checks HMI version to determine 3-slot vs 6-slot
5. **Dispatch Processing**:
   - Reads Octopus Intelligent `planned_dispatches`
   - Normalizes to 30-minute boundaries
   - Merges contiguous windows
   - Applies core window logic (23:30–05:30 protected, may extend)
   - Selects additional windows up to slot limit
6. **Schedule Programming**:
   - **Legacy**: Single CID 103 write with 3 windows
   - **Six-slot**: Multiple CID writes (one per slot time)
7. **Sensor Update** - Updates `sensor.solis_charge_schedule`

### Firmware Detection Logic

```
1. Check force_mode configuration
   - If "legacy" → use 3-slot CID 103
   - If "six_slot" → use 6-slot CIDs
   - If "auto" → continue to step 2

2. Query inverterDetail API for HMI version
   
3. Parse HMI version as hexadecimal
   - If >= 0x4B00 (decimal 19200) → six-slot
   - Otherwise → legacy

4. If six-slot detected, ensure max_slots >= 6
```

### Window Selection Logic

```
1. Core window (23:30-05:30) is always slot 1
2. If dispatches overlap core → extend core window
3. Remaining dispatches sorted by duration (longest first)
4. Select top N-1 dispatches (where N = max_slots)
5. Fill remaining slots with 00:00-00:00 (disabled)
```

---

## Entities Created

### sensor.solis_charge_schedule

**State**: Comma-separated list of active windows (e.g., `"23:30-05:30, 13:00-14:00"`)

**Attributes**:
- `charging_windows`: Full list of windows (3 or 6 depending on mode)
- `mode`: `"legacy"` or `"six_slot"`
- `hmi_version`: Detected HMI firmware version
- `last_updated`: ISO timestamp of last update
- `schedule_source`: `"octopus_dispatch"`
- `last_api_response`: `"success"`, `"partial_failure"`, etc.
- `operations`: (six-slot only) List of executed operations
- `failed_operations`: (six-slot only) List of failed operations (if any)
- `time_sync`: `"enabled"` or `"disabled"`
- `timezone`: Configured timezone

---

## Obtaining Solis API Credentials

1. Log in to [SolisCloud](https://www.soliscloud.com/)
2. Navigate to **Account** → **API Management**
3. Click **Activate Now**
4. Complete puzzle verification
5. Note your **Key ID** and **Key Secret**
6. **Plant ID** can be found in the SolisCloud plant URL

---

## Troubleshooting

### "No inverters returned from inverterList"

**Cause**: Invalid `plantId` or API credentials

**Solution**:
1. Verify `plantId` matches your SolisCloud plant
2. Check API credentials are correct
3. Ensure API access is enabled for your account

### "Multiple inverters found; set inverter_sn or inverter_id"

**Cause**: Your plant has multiple inverters and auto-selection failed

**Solution**:
1. Check the error log - it lists all available inverters with IDs and SNs
2. Add `inverter_sn` or `inverter_id` to your automation config
3. Example:
   ```
   ERROR Available inverters:
   ERROR   - ID: 123456, SN: ABC123, Name: Solis-5K, ProductModel: 2
   ERROR   - ID: 789012, SN: DEF456, Name: Solis-3K, ProductModel: 1
   ```
4. Add to config: `"inverter_sn": "ABC123"`

### Six-Slot Not Detected / Wrong Mode

**Symptoms**: Script uses legacy mode but you have 6-slot firmware

**Diagnosis**:
1. Run with `"diagnostics_only": true`
2. Check logs for: `"HMI version detected: ..."`
3. Check `sensor.solis_charge_schedule` → `hmi_version` attribute

**Solutions**:

**If HMI version not found:**
```json
"force_mode": "six_slot",
"max_slots": 6
```

**If HMI version detected but < 4B00:**
- Your firmware may not support 6 slots
- Continue using legacy mode
- Or try forcing six-slot if you're certain you have the update

### Time Sync Warnings

**Symptom**: `"Time sync returned code: X"`

**Cause**: Inverter may not support CID 56, or temporary API issue

**Impact**: Schedule programming still works, only time sync affected

**Solution**:
- If persistent, disable time sync: `"sync_inverter_time": false`
- Monitor inverter time manually

### Charging Windows Not Updating

**Check**:
1. Is `planned_dispatches` attribute present on dispatch sensor?
2. Check logs: `"Charging windows unchanged - skipping API update"`
   - This means the schedule hasn't changed (normal behavior)
3. Check `sensor.solis_charge_schedule` attributes for `last_api_response`

### Diagnostics Mode Checklist

Run with `"diagnostics_only": true` and check:

**Logs should show:**
```
INFO Firmware detection complete: HMI=..., six_slot=..., force_mode=..., final_max_slots=...
INFO Calculated X charging windows (core + Y additional)
INFO Total operations to execute: Z
```

**Sensor attributes should show:**
- `mode`: Correct firmware mode
- `operations`: (six-slot) List of planned CID writes
- `charging_windows`: Calculated schedule
- `last_api_response`: `"not_sent_diagnostics_mode"`

---

## Getting Help

When reporting issues, please provide:

1. **Your firmware mode**: Check `sensor.solis_charge_schedule` → `mode` attribute
2. **HMI version**: Check `sensor.solis_charge_schedule` → `hmi_version` attribute
3. **Full logs** from a single run with diagnostics enabled
4. **Your automation config** (redact credentials!)
5. **Inverter model** and **firmware version** from SolisCloud

**Logs location**: Settings → System → Logs → search for "pyscript.solis_smart_charging"

---

## Changelog

### v4.0.0 (December 2025)

**Major Features:**
- ✨ Six-slot firmware support (HMI >= 4B00)
- ✨ Automatic firmware detection via HMI version
- ✨ Force mode override (`legacy` / `six_slot` / `auto`)
- ✨ Diagnostics mode for safe testing

**Improvements:**
- 🔧 Enhanced logging throughout (structured, detailed)
- 🔧 Better error messages for multi-inverter scenarios
- 🔧 Configurable retry/delay parameters
- 🔧 Optional readback verification (six-slot mode)

**v3.2.0 Features Retained:**
- ✅ Automatic inverter time synchronization (CID 56)
- ✅ Timezone support for time sync
- ✅ Enhanced multi-inverter troubleshooting
- ✅ Handles undefined secrets gracefully

**Backward Compatibility:**
- ✅ Existing automations work without changes
- ✅ Legacy 3-slot mode unchanged
- ✅ All v3.2.0 features preserved

### v3.2.0 (December 2025)

- Enhanced multi-inverter troubleshooting with detailed diagnostic logging
- Automatic inverter time synchronization (CID 56)
- Fixed handling of undefined secrets
- Enhanced API response validation

### v3.1.0

- Multi-inverter support
- Fallback position coding
- Enhanced API robustness

### v3.0.x

- Complete rewrite of window handling
- Enhanced midnight crossover logic
- Better logging and reporting

---

## Contributing

Contributions welcome! Please:
- Test thoroughly (especially six-slot mode)
- Provide detailed logs with any issues
- Include your HMI version and inverter model

---

## License

MIT License - See LICENSE file for details

---

## Credits

- Core API logic adapted from [stevegal/solis_control](https://github.com/stevegal/solis_control)
- Six-slot CID mapping from [hultenvp/solis-sensor](https://github.com/hultenvp/solis-sensor)
- Window processing logic: Original development
- Time sync feature: v3.2.0 addition
- Six-slot support: v4.0.0 community contribution

---

## Disclaimer

**This script is provided AS-IS without warranty.**

- Use at your own risk
- Test with `diagnostics_only: true` first
- The six-slot mode has limited testing - please report results
- Incorrect configuration can affect your battery charging behavior
- Always verify inverter schedule after first run

**Not affiliated with Solis, Octopus Energy, or Home Assistant.**
 
