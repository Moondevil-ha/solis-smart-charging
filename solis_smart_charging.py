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

# SolisCloud API Helper Functions - Unchanged
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
# Time handling helper functions
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

# Dispatch normalization functions
def normalize_dispatch_window(dispatch):
    """
    Normalizes a dispatch window to exact 30-minute slots.
    Maintains all original dispatch data, only adjusting timestamps.
    
    Args:
        dispatch: Dictionary containing 'start' and 'end' datetime objects
        from Octopus dispatch data
    
    Returns:
        Dictionary with normalized start/end times aligned to 30-min slots
    """
    def round_to_slot(dt, round_up=False):
        """
        Rounds datetime to nearest 30-minute slot.
        For start times rounds down, for end times rounds up to ensure
        we capture full charging window.
        """
        minute = dt.minute
        if round_up:
            # For end times, round up to next 30-min slot
            if minute > 0:
                if minute <= 30:
                    return dt.replace(minute=30, second=0, microsecond=0)
                else:
                    return dt.replace(hour=dt.hour + 1, minute=0, second=0, microsecond=0)
        else:
            # For start times, round down to previous 30-min slot
            if minute >= 30:
                return dt.replace(minute=30, second=0, microsecond=0)
            return dt.replace(minute=0, second=0, microsecond=0)
        return dt.replace(second=0, microsecond=0)
    
    normalized = dispatch.copy()
    normalized['start'] = round_to_slot(dispatch['start'])
    normalized['end'] = round_to_slot(dispatch['end'], round_up=True)
    return normalized

def normalize_dispatches(dispatches):
    """
    Normalizes all dispatch windows and sorts them chronologically.
    Every dispatch window represents a valid charging opportunity.
    
    Args:
        dispatches: List of dispatch dictionaries from Octopus API
        
    Returns:
        List of normalized dispatch dictionaries sorted by start time
    """
    normalized = [normalize_dispatch_window(dispatch) for dispatch in dispatches]
    return sorted(normalized, key=lambda x: x['start'])

def merge_dispatch_windows(normalized_dispatches):
    """
    Merges normalized dispatch windows that are exactly contiguous.
    Windows must be pre-normalized to 30-minute slots.
    
    Args:
        normalized_dispatches: List of dispatch dictionaries with 
        normalized 30-minute slot timestamps,
        sorted chronologically
    
    Returns:
        List of merged dispatch windows, each dictionary containing:
        - start: datetime of window start
        - end: datetime of window end
        - duration_minutes: length of window in minutes
        - windows_merged: count of original windows combined
    """
    if not normalized_dispatches:
        return []
    
    merged = []
    current_window = {
        'start': normalized_dispatches[0]['start'],
        'end': normalized_dispatches[0]['end'],
        'windows_merged': 1
    }
    
    for dispatch in normalized_dispatches[1:]:
        # If this window starts exactly when current window ends
        if dispatch['start'] == current_window['end']:
            # Extend current window
            current_window['end'] = dispatch['end']
            current_window['windows_merged'] += 1
        else:
            # Calculate duration before storing
            duration = (current_window['end'] - current_window['start']).total_seconds() / 60
            current_window['duration_minutes'] = duration
            
            # Store the completed window
            merged.append(current_window)
            
            # Start a new window
            current_window = {
                'start': dispatch['start'],
                'end': dispatch['end'],
                'windows_merged': 1
            }
    
    # Add the final window
    duration = (current_window['end'] - current_window['start']).total_seconds() / 60
    current_window['duration_minutes'] = duration
    merged.append(current_window)
    
    return merged
def is_window_contiguous(window, core_start, core_end):
    """
    Checks if a window is contiguous with core hours.
    All times must be normalized to 30-minute slots.
    
    Args:
        window: Dictionary with 'start' and 'end' datetimes
        core_start: String "HH:MM" core hours start time
        core_end: String "HH:MM" core hours end time
        
    Returns:
        Tuple (bool, str): (is_contiguous, position)
        position is either 'before', 'after', or None
    """
    # Convert core hours to datetime objects on same day as window
    core_start_hour, core_start_minute = map(int, core_start.split(':'))
    core_end_hour, core_end_minute = map(int, core_end.split(':'))
    
    core_start_time = window['start'].replace(
        hour=core_start_hour, 
        minute=core_start_minute, 
        second=0, 
        microsecond=0
    )
    
    core_end_time = window['start'].replace(
        hour=core_end_hour, 
        minute=core_end_minute, 
        second=0, 
        microsecond=0
    )
    
    # Adjust for overnight core hours
    if core_start_time > core_end_time:
        if window['start'].hour < core_end_hour or window['start'].hour >= core_start_hour:
            core_end_time += timedelta(days=1)
    
    # Check if window is contiguous before core hours
    if window['end'] == core_start_time:
        return True, 'before'
        
    # Check if window is contiguous after core hours
    if window['start'] == core_end_time:
        return True, 'after'
    
    return False, None

def does_window_overlap_core(window, core_start, core_end):
    """
    Checks if a window overlaps with core hours.
    All times must be normalized to 30-minute slots.
    
    Args:
        window: Dictionary with 'start' and 'end' datetimes
        core_start: String "HH:MM" core start time
        core_end: String "HH:MM" core end time
    
    Returns:
        bool: True if window overlaps core hours
    """
    window_start = window['start'].strftime("%H:%M")
    window_end = window['end'].strftime("%H:%M")
    
    # Handle overnight core period
    if time_earlier_than(core_end, core_start):
        # Core period crosses midnight
        return (not (time_earlier_than(window_end, core_start) and 
                    time_later_than(window_start, core_end)))
    else:
        # Core period within same day
        return (not (time_earlier_than(window_end, core_start) or 
                    time_later_than(window_start, core_end)))

def process_core_hours(merged_windows, core_start="23:30", core_end="05:30"):
    """
    Processes merged windows against core hours, identifying windows that extend
    the core charging period and separating out independent windows.
    
    All windows must be pre-normalized to 30-minute slots.
    
    Args:
        merged_windows: List of merged dispatch window dictionaries
        core_start: String "HH:MM" default core hours start time
        core_end: String "HH:MM" default core hours end time
        
    Returns:
        Tuple containing:
        - Dictionary with final core window details including extended times
        - List of remaining independent charging windows
    """
    # Initialize extended core window times
    extended_core = {
        'start': core_start,
        'end': core_end
    }
    
    independent_windows = []
    
    # First pass: identify windows that extend core hours
    for window in merged_windows:
        is_contiguous, position = is_window_contiguous(window, 
            extended_core['start'],
            extended_core['end'])
        
        window_start = window['start'].strftime("%H:%M")
        window_end = window['end'].strftime("%H:%M")
        
        if is_contiguous:
            if position == 'before':
                # Extend core start time if window starts earlier
                if time_earlier_than(window_start, extended_core['start']):
                    extended_core['start'] = window_start
            elif position == 'after':
                # Extend core end time if window ends later
                if time_later_than(window_end, extended_core['end']):
                    extended_core['end'] = window_end
        else:
            # Check if window overlaps core hours
            overlaps = does_window_overlap_core(window, 
                extended_core['start'],
                extended_core['end'])
            if not overlaps:
                independent_windows.append(window)
    
    # Calculate final core window duration
    core_window = {
        'start': extended_core['start'],
        'end': extended_core['end'],
        'type': 'core',
        'duration_minutes': calculate_window_duration(
            extended_core['start'],
            extended_core['end']
        )
    }
    
    return core_window, independent_windows

def calculate_window_duration(start_time, end_time):
    """
    Calculates duration in minutes between two HH:MM times,
    handling overnight windows correctly.
    
    Args:
        start_time: String "HH:MM"
        end_time: String "HH:MM"
    
    Returns:
        int: Duration in minutes
    """
    start_hour, start_minute = map(int, start_time.split(':'))
    end_hour, end_minute = map(int, end_time.split(':'))
    
    minutes = ((end_hour - start_hour) * 60 + (end_minute - start_minute))
    if minutes < 0:  # Overnight window
        minutes += 24 * 60
        
    return minutes
    
def select_additional_windows(independent_windows, core_window):
    """
    Selects additional charging windows based on:
    1. Window duration (longer windows preferred)
    2. Proximity to core start (closer to core start preferred as battery 
        more likely to need charging)
    
    Args:
        independent_windows: List of window dictionaries not overlapping/contiguous 
        with core hours
        core_window: Dictionary containing core window details including 
                    'start' time
    
    Returns:
        List of up to 2 selected windows, ordered by start time
    """
    if not independent_windows:
        return []
        
    def calculate_window_score(window):
        """
        Scores a window based on duration and proximity to core start.
        Duration weighted more heavily (0.7) than proximity (0.3)
        """
        # Get end time of window for calculations
        window_end = window['end']
        
        # Convert core start time string to time object
        core_start_time = datetime.strptime(core_window['start'], "%H:%M").time()
        
        # Create timezone-aware datetime for comparison
        # IMPORTANT: Must include timezone info to match window_end
        core_start_dt = datetime.combine(window_end.date(), core_start_time).replace(
            tzinfo=window_end.tzinfo
        )
        
        # Handle overnight windows by adding a day if needed
        if core_start_dt < window_end:
            core_start_dt += timedelta(days=1)
        
        # Calculate time to core in minutes
        time_to_core = (core_start_dt - window_end).total_seconds() / 60
        
        # Calculate proximity score (0-1 range)
        proximity_score = 1 - (min(time_to_core, 1440) / 1440)
        
        # Find maximum duration using explicit loop
        # Replaced generator expression for pyscript compatibility
        max_duration = 0
        for w in independent_windows:
            if w['duration_minutes'] > max_duration:
                max_duration = w['duration_minutes']
        
        # Calculate duration score (0-1 range)
        duration_score = window['duration_minutes'] / max_duration
        
        # Return weighted combination of scores
        return (0.7 * duration_score) + (0.3 * proximity_score)
    
    # Score all windows
    scored_windows = []
    for window in independent_windows:
        score = calculate_window_score(window)
        # Create new dictionary to avoid modifying original
        window_copy = window.copy()
        window_copy['score'] = score
        scored_windows.append(window_copy)
    
    # Helper function for score-based sorting
    def score_sort_key(x):
        """Get score value, defaulting to 0 if not found"""
        return x.get('score', 0)
    
    # Sort by score descending using bubble sort
    # Replaced lambda-based sort for pyscript compatibility
    n = len(scored_windows)
    for i in range(n):
        for j in range(0, n-i-1):
            if score_sort_key(scored_windows[j]) < score_sort_key(scored_windows[j+1]):
                scored_windows[j], scored_windows[j+1] = scored_windows[j+1], scored_windows[j]
    
    # Select top 2 windows
    selected = scored_windows[:2] if len(scored_windows) > 2 else scored_windows
    
    # Helper function for time-based sorting
    def start_time_sort_key(x):
        """Get start time for chronological sorting"""
        return x['start']
    
    # Sort selected windows by start time using bubble sort
    n = len(selected)
    for i in range(n):
        for j in range(0, n-i-1):
            if start_time_sort_key(selected[j]) > start_time_sort_key(selected[j+1]):
                selected[j], selected[j+1] = selected[j+1], selected[j]
    
    return selected

def format_charging_windows(core_window, additional_windows):
    """
    Formats the selected charging windows into the structure expected by the 
    Solis API.
    
    Args:
        core_window: Dictionary containing core charging window
        additional_windows: List of additional charging windows
        
    Returns:
        List of dictionaries in Solis API format
    """
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
    
    # Add additional windows
    for window in additional_windows:
        charging_windows.append({
            "chargeCurrent": "60",
            "dischargeCurrent": "100",
            "chargeStartTime": window['start'].strftime("%H:%M"),
            "chargeEndTime": window['end'].strftime("%H:%M"),
            "dischargeStartTime": "00:00",
            "dischargeEndTime": "00:00"
        })
    
    # Fill remaining slots if needed
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
    dispatch_sensor = 'binary_sensor.octopus_energy_a_42185595_intelligent_dispatching'
    try:
        dispatches = state.getattr(dispatch_sensor)
    except Exception as e:
        log.error(f"Error getting dispatch data: {str(e)}")
        return

    log.info(f"Dispatches retrieved: {dispatches}")

    # Process dispatches if available
    charging_windows = None
    if dispatches and 'planned_dispatches' in dispatches and dispatches['planned_dispatches']:
        try:
            # Normalize and merge dispatch windows
            normalized = normalize_dispatches(dispatches['planned_dispatches'])
            merged_windows = merge_dispatch_windows(normalized)
            
            # Process core hours and get independent windows
            core_window, independent_windows = process_core_hours(merged_windows)
            
            # Select additional windows based on duration and timing
            additional_windows = select_additional_windows(independent_windows, core_window)
            
            # Format windows for Solis API
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
