# Solis Smart Charging for Home Assistant

This integration synchronizes Solis inverter charging windows with Octopus Energy Intelligent dispatch periods in Home Assistant. It automatically adjusts your battery charging schedule to maximize the use of cheaper electricity during dispatch periods while maintaining core charging hours.

Code has been utilised from https://github.com/stevegal/solis_control for the API calls to SolisCloud performing the actual programming.

## Features

- Automatically syncs Solis inverter charging windows with Octopus Energy Intelligent dispatch periods
- Maintains protected core charging hours (23:30-05:30)
- Supports up to three charging windows (Solis limitation)
- Smart charging window management:
  - Automatically detects and merges contiguous charging blocks
  - Extends core hours when dispatch periods are adjacent
  - Handles early charging completion appropriately
  - Maintains charging windows during dispatch periods
- Robust time handling:
  - All times normalized to 30-minute slots
  - Smart handling of overnight periods and early morning dispatches
  - Timezone-aware datetime processing
  - Proper management of charging windows across midnight boundary

## Prerequisites

- Home Assistant installation
- Solis inverter with battery storage
- Octopus Energy Intelligent tariff
- [Octopus Energy Integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy) installed
- [pyscript integration](https://github.com/custom-components/pyscript) installed

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
```

3. Add your Solis credentials to `secrets.yaml`:

```yaml
solis_api_secret: "your_api_secret"
solis_api_key: "your_api_key"
solis_username: "your_username"
solis_password: "your_password"
solis_plant_id: "your_plant_id"
```

4. Copy `solis_smart_charging.py` to your `config/pyscript` directory
5. Add the automation to your `automations.yaml` or through the Home Assistant UI

## Configuration

### Automation

```yaml
alias: Sync Solis Charging with Octopus Dispatch
description: ""
trigger:
  - platform: state
    entity_id:
      - binary_sensor.octopus_energy_intelligent_dispatching
    attribute: planned_dispatches
condition:
  - condition: template
    value_template: >
      {% set dispatches =
      state_attr('binary_sensor.octopus_energy_intelligent_dispatching',
      'planned_dispatches') %} {% if dispatches is none %}
        {% set result = false %}
      {% else %}
        {% set result = true %}
      {% endif %} {{ result }}
action:
  - service: pyscript.solis_smart_charging
    metadata: {}
    data:
      config: |-
        {
          "secret": "{{ states('input_text.solis_api_secret') }}",
          "key_id": "{{ states('input_text.solis_api_key') }}",
          "username": "{{ states('input_text.solis_username') }}",
          "password": "{{ states('input_text.solis_password') }}",
          "plantId": "{{ states('input_text.solis_plant_id') }}"
        }
mode: single
```
Note: The dispatching sensor will usually include your account ID, please check and edit the automation appropriately for the correct entity.

## How It Works

1. The script monitors Octopus Energy Intelligent dispatch periods
2. When dispatch periods are updated:
   - Core charging hours (23:30-05:30) are protected and cannot be reduced
   - Early morning dispatches (00:00-12:00) are processed against previous day's core window
   - The script identifies contiguous charging blocks and merges them
   - Core hours are extended if dispatch periods are adjacent
   - Additional charging windows are selected based on available charge amount
   - All times are normalized to 30-minute slots
3. During charging:
   - Dispatch windows may remain but with adjusted kWh values
   - Binary sensor state indicates valid charging periods
   - Windows automatically adjust based on actual charging needs
4. The resulting charging windows are synchronized to your Solis inverter
5. The process repeats when new dispatch periods are received

## Known Behaviors

1. Dispatch Windows:
   - Windows may remain after charging completion -- to be addressed.
   - System maintains window integrity during overnight transitions

2. Window Processing:
   - Early morning dispatches (before 12:00) align with previous day's core window
   - Windows are always normalized to 30-minute boundaries
   - Core window can extend but never shrink

## Obtaining Solis API Credentials

1. Log in to your [Solis Cloud account](https://www.soliscloud.com/)
2. Navigate to Account Management
3. Under API Management, create new API credentials
4. Note down your API Key ID and Secret
5. Your Plant ID can be found in the URL when viewing your plant details

## Version History

### v3.0x
- Complete rewrite of window handling
- Enhanced logic around midnight window crossover
- Better logging and reporting

### v2.0x
- Enhanced overnight charging behavior
- Improved early morning dispatch processing
- Better handling of timezone-aware operations
- More robust window merging logic

### v1.0x
- Initial release

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
