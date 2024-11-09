# Solis Smart Charging for Home Assistant

***NOTE Major change in processing being evaluated. Release pending***

This integration synchronizes Solis inverter charging windows with Octopus Energy Intelligent dispatch periods in Home Assistant. It automatically adjusts your battery charging schedule to maximize the use of cheaper electricity during dispatch periods while maintaining core charging hours.

Code has been utilised from https://github.com/stevegal/solis_control for the API calls to SolisCloud performing the actual programming.

## Features

- Automatically syncs Solis inverter charging windows with Octopus Energy Intelligent dispatch periods
- Maintains core charging hours (default 23:30-05:30)
- Supports up to three charging windows (Solis limitation)
- Prioritizes dispatch periods by charging volume
- Extends core charging window when dispatch periods are contiguous
- Handles time rounding to meet Solis 30-minute interval requirements

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

## How It Works

1. The script monitors Octopus Energy Intelligent dispatch periods
2. When dispatch periods are updated:
   - Core charging hours (23:30-05:30) are maintained
   - Additional dispatch periods are prioritized by charging volume
   - Up to two additional charging windows are created
   - If dispatch periods are contiguous with core hours, the core window is extended
3. Charging windows are synchronized to your Solis inverter
4. The process repeats when dispatch periods change

## Obtaining Solis API Credentials

1. Log in to your [Solis Cloud account](https://www.soliscloud.com/)
2. Navigate to Account Management
3. Under API Management, create new API credentials
4. Note down your API Key ID and Secret
5. Your Plant ID can be found in the URL when viewing your plant details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
