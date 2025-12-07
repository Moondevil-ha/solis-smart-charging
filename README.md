# Solis Smart Charging for Home Assistant

This integration synchronizes Solis inverter charging windows with Octopus Energy Intelligent dispatch periods in Home Assistant. It automatically adjusts your battery charging schedule to maximize the use of cheaper electricity during dispatch periods while maintaining core charging hours.

Code has been utilised from [https://github.com/stevegal/solis_control](https://github.com/stevegal/solis_control) for the API calls to SolisCloud performing the actual programming.

The core window processing logic is identical between both implementations, only the communication method differs.

---

## Features

* Automatically syncs Solis inverter charging windows with Octopus Energy Intelligent dispatch periods
* **NEW: Automatic inverter time synchronization** - prevents charging window drift due to clock inaccuracies
* Maintains protected core charging hours (23:30-05:30)
* Supports up to three charging windows (Solis limitation)
* Smart charging window management:
  * Automatically detects and merges contiguous charging blocks
  * Extends core hours when dispatch periods are adjacent
  * Handles early charging completion appropriately
  * Maintains charging windows during dispatch periods
* Robust time handling:
  * All times normalized to 30-minute slots
  * Smart handling of overnight periods and early morning dispatches
  * Timezone-aware datetime processing
  * Proper management of charging windows across midnight boundary
* **Enhanced Multi-Inverter Support**
  * Optional: `inverter_sn` or `inverter_id` can be provided to explicitly select the correct inverter
  * If omitted, the script will automatically select a hybrid/storage inverter when possible
  * Prevents Solis error B0107 when multiple inverters exist and only one supports charge control
  * **NEW: Detailed diagnostic logging** when inverter selection fails - shows all available inverters with IDs, serial numbers, and models

---

## Prerequisites

* Home Assistant installation
* Solis inverter with battery storage
* Octopus Energy Intelligent tariff
* [Octopus Energy Integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy) installed
* [pyscript integration](https://github.com/custom-components/pyscript) installed

---

## Installation

1. Ensure you have the pyscript integration installed and configured in Home Assistant

2. Add the following to your `configuration.yaml`:

```yaml
pyscript:
  allow_all_imports: true
  hass_is_global: true

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

  # Optional - for multi-inverter support
  solis_inverter_sn:
    name: Solis Inverter Serial (optional)
    initial: !secret solis_inverter_sn
  solis_inverter_id:
    name: Solis Inverter ID (optional)
    initial: !secret solis_inverter_id
```

3. Add your Solis credentials to `secrets.yaml`:

```yaml
solis_api_secret: "your_api_secret"
solis_api_key: "your_api_key"
solis_username: "your_username"
solis_password: "your_password"
solis_plant_id: "your_plant_id"

# Optional - only needed if you have more than one inverter
# You can omit these entirely if you have a single inverter
solis_inverter_sn: "your_hybrid_inverter_sn"
# or
solis_inverter_id: "your_hybrid_inverter_id"
```

4. Copy `solis_smart_charging.py` to your `config/pyscript` directory

5. There are a couple of references in the code to the dispatch entity. Ensure you change this to match your own entities.

6. Add the automation to your `automations.yaml` or through the Home Assistant UI

---

## Configuration

### Automation

```yaml
alias: Sync Solis Charging with Octopus Dispatch
description: ""
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.octopus_energy_a_42185595_intelligent_dispatching
    attribute: planned_dispatches
conditions:
  - condition: template
    value_template: >
      {% set dispatches =
      state_attr('binary_sensor.octopus_energy_a_42185595_intelligent_dispatching',
      'planned_dispatches') %} {% if dispatches is none %}
        {% set result = false %}
      {% else %}
        {% set result = true %}
      {% endif %} {{ result }}
actions:
  - action: pyscript.solis_smart_charging
    metadata: {}
    data:
      config: |-
        {
          "secret": "{{ states('input_text.solis_api_secret') }}",
          "key_id": "{{ states('input_text.solis_api_key') }}",
          "username": "{{ states('input_text.solis_username') }}",
          "password": "{{ states('input_text.solis_password') }}",
          "plantId": "{{ states('input_text.solis_plant_id') }}",
          "dispatch_sensor": "binary_sensor.octopus_energy_a_42185595_intelligent_dispatching",

          "inverter_sn": "{{ states('input_text.solis_inverter_sn') }}",
          "inverter_id": "{{ states('input_text.solis_inverter_id') }}"
        }
mode: single
```

**Note:** The dispatching sensor will usually include your account ID, please check and edit the automation appropriately for the correct entity.

### Optional Configuration Parameters

You can add these optional parameters to your automation config:

```yaml
data:
  config: |-
    {
      "secret": "{{ states('input_text.solis_api_secret') }}",
      ...
      "sync_inverter_time": true,  # Default: true - syncs inverter clock on every run
      "inverter_sn": "{{ states('input_text.solis_inverter_sn') }}",
      "inverter_id": "{{ states('input_text.solis_inverter_id') }}"
    }
```

**sync_inverter_time**: (Default: `true`) - Automatically synchronizes your inverter's internal clock with Home Assistant's NTP-synced time before updating charging windows. This prevents time drift that can cause charging windows to start/stop at incorrect times. Set to `false` only if you want to manage inverter time manually.

---

## Automatic Time Synchronization

**New in v3.2.0** - The script now automatically keeps your inverter's clock synchronized with accurate time.

### Why This Matters

Inverter internal clocks can drift over time, causing:
* Charging windows starting late or early
* Missing cheap rate periods
* Charging during expensive periods
* Incorrect window end times

### How It Works

1. On every script run, **before** updating charging windows, the current UTC time from Home Assistant is sent to the inverter
2. Uses the Solis API control endpoint (CID 56) for NTP-based time sync
3. The inverter clock is updated to match Home Assistant's time (which should be NTP-synced)
4. Enabled by default, runs automatically with no user intervention needed

### Log Output

When time sync succeeds, you'll see:
```
INFO Successfully synced inverter time to 2025-12-07 10:36:40 UTC
```

### Disabling Time Sync

While not recommended, you can disable automatic time sync:

```yaml
data:
  config: |-
    {
      ...
      "sync_inverter_time": false
    }
```

---

## Multi-Inverter Support

If your Solis plant contains multiple inverters (e.g., PV inverter + hybrid inverter), SolisCloud may return them in an unpredictable order.

Only hybrid/storage inverters can accept charge-schedule programming — the others will return:

```
B0107 – The datalogger model does not support this function
```

### Configuration Options

You can avoid this by explicitly specifying:
* `inverter_sn` or
* `inverter_id`

If neither is provided:
* The script will attempt to auto-select a hybrid/storage inverter (ProductModel == 2)
* If exactly one suitable inverter exists, it will be used
* If none or multiple matches exist, the script will stop safely and log an error

### Troubleshooting Multi-Inverter Issues

**New in v3.2.0** - Enhanced diagnostic logging helps identify inverter selection problems.

If you're getting B0107 errors:

1. **Check your logs** after the script runs - you'll now see detailed information about all available inverters:

```
ERROR Available inverters:
ERROR   - ID: 1308675217947185060, SN: 6031050221230050, Name: Solis-5K-Hybrid, ProductModel: 3105
ERROR   - ID: 1234567890123456789, SN: 5031050221230099, Name: Solis-3K-PV, ProductModel: 1
```

2. **Identify your hybrid/storage inverter** - look for:
   - ProductModel: 2, 3105, or similar storage inverter models
   - The inverter connected to your battery

3. **Copy the Serial Number** from the logs

4. **Add it to your secrets.yaml**:
```yaml
solis_inverter_sn: "6031050221230050"  # Your actual SN from the logs
```

5. **Reload the automation** - the B0107 error should resolve

### Handling Undefined Secrets

**New in v3.2.0** - The script now correctly handles undefined secrets.

If you don't define `solis_inverter_sn` or `solis_inverter_id` in your secrets, Home Assistant may return:
- `"unknown"`
- `"unavailable"`
- `"none"`

The script now treats these as empty strings and falls through to auto-selection. You **no longer need** to define these secrets if you want auto-selection to work.

---

## How It Works

1. The script monitors Octopus Energy Intelligent dispatch periods

2. When dispatch periods are updated:
   * **Inverter time is synchronized** to ensure accurate charging window timing (v3.2.0)
   * Core charging hours (23:30-05:30) are protected and cannot be reduced
   * Early morning dispatches (00:00-12:00) are processed against previous day's core window
   * The script identifies contiguous charging blocks and merges them
   * Core hours are extended if dispatch periods are adjacent
   * Additional charging windows are selected based on available charge amount
   * All times are normalized to 30-minute slots

3. During charging:
   * Dispatch windows may remain but with adjusted kWh values
   * Binary sensor state indicates valid charging periods
   * Windows automatically adjust based on actual charging needs

4. The resulting charging windows are synchronized to your Solis inverter

5. The process repeats when new dispatch periods are received

---

## Known Behaviors

**Dispatch Windows:**
* Windows may remain after charging completion -- to be addressed.
* System maintains window integrity during overnight transitions

**Window Processing:**
* Early morning dispatches (before 12:00) align with previous day's core window
* Windows are always normalized to 30-minute boundaries
* Core window can extend but never shrink

**Local sensors:**
* Local entities are created (if they do not exist) or updated to reflect the calculated charging windows.
* The newly calculated windows are checked against the local ones, and the API is only called if there is a change.

---

## Obtaining Solis API Credentials

1. Log in to your [Solis Cloud account](https://www.soliscloud.com/)
2. Navigate to Account Management
3. Under API Management, create new API credentials
4. Note down your API Key ID and Secret
5. Your Plant ID can be found in the URL when viewing your plant details

---

## Example Dashboard View

<img width="1369" height="379" alt="image" src="https://github.com/user-attachments/assets/444447ed-7162-405c-8103-5b49cd1f69af" />


```yaml
title: Octopus Intelligent
panel: false
icon: mdi:lightning-bolt-circle
badges: []
cards: []
type: sections
sections:
  - type: grid
    cards:
      - type: custom:mushroom-template-card
        primary: Octopus Energy Dispatches
        secondary: >
          {% set dispatches =
          state_attr('binary_sensor.octopus_energy_a_42185595_intelligent_dispatching',
          'planned_dispatches') %}

          {% if dispatches | length > 0 %}
            {%- for dispatch in dispatches %}
              {{- (dispatch.start | as_local).strftime('%H:%M') }} - {{ (dispatch.end | as_local).strftime('%H:%M') }}
              {%- if not loop.last %}
          {{ '\n' }}      {%- endif %}
            {%- endfor %}
          {% else %}
            No dispatches scheduled
          {% endif %}
        icon: mdi:clock-outline
        icon_color: >-
          {% if
          is_state('binary_sensor.octopus_energy_a_42185595_intelligent_dispatching',
          'on') %}
            green
          {% else %}
            grey
          {% endif %}
        tap_action:
          action: more-info
          entity: binary_sensor.octopus_energy_a_42185595_intelligent_dispatching
        layout: vertical
        multiline_secondary: true
        card_mod:
          style: |
            ha-card {
              --ha-card-background: var(--card-background-color);
              --primary-text-color: var(--primary-color);
            }
        chip:
          type: entity
          entity: binary_sensor.octopus_energy_a_42185595_intelligent_dispatching
          icon: mdi:power
          content: >
            {{ 'Active' if
            is_state('binary_sensor.octopus_energy_a_42185595_intelligent_dispatching',
            'on') else 'Inactive' }}
      - type: custom:mushroom-template-card
        primary: Solis Charging Schedule
        secondary: >
          {% set windows = state_attr('sensor.solis_charge_schedule',
          'charging_windows') %} {% if windows | length > 0 %}
            {%- for window in windows %}
              {%- if window.chargeStartTime != "00:00" or window.chargeEndTime != "00:00" %}
                {{- window.chargeStartTime }} - {{ window.chargeEndTime }}
                {%- if not loop.last %}
          {{ '\n' }}        {%- endif %}
              {%- endif %}
            {%- endfor %}
          {% else %}
            No charging windows scheduled
          {% endif %}
        icon: mdi:battery-charging-outline
        icon_color: >-
          {% set windows = state_attr('sensor.solis_charge_schedule',
          'charging_windows') %} {% if windows | length > 0 %}
            green
          {% else %}
            grey
          {% endif %}
        tap_action:
          action: more-info
          entity: sensor.solis_charge_schedule
        layout: vertical
        multiline_secondary: true
        card_mod:
          style: |
            ha-card {
              --ha-card-background: var(--card-background-color);
              --primary-text-color: var(--primary-color);
            }
        chip:
          type: entity
          entity: sensor.solis_charge_schedule
          icon: mdi:battery-clock
          content: >
            {{ 'Updated: ' + state_attr('sensor.solis_charge_schedule',
            'last_updated') | as_datetime | as_local | as_timestamp |
            timestamp_custom('%H:%M') }}
      - type: vertical-stack
        cards:
          - type: custom:mushroom-number-card
            entity: number.octopus_energy_a_42185595_intelligent_charge_target
            icon: mdi:battery-charging
            name: EV Charge Target
            display_mode: buttons
            fill_container: true
            layout: vertical
            card_mod:
              style: |
                ha-card {
                  --ha-card-background: var(--card-background-color);
                  --primary-text-color: var(--primary-color);
                }
          - type: custom:mushroom-entity-card
            entity: time.octopus_energy_a_42185595_intelligent_target_time
            icon: mdi:clock-outline
            name: Target Charge Time
            tap_action:
              action: more-info
            layout: vertical
            primary_info: name
            secondary_info: state
            card_mod:
              style: |
                ha-card {
                  --ha-card-background: var(--card-background-color);
                  --primary-text-color: var(--primary-color);
                }
    column_span: 2
```

---

## Version History

### v3.2.0 (December 2025)

* **NEW: Automatic inverter time synchronization** - prevents charging window drift
* Enhanced multi-inverter troubleshooting with detailed diagnostic logging
* Fixed handling of undefined secrets (now treats "unknown"/"unavailable" as empty)
* Enhanced API response validation with better error messages
* Logs all available inverters when selection fails
* Confirms selected inverter in logs after successful selection

### v3.1.0

* Multi-inverter support
* Fallback position coding
* Enhanced API robustness

### v3.0x

* Complete rewrite of window handling
* Enhanced logic around midnight window crossover
* Better logging and reporting
* Added multi-inverter support and explicit inverter selection

### v2.0x

* Enhanced overnight charging behavior
* Improved early morning dispatch processing
* Better handling of timezone-aware operations
* More robust window merging logic

### v1.0x

* Initial release

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.
