import json
from datetime import datetime, timedelta, timezone
import logging
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import hashlib 
import hmac
import base64
import re
from http import HTTPStatus

log = logging.getLogger("pyscript.solis_smart_charging")

# Constants
VERB = "POST"
LOGIN_URL = '/v2/api/login'
CONTROL_URL= '/v2/api/control'
INVERTER_URL= '/v1/api/inverterList'

# Helper functions
def digest(body: str) -> str:
    return base64.b64encode(hashlib.md5(body.encode('utf-8')).digest()).decode('utf-8')

def passwordEncode(password: str) -> str:
    md5Result = hashlib.md5(password.encode('utf-8')).hexdigest()
    return md5Result

def prepare_header(config: dict[str,str], body: str, canonicalized_resource: str) -> dict[str, str]:
    content_md5 = digest(body)
    content_type = "application/json"
    
    now = datetime.now(timezone.utc)
    date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    encrypt_str = (VERB + "\n" + content_md5 + "\n" + content_type + "\n" + date + "\n" + canonicalized_resource)
    hmac_obj = hmac.new(
        config["secret"].encode('utf-8'),
        msg=encrypt_str.encode('utf-8'),
        digestmod=hashlib.sha1
    )
    sign = base64.b64encode(hmac_obj.digest())
    authorization = "API " + str(config["key_id"]) + ":" + sign.decode('utf-8')
    
    header = {
        "Content-MD5": content_md5,
        "Content-Type": content_type,
        "Date": date,
        "Authorization": authorization
    }
    return header

def control_body(inverterId, chargeSettings) -> str:
    body = '{"inverterId":"'+str(inverterId)+'", "cid":"103","value":"'
    for index, time in enumerate(chargeSettings):
        body = body + str(time['chargeCurrent'])+","+str(time['dischargeCurrent'])+","+str(time['chargeStartTime'])+","+str(time['chargeEndTime'])+","+str(time['dischargeStartTime'])+","+str(time['dischargeEndTime'])
        if (index != 2):
            body = body+","
    return body+'"}'

def is_contiguous_with_core_hours(block_start, block_end, core_window=None):
    """
    Check if a time block is contiguous with core hours.
    Returns (bool, position) where position is 'before', 'after', or None.
    """
    if core_window is None:
        core_start_time = "23:30"
        core_end_time = "05:30"
    else:
        core_start_time = core_window["chargeStartTime"]
        core_end_time = core_window["chargeEndTime"]
    
    core_start_hour, core_start_minute = map(int, core_start_time.split(":"))
    core_end_hour, core_end_minute = map(int, core_end_time.split(":"))
    
    # Normalize all times to remove seconds and microseconds
    block_start = block_start.replace(second=0, microsecond=0)
    block_end = block_end.replace(second=0, microsecond=0)
    
    core_start = block_start.replace(hour=core_start_hour, minute=core_start_minute, 
                                    second=0, microsecond=0)
    if core_start > block_start:
        core_start -= timedelta(days=1)
        
    core_end = block_start.replace(hour=core_end_hour, minute=core_end_minute, 
                                    second=0, microsecond=0)
    if core_start > core_end:
        core_end += timedelta(days=1)
    
    # Block ends at or within 30 minutes before core start
    if (block_end >= core_start - timedelta(minutes=30) and 
        block_end <= core_start + timedelta(minutes=1)):
        return True, 'before'
    
    # Block starts within 29 minutes after core end (making it part of the same 30-min slot)
    # We use 29 minutes because a window starting at exactly 30 minutes after
    # should be treated as a new window to align with electricity pricing slots
    if (block_start >= core_end and 
        block_start < core_end + timedelta(minutes=29)):
        return True, 'after'
    
    # If the block overlaps core hours, consider it part of core hours
    if overlaps_core_hours(block_start, block_end, core_window):
        if block_start < core_start:
            return True, 'before'
        elif block_end > core_end:
            return True, 'after'
    
    return False, None


def overlaps_core_hours(check_start, check_end, core_window=None):
    """
    Check if a time period overlaps with core hours, considering dynamic core hours.
    """
    if core_window is None:
        core_start_time = "23:30"
        core_end_time = "05:30"
    else:
        core_start_time = core_window["chargeStartTime"]
        core_end_time = core_window["chargeEndTime"]
    
    core_start_hour, core_start_minute = map(int, core_start_time.split(":"))
    core_end_hour, core_end_minute = map(int, core_end_time.split(":"))
    
    core_start = check_start.replace(hour=core_start_hour, minute=core_start_minute, 
                                    second=0, microsecond=0)
#    if core_start > check_start:
#        core_start -= timedelta(days=1)
        
    core_end = check_start.replace(hour=core_end_hour, minute=core_end_minute, 
                                    second=0, microsecond=0)
    if core_start > core_end:
        core_end += timedelta(days=1)
    
    return (check_start <= core_end and check_end >= core_start)
        
    # Now check for overlap
    return (
        (core_start <= check_start < core_end) or  # Start falls in core hours
        (core_start < check_end <= core_end) or    # End falls in core hours
        (check_start <= core_start and 
        check_end >= core_end)  # Surrounds core hours
    )

def find_contiguous_blocks(dispatches):
    """Find contiguous charging blocks from dispatch windows."""
    if not dispatches:
        return []
    
    result_blocks = []
    sorted_dispatches = sorted(dispatches, key=lambda x: x['start'])
    
    # Initialize reference core window
    reference_core_window = {
        "chargeStartTime": "23:30",
        "chargeEndTime": "05:30"
    }
    
    # First pass - identify all contiguous blocks
    for dispatch in sorted_dispatches:
        charge = abs(float(dispatch.get('charge_in_kwh', 0)))
        if charge <= 0:
            continue
            
        block = {
            'start': dispatch['start'],
            'end': dispatch['end'],
            'total_charge': charge
        }
        
        # Check against reference core window
        is_contiguous, position = is_contiguous_with_core_hours(
            block['start'], 
            block['end'], 
            reference_core_window
        )
        
        if is_contiguous:
            block['contiguous_position'] = position
            result_blocks.append(block)
    
    # Calculate final core window
    final_core_window = reference_core_window.copy()
    earliest_start = final_core_window["chargeStartTime"]
    latest_end = final_core_window["chargeEndTime"]
    
    for block in result_blocks:
        if 'contiguous_position' in block:
            if block['contiguous_position'] == 'before':
                new_start = round_to_half_hour(block['start']).strftime("%H:%M")
                if time_earlier_than(new_start, earliest_start):
                    earliest_start = new_start
            elif block['contiguous_position'] == 'after':
                new_end = round_to_half_hour(block['end'], is_end_time=True).strftime("%H:%M")
                if time_later_than(new_end, latest_end):
                    latest_end = new_end
    
    final_core_window["chargeStartTime"] = earliest_start
    final_core_window["chargeEndTime"] = latest_end
    
    # Second pass - process non-contiguous blocks
    for dispatch in sorted_dispatches:
        charge = abs(float(dispatch.get('charge_in_kwh', 0)))
        if charge <= 0:
            continue
            
        block = {
            'start': dispatch['start'],
            'end': dispatch['end'],
            'total_charge': charge
        }
        
        # Skip if already processed as contiguous
        already_exists = False
        for existing in result_blocks:
            if (existing['start'] == block['start'] and 
                existing['end'] == block['end']):
                already_exists = True
                break
                
        if already_exists:
            continue
            
        # Skip if overlaps with final extended core window
        if overlaps_core_hours(block['start'], block['end'], final_core_window):
            continue
            
        result_blocks.append(block)
    
    return result_blocks

def round_to_half_hour(dt, is_end_time=False):
    """Round datetime to nearest 30-minute interval. For end times, always round up."""
    if is_end_time:
        # For end times, if there are any minutes, round up to next 30 min interval
        if dt.minute > 0:
            if dt.minute <= 30:
                return dt.replace(minute=30, second=0, microsecond=0)
            else:
                return dt.replace(hour=dt.hour + 1, minute=0, second=0, microsecond=0)
        return dt.replace(minute=0, second=0, microsecond=0)
    else:
        # For start times, keep existing rounding logic
        if dt.minute >= 30:
            return dt.replace(minute=30, second=0, microsecond=0)
        return dt.replace(minute=0, second=0, microsecond=0)

def time_earlier_than(time1, time2):
    """Compare two time strings in HH:MM format."""
    h1, m1 = map(int, time1.split(':'))
    h2, m2 = map(int, time2.split(':'))
    return h1 < h2 or (h1 == h2 and m1 < m2)

def time_later_than(time1, time2):
    """Compare two time strings in HH:MM format."""
    h1, m1 = map(int, time1.split(':'))
    h2, m2 = map(int, time2.split(':'))
    return h1 > h2 or (h1 == h2 and m1 > m2)

@service
async def solis_smart_charging(config=None):
    """
    PyScript service to sync Solis charging windows with Octopus dispatch periods.
    Args:
        hass: Home Assistant instance
        config (dict): Configuration containing Solis API credentials
    """
    # Create session here where we have access to hass
    session = async_get_clientsession(hass)
    
    async def set_control_times_internal(token, inverterId, config, times):
        body = control_body(inverterId, times)
        headers = prepare_header(config, body, CONTROL_URL)
        headers['token'] = token
        response = await session.post(
            "https://www.soliscloud.com:13333"+CONTROL_URL,
            data=body,
            headers=headers
        )
        response_text = response.text()
        log.warning(f"solis response: {response_text}")
        return response_text

    async def login_internal(config):
        body = '{"userInfo":"'+str(config['username'])+'","password":"'+ passwordEncode(str(config['password']))+'"}' 
        header = prepare_header(config, body, LOGIN_URL)
        response = await session.post(
            "https://www.soliscloud.com:13333"+LOGIN_URL,
            data=body,
            headers=header
        )
        status = response.status
        response_text = response.text()
        r = json.loads(re.sub(r'("(?:\\?.)*?")|,\s*([]}])', r'\1\2', response_text))
        
        if status == HTTPStatus.OK:
            result = r
        else:
            log.warning(status)
            result = response_text
        
        return result["csrfToken"]

    async def getInverterList_internal(config):
        body = '{"stationId":"' + str(config['plantId']) + '"}'
        header = prepare_header(config, body, INVERTER_URL)
        response = await session.post(
            "https://www.soliscloud.com:13333" + INVERTER_URL,
            data=body,
            headers=header
        )
        inverterList = response.json()
        inverterId = ""
        for record in inverterList['data']['page']['records']:
            inverterId = record.get('id')
        return inverterId

    # Validate config
    if not config:
        log.error("No configuration provided")
        return
        
    if isinstance(config, str):
        config = json.loads(config)

    required_keys = ['secret', 'key_id', 'username', 'password', 'plantId']
    missing_keys = [key for key in required_keys if key not in config]
    
    if missing_keys:
        log.error(f"Missing required configuration keys: {', '.join(missing_keys)}")
        return

    # Get dispatch data
    dispatch_sensor = 'binary_sensor.octopus_energy_intelligent_dispatching'
    try:
        dispatches = state.getattr(dispatch_sensor)
    except Exception as e:
        log.error(f"Error getting dispatch data: {str(e)}")
        return

    log.info(f"Dispatches retrieved: {dispatches}")

    # Initialize default core hours and charging windows
    core_start = "23:30"
    core_end = "05:30"
    
    charging_windows = [
        {
            "chargeCurrent": "60",
            "dischargeCurrent": "100",
            "chargeStartTime": core_start,
            "chargeEndTime": core_end,
            "dischargeStartTime": "00:00",
            "dischargeEndTime": "00:00"
        }
    ]

    # Process dispatches if available
    if dispatches and 'planned_dispatches' in dispatches and dispatches['planned_dispatches']:
        try:
            charging_blocks = find_contiguous_blocks(dispatches['planned_dispatches'])
            
            if charging_blocks:
                log.debug(f"Charging blocks before selection: {charging_blocks}")

                # Find top two blocks by charge
                selected_blocks = []
                remaining_blocks = charging_blocks.copy()
                
                for _ in range(2):  # Get top 2 blocks
                    highest_charge = 0
                    highest_block = None
                    for block in remaining_blocks:
                        if block['total_charge'] > highest_charge:
                            highest_charge = block['total_charge']
                            highest_block = block
                    
                    if highest_block:
                        selected_blocks.append(highest_block)
                        remaining_blocks.remove(highest_block)

                log.debug(f"Selected blocks: {selected_blocks}")
                
                # Process selected blocks
                non_core_blocks = []
                for block in selected_blocks:
                    if block.get('contiguous_position') == 'before':
                        core_start = round_to_half_hour(block['start']).strftime("%H:%M")
                        charging_windows[0]["chargeStartTime"] = core_start
                        log.info(f"Extended core hours start to {core_start}")
                    elif block.get('contiguous_position') == 'after':
                        core_end = round_to_half_hour(block['end'], is_end_time=True).strftime("%H:%M")
                        charging_windows[0]["chargeEndTime"] = core_end
                        log.info(f"Extended core hours end to {core_end}")
                    else:
                        non_core_blocks.append(block)
                
                # Add non-core blocks
                for block in non_core_blocks:
                    start_time = round_to_half_hour(block['start'])
                    end_time = round_to_half_hour(block['end'], is_end_time=True)
                    
                    charging_windows.append({
                        "chargeCurrent": "60",
                        "dischargeCurrent": "100",
                        "chargeStartTime": start_time.strftime("%H:%M"),
                        "chargeEndTime": end_time.strftime("%H:%M"),
                        "dischargeStartTime": "00:00",
                        "dischargeEndTime": "00:00"
                    })
        
        except Exception as e:
            log.error(f"Error processing dispatch windows: {str(e)}")
            log.info("Falling back to core hours only")
    else:
        log.info("No planned dispatches available, using core hours only")

    # Fill remaining slots
    while len(charging_windows) < 3:
        charging_windows.append({
            "chargeCurrent": "60",
            "dischargeCurrent": "100",
            "chargeStartTime": "00:00",
            "chargeEndTime": "00:00",
            "dischargeStartTime": "00:00",
            "dischargeEndTime": "00:00"
        })

    try:
        # Get inverter ID
        inverterId = getInverterList_internal(config)
        log.info(f"Retrieved inverter ID: {inverterId}")

        # Login to get token
        token = login_internal(config)
        log.info("Successfully logged in to Solis API")

        # Set charging schedule
        result = set_control_times_internal(token, inverterId, config, charging_windows)
        
        log.info("Successfully set charging windows")
        return result

    except Exception as e:
        log.error(f"Error communicating with Solis API: {str(e)}")
        raise
