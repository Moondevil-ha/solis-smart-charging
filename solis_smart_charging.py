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

# API Helper Functions
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

# Time Handling Functions
def round_to_slot(dt, is_end_time=False):
    """
    Rounds datetime to nearest 30-minute slot.
    Args:
        dt: datetime to round
        is_end_time: if True, rounds up for end times, otherwise rounds down
    """
    minute = dt.minute
    if is_end_time:
        if minute == 30:  # Handle exact 30-min boundary for end times
            return dt.replace(second=0, microsecond=0)
        if minute > 0:
            if minute <= 30:
                return dt.replace(minute=30, second=0, microsecond=0)
            return dt.replace(hour=dt.hour + 1, minute=0, second=0, microsecond=0)
        return dt.replace(minute=0, second=0, microsecond=0)  # Handle exact hour boundary
    else:
        if minute >= 30:
            return dt.replace(minute=30, second=0, microsecond=0)
        return dt.replace(minute=0, second=0, microsecond=0)

def is_within_core_hours(start_dt, end_dt, core_start="23:30", core_end="05:30"):
    """Check if a time window falls entirely within core hours."""
    def to_minutes(dt):
        return dt.hour * 60 + dt.minute
    
    start_mins = to_minutes(start_dt)
    end_mins = to_minutes(end_dt)
    
    # Convert core times to minutes
    core_start_hour, core_start_minute = map(int, core_start.split(':'))
    core_end_hour, core_end_minute = map(int, core_end.split(':'))
    core_start_mins = core_start_hour * 60 + core_start_minute
    core_end_mins = core_end_hour * 60 + core_end_minute
    
    # Adjust for overnight period
    if core_start_mins > core_end_mins:  # Overnight period
        if start_mins >= core_start_mins:
            end_mins += 1440  # Add 24 hours worth of minutes
        core_end_mins += 1440
    
    return start_mins >= core_start_mins and end_mins <= core_end_mins

def normalize_dispatch(dispatch):
    """Normalize a single dispatch window to 30-minute slots."""
    return {
        'start': round_to_slot(dispatch['start'], is_end_time=False),
        'end': round_to_slot(dispatch['end'], is_end_time=True),
        **{k: v for k, v in dispatch.items() if k not in ['start', 'end']}
    }

def normalize_dispatches(dispatches, core_start="23:30", core_end="05:30"):
    """Filter out core-hour windows and normalize remaining ones."""
    normalized = []
    for dispatch in dispatches:
        if not is_within_core_hours(dispatch['start'], dispatch['end'], core_start, core_end):
            normalized.append(normalize_dispatch(dispatch))
    
    # Sort by start time using bubble sort
    n = len(normalized)
    for i in range(n):
        for j in range(0, n-i-1):
            if normalized[j]['start'] > normalized[j+1]['start']:
                normalized[j], normalized[j+1] = normalized[j+1], normalized[j]
    
    return normalized

def merge_dispatch_windows(normalized_dispatches):
    """Merge overlapping and contiguous dispatch windows."""
    if not normalized_dispatches:
        return []
    
    merged = []
    current_window = normalized_dispatches[0].copy()
    
    for next_window in normalized_dispatches[1:]:
        # Check for overlap or contiguity (within 1 second tolerance)
        if (next_window['start'] - current_window['end']).total_seconds() <= 1:
            # Extend current window
            current_window['end'] = max(current_window['end'], next_window['end'])
        else:
            # Calculate duration and store current window
            duration = (current_window['end'] - current_window['start']).total_seconds() / 60
            current_window['duration_minutes'] = duration
            merged.append(current_window)
            current_window = next_window.copy()
    
    # Add final window with duration
    duration = (current_window['end'] - current_window['start']).total_seconds() / 60
    current_window['duration_minutes'] = duration
    merged.append(current_window)
    
    return merged

def process_core_hours(merged_windows, core_start="23:30", core_end="05:30"):
    """Process windows against core hours and extend if overlaps or abuts.
    Iteratively checks for new overlaps after each extension."""
    
    # Convert core hours to datetime for easier comparison
    core_start_dt = datetime.strptime(core_start, "%H:%M")
    core_end_dt = datetime.strptime(core_end, "%H:%M")
    
    # Adjust for overnight core period
    if core_end_dt < core_start_dt:
        core_end_dt += timedelta(days=1)

    core_window = {
        'start': core_start_dt,
        'end': core_end_dt
    }
    
    # Keep track of which windows we've processed
    windows_to_check = merged_windows.copy()
    independent_windows = []
    changes_made = True
    
    while changes_made and windows_to_check:
        changes_made = False
        still_to_check = []
        
        for window in windows_to_check:
            window_start = window['start']
            window_end = window['end']
            
            # Adjust for overnight periods
            if window_end < window_start:
                window_end += timedelta(days=1)

            # NEW: If this is a morning window being compared to previous evening core start
            if window_start.hour < 12 and core_window['start'].hour > 12:
                window_start += timedelta(days=1)
                window_end += timedelta(days=1)
            
            # Check for any overlap or abutment (within 1 min tolerance)
            if ((window_start <= core_window['end'] + timedelta(minutes=1) and 
                window_end >= core_window['start'] - timedelta(minutes=1))):
                # Extend core window
                core_window['start'] = min(core_window['start'], window_start)
                core_window['end'] = max(core_window['end'], window_end)
                changes_made = True
            else:
                still_to_check.append(window)
        
        windows_to_check = still_to_check
    
    # Any windows left are truly independent
    independent_windows = windows_to_check
    
    # Format core_window back to string times
    result_core = {
        'start': core_window['start'].strftime("%H:%M"),
        'end': core_window['end'].strftime("%H:%M"),
        'type': 'core'
    }
    
    return result_core, independent_windows


def select_additional_windows(independent_windows, core_window):
    """Select additional windows based on duration and proximity to core start."""
    if not independent_windows:
        return []
    
    # Score windows based on duration and proximity to core start
    scored_windows = []
    max_duration = 0
    for window in independent_windows:
        if window['duration_minutes'] > max_duration:
            max_duration = window['duration_minutes']
    
    for window in independent_windows:
        # Duration score (0-1)
        duration_score = window['duration_minutes'] / max_duration if max_duration > 0 else 0
        
        # Proximity score (0-1)
        core_start_time = datetime.strptime(core_window['start'], "%H:%M").time()
        window_end = window['end']
        
        # Use window's timezone for consistency
        tz = window_end.tzinfo
        core_start_dt = datetime.combine(window_end.date(), core_start_time)
        core_start_dt = core_start_dt.replace(tzinfo=tz)
        
        if core_start_dt < window_end:
            core_start_dt += timedelta(days=1)
        
        minutes_to_core = (core_start_dt - window_end).total_seconds() / 60
        proximity_score = 1 - (min(minutes_to_core, 1440) / 1440)
        
        # Final score (70% duration, 30% proximity)
        final_score = (0.7 * duration_score) + (0.3 * proximity_score)
        scored_windows.append((window, final_score))
    
    # Sort by score using bubble sort
    n = len(scored_windows)
    for i in range(n):
        for j in range(0, n-i-1):
            if scored_windows[j][1] < scored_windows[j+1][1]:
                scored_windows[j], scored_windows[j+1] = scored_windows[j+1], scored_windows[j]
    
    # Select top 2 windows
    selected = []
    for i in range(min(2, len(scored_windows))):
        selected.append(scored_windows[i][0])
    
    # Sort selected windows by start time using bubble sort
    n = len(selected)
    for i in range(n):
        for j in range(0, n-i-1):
            if selected[j]['start'] > selected[j+1]['start']:
                selected[j], selected[j+1] = selected[j+1], selected[j]
    
    return selected

def format_charging_windows(core_window, additional_windows):
    """Format windows for Solis API."""
    charging_windows = [
        {
            "chargeCurrent": "60",
            "dischargeCurrent": "100",
            "chargeStartTime": core_window['start'],
            "chargeEndTime": core_window['end'],
            "dischargeStartTime": "00:00",
            "dischargeEndTime": "00:00"
        }
    ]
    
    for window in additional_windows:
        charging_windows.append({
            "chargeCurrent": "60",
            "dischargeCurrent": "100",
            "chargeStartTime": window['start'].strftime("%H:%M"),
            "chargeEndTime": window['end'].strftime("%H:%M"),
            "dischargeStartTime": "00:00",
            "dischargeEndTime": "00:00"
        })
    
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
    
    return charging_windows

def validate_charging_windows(charging_windows):
    """
    Validates charging windows before sending to API.
    Returns (bool, str) tuple - (is_valid, error_message)
    """
    # Check we have exactly 3 windows
    if len(charging_windows) != 3:
        return False, f"Expected 3 charging windows, got {len(charging_windows)}"
    
    # Validate each window's time format and slot alignment
    for i, window in enumerate(charging_windows):
        start = window['chargeStartTime']
        end = window['chargeEndTime']
        
        # Skip validation for dummy windows (00:00-00:00)
        if start == "00:00" and end == "00:00":
            continue
            
        # Check time format and slot alignment
        for time_str in [start, end]:
            try:
                hour, minute = map(int, time_str.split(':'))
                if minute not in [0, 30]:
                    return False, f"Window {i+1} time {time_str} not aligned to 30-minute slot"
            except:
                return False, f"Window {i+1} has invalid time format: {time_str}"
    
    return True, ""

# Send the charging windows
@service
async def solis_smart_charging(config=None):
    """
    PyScript service to sync Solis charging windows with Octopus dispatch periods.
    Args:
        config (dict): Configuration containing Solis API credentials
    """
    # Validate config first
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

    # Create session for all API calls
    async with async_get_clientsession(hass) as session:
        try:
            # Login to get token
            body = '{"userInfo":"'+str(config['username'])+'","password":"'+ passwordEncode(str(config['password']))+'"}' 
            header = prepare_header(config, body, LOGIN_URL)
            response = await session.post(
                "https://www.soliscloud.com:13333"+LOGIN_URL,
                data=body,
                headers=header
            )
            status = response.status
            response_text = response.text()  # Removed await
            r = json.loads(re.sub(r'("(?:\\?.)*?")|,\s*([]}])', r'\1\2', response_text))
            
            if status != HTTPStatus.OK:
                log.error(f"Login failed with status {status}")
                return
                
            token = r["csrfToken"]
            log.info("Successfully logged in to Solis API")

            # Get inverter ID
            body = '{"stationId":"' + str(config['plantId']) + '"}'
            header = prepare_header(config, body, INVERTER_URL)
            response = await session.post(
                "https://www.soliscloud.com:13333" + INVERTER_URL,
                data=body,
                headers=header
            )
            inverterList = response.json()  # Removed await
            inverterId = ""
            for record in inverterList['data']['page']['records']:
                inverterId = record.get('id')
            
            if not inverterId:
                log.error("No inverter ID found")
                return
                
            log.info(f"Retrieved inverter ID: {inverterId}")

            # Get dispatch data and process charging windows
            dispatch_sensor = 'binary_sensor.octopus_energy_a_42185595_intelligent_dispatching'
            try:
                dispatches = state.getattr(dispatch_sensor)
            except Exception as e:
                log.error(f"Error getting dispatch data: {str(e)}")
                return

            # Process dispatches if available
            charging_windows = None
            if dispatches and 'planned_dispatches' in dispatches and dispatches['planned_dispatches']:
                try:
                    normalized = normalize_dispatches(dispatches['planned_dispatches'])
                    merged_windows = merge_dispatch_windows(normalized)
                    core_window, independent_windows = process_core_hours(merged_windows)
                    additional_windows = select_additional_windows(independent_windows, core_window)
                    charging_windows = format_charging_windows(core_window, additional_windows)
                except Exception as e:
                    log.error(f"Error processing dispatch windows: {str(e)}")
                    log.info("Falling back to core hours only")
            
            if charging_windows is None:
                log.info("Using default core hours only")
                charging_windows = format_charging_windows(
                    {'start': "23:30", 'end': "05:30"},
                    []
                )

            # Add validation here
            is_valid, error_message = validate_charging_windows(charging_windows)
            if not is_valid:
                log.error(f"Invalid charging windows: {error_message}")
                return

            # Set charging schedule
            body = control_body(inverterId, charging_windows)
            headers = prepare_header(config, body, CONTROL_URL)
            headers['token'] = token
            response = await session.post(
                "https://www.soliscloud.com:13333"+CONTROL_URL,
                data=body,
                headers=headers
            )
            response_text = response.text()  # Removed await
            log.info(f"Solis API response: {response_text}")
            
            return response_text

        except Exception as e:
            log.error(f"Error communicating with Solis API: {str(e)}")
            raise
