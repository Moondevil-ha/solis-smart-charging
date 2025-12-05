# Solis Smart Charging for Home Assistant

This integration synchronizes Solis inverter charging windows with Octopus Energy Intelligent dispatch periods in Home Assistant. It automatically adjusts your battery charging schedule to maximize the use of cheaper electricity during dispatch periods while maintaining core charging hours.

Code has been utilised from [https://github.com/stevegal/solis_control](https://github.com/stevegal/solis_control) for the API calls to SolisCloud performing the actual programming.

The core window processing logic is identical between both implementations—only the communication method differs.

---

## Features

* Automatically syncs Solis inverter charging windows with Octopus Energy Intelligent dispatch periods
* Maintains protected core charging hours (23:30–05:30)
* Supports up to three charging windows (Solis limitation)
* Smart charging window management:
  * Automatically detects and merges contiguous charging blocks
  * Extends core hours when dispatch periods are adjacent
  * Handles early charging completion appropriately
  * Maintains charging windows during dispatch periods
* Robust time handling:
  * All times normalized to 30-minute slots
  * Timezone-aware
  * Handles midnight crossover
* **Multi-inverter support (new):**
  * Explicit inverter selection by `inverter_sn` or `inverter_id`
  * Automatic detection of hybrid/storage inverters (`productModel == 2`)
  * Safety fallbacks to avoid sending control commands to the wrong datalogger

---

## Prerequisites

* Home Assistant installation
* Solis inverter with battery storage
* Octopus Energy Intelligent tariff
* [Octopus Energy Integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy)
* [pyscript integration](https://github.com/custom-components/pyscript)

---

## Installation

1. Ensure you have the pyscript integration installed and configured in Home Assistant.
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

# Optional but recommended if you have more than one inverter
solis_inverter_sn: "your_hybrid_inverter_sn"
# or:
solis_inverter_id: "your_hybrid_inverter_id"
```

4. Copy `solis_smart_charging.py` to your `config/pyscript` directory.
5. Update the dispatch entity references in the script/automation to match your own.
6. Add the automation either via YAML or using the Home Assistant Automation UI.

---

## Configuration

### Automation Example

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
      {% set d = state_attr('binary_sensor.octopus_energy_a_42185595_intelligent_dispatching', 'planned_dispatches') %}
      {{ d is not none }}
actions:
  - action: pyscript.solis_smart_charging
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

**Note:**
The dispatch entity will differ for each user. Ensure you update it correctly.

---

## Multi-Inverter Support (New)

If your Solis plant contains more than one inverter, SolisCloud may return them in an unpredictable order. Some models (string-only inverters, older dataloggers) **cannot** accept remote charge-slot programming and will return:

```
B0107 – The datalogger model does not support this function
```

To guarantee correct behaviour:

### Option 1 — Explicitly set your hybrid inverter (recommended)

```yaml
inverter_sn: "your_hybrid_inverter_sn"
```

or

```yaml
inverter_id: "your_hybrid_inverter_id"
```

### Option 2 — Automatic detection

If neither parameter is set:

* The script auto-detects a **hybrid/storage inverter** via `productModel == 2`
* If exactly one match exists, it's used
* If 0 or >1 matches exist, the script logs a clear error and **stops safely**

This ensures the script **never writes to the wrong datalogger**.

---

## How It Works

1. The script listens for updated Octopus Intelligent dispatch periods.
2. When dispatch updates occur:
   * Core charging hours (23:30–05:30) are protected
   * Early morning dispatches are anchored to the previous day
   * Contiguous dispatch blocks are merged
   * Core hours extend when required
   * Additional windows are selected as needed
   * All times are normalised to 30-minute slots
3. The script determines the correct inverter (explicit or automatic).
4. The generated charging windows are pushed to your Solis inverter.
5. A local sensor (`sensor.solis_charge_schedule`) reflects the schedule.

---

## Known Behaviours

* Dispatch windows may remain after early charging completion (future improvement planned)
* Core window always extends when needed but never shrinks
* Local sensor is updated only when a schedule change occurs
* Times always normalised to 30-minute Solis-compatible slots

---

## Obtaining Solis API Credentials

1. Log in to your [SolisCloud account](https://www.soliscloud.com/)
2. Go to **Account Management → API Management**
3. Create new credentials
4. Record your API Key ID and Secret
5. Your Plant ID is visible in your plant's URL

---

## Version History

### v3.1.0

* Added MultiInverter Logic
* Safety Fallbacks
* More robust API Communication

### v3.0x

* Complete rewrite of window handling
* Enhanced logic for midnight crossover
* Better logging and reporting
* **New: Multi-inverter support & explicit inverter selection**

### v2.0x

* Improved early morning processing
* Better timezone handling
* Window merging improvements

### v1.0x

* Initial release

---

## Contributing

Pull requests are welcome!

---

## License

MIT License.
