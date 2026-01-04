# Testing Guide for Six-Slot Firmware

**Important**: This script has NOT been tested with six-slot firmware. You are the first tester!

This guide will help you safely test the six-slot functionality and provide feedback.

---

## Before You Start

### What You'll Need
- Home Assistant with logs access
- Access to SolisCloud web interface
- Your inverter's HMI version (check SolisCloud)
- Ability to manually revert inverter settings if needed
- About 30 minutes for testing

### Safety First
1. **Understand the risks**: Incorrect charging schedules could affect your battery
2. **Know how to manually set charging times** in SolisCloud or on the inverter
3. **Take screenshots** of your current charging schedule before starting
4. **Have backup plan**: Know how to revert to manual control

---

## Testing Phases

We'll do this in 3 phases:
1. **Diagnostics** - Verify detection without writing to inverter
2. **Single Write** - Test one update with verification
3. **Full Operation** - Enable normal automated operation

---

## Phase 1: Diagnostics Mode (SAFE - NO WRITES)

### Step 1: Update Script

1. Replace your existing `solis_smart_charging.py` with v4.0.0
2. Location: `/config/pyscript/solis_smart_charging.py`
3. **Reload PyScript**: Developer Tools → YAML → Reload PyScript

### Step 2: Add Diagnostics Flag

Modify your automation to add `"diagnostics_only": true`:

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
          "dispatch_sensor": "binary_sensor.octopus_energy_xxx_intelligent_dispatching",
          "diagnostics_only": true
        }
```

### Step 3: Trigger the Automation

Manually trigger the automation once.

### Step 4: Check Logs

Go to: Settings → System → Logs → Search for "solis_smart_charging"

**Look for these key lines:**

```
INFO === Solis Smart Charging v4.0.0 ===
INFO Configuration: diagnostics_only=True, force_mode=auto, max_slots=...
INFO Login successful, token obtained
INFO Found X inverter(s) in plant
INFO Using inverter - ID: ..., SN: ..., Name: ..., ProductModel: ...
```

**Then look for firmware detection:**

```
INFO Auto-detecting firmware mode via HMI version...
INFO HMI version detected: XXXX (decimal: YYYY, six_slot: True/False)
INFO Firmware detection complete: HMI=XXXX, six_slot=True/False, force_mode=auto, final_max_slots=X
```

**Then look for time sync:**

```
INFO Syncing inverter time (CID 56)...
INFO Successfully synced inverter time to 2025-12-07 10:36:40 (UTC)
```

**Finally, look for the operations plan:**

```
INFO === Six-Slot Mode: Building CID operations ===
INFO Total operations to execute: X
INFO   Operation: charge_time slot_1 CID=5946 value='23:30-05:30'
INFO   Operation: charge_time slot_2 CID=5949 value='13:00-14:00'
...
WARNING === DIAGNOSTICS MODE: Not writing to inverter ===
```

### Step 5: Check Sensor

Go to: Developer Tools → States → Find `sensor.solis_charge_schedule`

**Check the attributes:**
- `mode`: Should say `"six_slot"` or `"legacy"`
- `hmi_version`: Your HMI version
- `operations`: List of planned CID writes (six-slot only)
- `charging_windows`: Calculated schedule
- `last_api_response`: Should say `"not_sent_diagnostics_mode"`

### Phase 1 Checklist

- [ ] HMI version detected correctly?
- [ ] Six-slot mode detected? (check `mode` attribute)
- [ ] Time sync successful?
- [ ] Operations list looks reasonable?
- [ ] Charging windows make sense?
- [ ] No errors in logs?

**If ANY of the above failed, STOP and report the issue before proceeding!**

---

## Phase 2: Single Write Test (WILL WRITE TO INVERTER)

**⚠️ WARNING: This will modify your inverter settings!**

### Step 1: Take Screenshots

Before proceeding:
1. Log into SolisCloud
2. View your current charging schedule
3. **Take screenshots** for comparison

### Step 2: Remove Diagnostics Flag

Remove the `"diagnostics_only": true` line from your automation:

```yaml
{
  "secret": "{{ states('input_text.solis_api_secret') }}",
  "key_id": "{{ states('input_text.solis_api_key') }}",
  "username": "{{ states('input_text.solis_username') }}",
  "password": "{{ states('input_text.solis_password') }}",
  "plantId": "{{ states('input_text.solis_plant_id') }}",
  "dispatch_sensor": "binary_sensor.octopus_energy_xxx_intelligent_dispatching"
}
```

### Step 3: Trigger ONCE

Manually trigger the automation **once**.

### Step 4: Watch the Logs

**Look for execution messages:**

```
INFO === Executing six-slot control writes ===
INFO Writing: charge_time slot_1 CID=5946 value='23:30-05:30'
INFO SUCCESS: charge_time slot_1 CID=5946
INFO Writing: charge_time slot_2 CID=5949 value='13:00-14:00'
INFO SUCCESS: charge_time slot_2 CID=5949
...
INFO === Six-slot update completed successfully ===
```

**Or if there were failures:**

```
ERROR FAILED: charge_time slot_X CID=XXXX
ERROR === Six-slot update completed with X failures ===
```

### Step 5: Verify in SolisCloud

1. **Wait 2-3 minutes** for changes to propagate
2. Log into SolisCloud
3. View your charging schedule
4. **Compare with the calculated windows** from Phase 1

**Questions to answer:**
- Do the times match what the script calculated?
- Are all 6 slots visible (or appropriate number)?
- Do the times look correct?

### Step 6: Check Sensor Again

Check `sensor.solis_charge_schedule` attributes:
- `last_api_response`: Should be `"success"` or `"partial_failure"`
- `failed_operations`: Should be empty (or list failed ops)

### Phase 2 Checklist

- [ ] All CID writes successful?
- [ ] Times visible in SolisCloud?
- [ ] Times match calculated schedule?
- [ ] No unexpected behavior?
- [ ] Inverter still responding normally?

**If anything failed or looks wrong:**
1. Manually revert charging schedule in SolisCloud
2. Disable automation
3. Report the issue with full logs

---

## Phase 3: Full Operation (AUTOMATED)

**Only proceed if Phase 2 was 100% successful!**

### Step 1: Leave Automation Enabled

Your automation is now ready for normal operation. It will:
- Trigger when Octopus dispatches update
- Auto-detect firmware mode
- Sync inverter time
- Program charging windows
- Only update when schedule changes

### Step 2: Monitor First Few Runs

For the first 24-48 hours:
1. **Check logs after each trigger** (when dispatches update)
2. **Verify schedule in SolisCloud** matches expectations
3. **Observe actual charging behavior**

### Step 3: Long-Term Monitoring

After a few successful runs:
- Check weekly that charging occurs as expected
- Verify time sync is working (times stay accurate)
- Monitor for any API errors in logs

---

## What to Report Back

### Success Report

If everything works:

```markdown
## Six-Slot Testing - SUCCESS ✅

**Environment:**
- Inverter Model: [e.g., S5-EH1P6K-L]
- HMI Version: [from logs, e.g., 4b05]
- Firmware: [if known]
- Home Assistant Version: [e.g., 2024.12.1]

**Testing Results:**
- ✅ Diagnostics mode: Detected six-slot correctly
- ✅ Single write: All CID writes successful
- ✅ SolisCloud verification: Times match perfectly
- ✅ 48hr monitoring: No issues observed
- ✅ Time sync: Working correctly

**Observations:**
[Any notes, e.g., "Took 2 minutes for changes to appear in SolisCloud"]

**Logs:**
[Attach full log from one successful run]
```

### Failure Report

If anything fails:

```markdown
## Six-Slot Testing - ISSUE ⚠️

**Environment:**
- Inverter Model: 
- HMI Version: 
- Firmware: 
- Home Assistant Version: 

**Phase Failed:** [Diagnostics / Single Write / Full Operation]

**Issue Description:**
[Detailed description of what went wrong]

**Expected:**
[What you expected to happen]

**Actual:**
[What actually happened]

**Logs:**
[Full logs from the failed run]

**Screenshots:**
[SolisCloud screenshots showing the issue]

**Sensor State:**
[Copy/paste sensor.solis_charge_schedule attributes]
```

---

## Emergency Revert Procedure

If something goes seriously wrong:

### Immediate Steps

1. **Disable the automation** in Home Assistant
2. **Log into SolisCloud**
3. **Manually set your normal charging schedule**
4. **Verify** the inverter is charging as expected

### Script Revert

If you need to go back to v3.2.0:

1. Replace script with previous version
2. Reload PyScript
3. Remove any v4.0.0 configuration parameters
4. Trigger automation once to restore v3.2.0 schedule

---

## Common Issues & Solutions

### "HMI version not found"

**Cause**: API didn't return HMI version

**Solution**: 
```yaml
"force_mode": "six_slot",
"max_slots": 6
```

### Time Sync Failures

**Symptom**: `"Time sync returned code: X"`

**Impact**: Not critical, schedule programming continues

**Solution**: Monitor; if persistent, disable with `"sync_inverter_time": false`

### "Multiple inverters found"

**Cause**: Plant has multiple inverters

**Solution**: Add `"inverter_sn": "YOUR_SN"` to config

### CID Write Failures

**Symptom**: Some CID writes fail in logs

**Check**: 
1. Are the failed CIDs consistent?
2. Do successful writes still appear in SolisCloud?
3. Is the inverter responding?

**Report**: Full logs with all failed CID numbers

---

## Questions to Answer During Testing

### Firmware Detection
- [ ] What HMI version was detected?
- [ ] Did six-slot mode auto-detect correctly?
- [ ] If you forced six-slot, did it work?

### Time Sync
- [ ] Did time sync execute successfully?
- [ ] What timezone did you use?
- [ ] Did inverter time stay accurate over 48 hours?

### CID Writes
- [ ] How many CID writes were executed?
- [ ] Were all successful on first attempt?
- [ ] If retries occurred, how many?

### SolisCloud Behavior
- [ ] How long until changes appeared in SolisCloud?
- [ ] Do all 6 slots show in the interface?
- [ ] Can you edit slots manually after script writes?

### Actual Charging
- [ ] Did charging occur at programmed times?
- [ ] Were the times accurate (within 1-2 minutes)?
- [ ] Any unexpected charging outside windows?

---

## Thank You!

Your testing is invaluable since the author doesn't have six-slot firmware to test with.

**Please provide detailed feedback even if everything works perfectly!**

Knowing what works is just as important as knowing what doesn't.

---

## Contact

Report results via:
- GitHub Issues (preferred)
- Home Assistant Community Forum
- Direct message to script author

**Include**:
- Success/Failure status
- Full logs from at least one run
- SolisCloud screenshots
- Sensor attributes
- Your environment details
