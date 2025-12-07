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
log.setLevel(logging.DEBUG)

def debug_log(prefix, message):
    log.debug(f"{prefix}: {message}")

# Constants
VERB = "POST"
LOGIN_URL = '/v2/api/login'
CONTROL_URL= '/v2/api/control'
INVERTER_URL= '/v1/api/inverterList'

# API Helper Functions - Keeping exactly as is
def digest(body: str) -> str:
    return base64.b64encode(hashlib.md5(body.encode('utf-8')).digest()).decode('utf-8')

def passwordEncode(password: str) -> str:
    return hashlib.md5(password.encode('utf-8')).hexdigest()

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

class WindowProcessor:
    def __init__(self):
        self.core_window = None
        self.dispatch_blocks = []
        self.charging_windows = []
        
    def initialize_core_window(self, first_dispatch_time):
        """Initialize core window based on first dispatch timezone and date.
        If dispatches are received during early hours (00:00-12:00), align core window to previous day."""
        dispatch_tz = first_dispatch_time.tzinfo
        dispatch_hour = first_dispatch_time.hour
    
        # If we receive dispatches between midnight and noon, 
        # we're probably processing the current night's schedule
        if 0 <= dispatch_hour < 12:
            dispatch_date = (first_dispatch_time - timedelta(days=1)).date()
        else:
            dispatch_date = first_dispatch_time.date()
        
        next_date = dispatch_date + timedelta(days=1)
    
        # Initialize core window with same timezone as dispatches
        core_start = datetime.combine(dispatch_date, 
                                    datetime.strptime('23:30', '%H:%M').time()
                                    ).replace(tzinfo=dispatch_tz)
        core_end = datetime.combine(next_date, 
                                    datetime.strptime('05:30', '%H:%M').time()
                                    ).replace(tzinfo=dispatch_tz)
    
        self.core_window = {
            'start': core_start,
            'end': core_end
        }
        log.debug(f"Initialized core window: {self.core_window['start']} to {self.core_window['end']}")

    def round_to_slot(self, dt: datetime, is_end_time: bool = False) -> datetime:
        """Round datetime to nearest 30-minute slot."""
        result = dt.replace(second=0, microsecond=0)
        minute = result.minute
        
        if is_end_time:
            if minute > 0:
                if minute <= 30:
                    result = result.replace(minute=30)
                else:
                    result = result + timedelta(hours=1)
                    result = result.replace(minute=0)
        else:
            result = result.replace(minute=(minute // 30) * 30)
        
        return result

    def normalize_dispatch(self, dispatch: dict) -> dict:
        """Normalize a dispatch window, maintaining all original attributes."""
        normalized = {
            'start': self.round_to_slot(dispatch['start'], False),
            'end': self.round_to_slot(dispatch['end'], True),
            'duration_minutes': (dispatch['end'] - dispatch['start']).total_seconds() / 60
        }
        # Copy any additional attributes
        for k, v in dispatch.items():
            if k not in ['start', 'end']:
                normalized[k] = v
        return normalized

    def normalize_dispatches(self, dispatches: list) -> list:
        """Process incoming dispatch windows."""
        log.debug(f"\nProcessing {len(dispatches)} dispatch windows")
        
        if not dispatches:
            return []
            
        # Initialize core window based on first dispatch
        if self.core_window is None:
            self.initialize_core_window(dispatches[0]['start'])
            
        self.dispatch_blocks = []
        valid_dispatches = []
        
        # First pass: normalize all windows
        for dispatch in dispatches:
            normalized = self.normalize_dispatch(dispatch)
            log.debug(f"Normalized window: {normalized['start']} to {normalized['end']}")
            valid_dispatches.append(normalized)
        
        # Bubble sort by start time
        n = len(valid_dispatches)
        for i in range(n):
            for j in range(0, n - i - 1):
                if valid_dispatches[j]['start'] > valid_dispatches[j + 1]['start']:
                    valid_dispatches[j], valid_dispatches[j + 1] = valid_dispatches[j + 1], valid_dispatches[j]
        
        log.debug("Sorted windows:")
        for window in valid_dispatches:
            log.debug(f"  {window['start']} to {window['end']}")
        
        # Merge contiguous windows
        if valid_dispatches:
            current_window = valid_dispatches[0].copy()
            
            for next_window in valid_dispatches[1:]:
                # Check for contiguous or overlapping windows
                if (next_window['start'] - current_window['end']).total_seconds() <= 1:
                    log.debug(f"Merging windows: {current_window['end']} and {next_window['start']}")
                    # Extend current window
                    current_window['end'] = max(current_window['end'], next_window['end'])
                    current_window['duration_minutes'] = (current_window['end'] - current_window['start']).total_seconds() / 60
                else:
                    self.dispatch_blocks.append(current_window)
                    current_window = next_window.copy()
            
            self.dispatch_blocks.append(current_window)
        
        log.debug("\nFinal merged dispatch blocks:")
        for block in self.dispatch_blocks:
            log.debug(f"  {block['start']} to {block['end']} (duration: {block['duration_minutes']} mins)")
        
        return self.dispatch_blocks

    def process_core_hours(self):
        """Process windows against core hours and extend if needed."""
        if not self.core_window:
            return
            
        log.debug(f"\nProcessing core hours")
        log.debug(f"Initial core window: {self.core_window['start']} to {self.core_window['end']}")
        
        while True:
            changes_made = False
            remaining_blocks = []
            
            for window in self.dispatch_blocks:
                log.debug(f"\nChecking window: {window['start']} to {window['end']}")
                
                # Check if window overlaps core
                if (window['start'] <= self.core_window['end'] and 
                    window['end'] >= self.core_window['start']):
                    
                    if window['start'] < self.core_window['start']:
                        log.debug(f"Extending core start from {self.core_window['start']} to {window['start']}")
                        self.core_window['start'] = window['start']
                        changes_made = True
                    
                    if window['end'] > self.core_window['end']:
                        log.debug(f"Extending core end from {self.core_window['end']} to {window['end']}")
                        self.core_window['end'] = window['end']
                        changes_made = True
                else:
                    log.debug("Window outside core - keeping for additional windows")
                    remaining_blocks.append(window)
            
            self.dispatch_blocks = remaining_blocks
            
            if not changes_made:
                break
        
        log.debug(f"\nAfter core processing:")
        log.debug(f"Final core window: {self.core_window['start']} to {self.core_window['end']}")
        if remaining_blocks:
            log.debug("Remaining windows for additional selection:")
            for block in remaining_blocks:
                log.debug(f"  {block['start']} to {block['end']} (duration: {block['duration_minutes']} mins)")
        else:
            log.debug("No remaining windows for additional selection")

    def select_additional_windows(self):
        """Select up to two additional windows based on duration."""
        if not self.dispatch_blocks:
            return []
        
        log.debug("\nSelecting additional windows")
        
        # Bubble sort by duration (longest first)
        blocks = self.dispatch_blocks.copy()
        n = len(blocks)
        for i in range(n):
            for j in range(0, n - i - 1):
                if blocks[j]['duration_minutes'] < blocks[j + 1]['duration_minutes']:
                    blocks[j], blocks[j + 1] = blocks[j + 1], blocks[j]
        
        selected = blocks[:2]
        log.debug("Selected windows:")
        for window in selected:
            log.debug(f"  {window['start']} to {window['end']} (duration: {window['duration_minutes']} mins)")
        
        return selected

    def format_charging_windows(self, additional_windows):
        """Format windows for Solis API."""
        log.debug("\nFormatting charging windows")
    
        if not self.core_window:
            # Initialize with default core window using current time
            self.initialize_core_window(datetime.now(timezone.utc))
            
        # Add core window
        self.charging_windows = [{
            "chargeCurrent": "60",
            "dischargeCurrent": "100",
            "chargeStartTime": self.core_window['start'].strftime("%H:%M"),
            "chargeEndTime": self.core_window['end'].strftime("%H:%M"),
            "dischargeStartTime": "00:00",
            "dischargeEndTime": "00:00"
        }]
        log.debug(f"Core window: {self.charging_windows[0]}")
    
        # Add additional windows
        for window in additional_windows:
            formatted = {
                "chargeCurrent": "60",
                "dischargeCurrent": "100",
                "chargeStartTime": window['start'].strftime("%H:%M"),
                "chargeEndTime": window['end'].strftime("%H:%M"),
                "dischargeStartTime": "00:00",
                "dischargeEndTime": "00:00"
            }
            self.charging_windows.append(formatted)
            log.debug(f"Additional window: {formatted}")
    
        # Fill with dummy windows if needed
        while len(self.charging_windows) < 3:
            dummy = {
                "chargeCurrent": "60",
                "dischargeCurrent": "100",
                "chargeStartTime": "00:00",
                "chargeEndTime": "00:00",
                "dischargeStartTime": "00:00",
                "dischargeEndTime": "00:00"
            }
            self.charging_windows.append(dummy)
            log.debug(f"Added dummy window: {dummy}")
    
        return self.charging_windows

@service
async def solis_smart_charging(config=None):
    """PyScript service to sync Solis charging windows with Octopus dispatch periods."""
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
    
    session = async_get_clientsession(hass)
    
    try:
        # Login
        body = '{"userInfo":"'+str(config['username'])+'","password":"'+ passwordEncode(str(config['password']))+'"}' 
        header = prepare_header(config, body, LOGIN_URL)
        login_response = await session.post(
            "https://www.soliscloud.com:13333"+LOGIN_URL,
            data=body,
            headers=header
        )
        
        if login_response.status != HTTPStatus.OK:
            log.error(f"Login failed with status {login_response.status}")
            return
            
        login_text = login_response.text()  # No await here
        login_data = json.loads(re.sub(r'("(?:\\?.)*?")|,\s*([]}])', r'\1\2', login_text))
        token = login_data["csrfToken"]
        
        # Get inverter ID (updated logic for multi-inverter plants)
        inverter_body = '{"stationId":"' + str(config['plantId']) + '"}'
        inverter_header = prepare_header(config, inverter_body, INVERTER_URL)
        inverter_response = await session.post(
            "https://www.soliscloud.com:13333" + INVERTER_URL,
            data=inverter_body,
            headers=inverter_header
        )
        
        try:
            inverter_data = inverter_response.json()  # No await here
        except Exception as e:
            log.error(f"Failed to decode inverter list JSON: {str(e)}")
            return

        records = inverter_data.get('data', {}).get('page', {}).get('records', []) or []
        if not records:
            log.error("No inverters returned from inverterList")
            return

        # Optional explicit config overrides
        cfg_sn = str(config.get('inverter_sn', '')).strip()
        cfg_id = str(config.get('inverter_id', '')).strip()

        chosen = None

        if cfg_sn or cfg_id:
            for record in records:
                if cfg_sn and str(record.get('sn')) == cfg_sn:
                    chosen = record
                    break
                if cfg_id and str(record.get('id')) == cfg_id:
                    chosen = record
                    break
            if not chosen:
                log.error("Configured inverter_sn/inverter_id not found in inverterList; please check your config.")
                return
        else:
            # Try to auto-select a storage (battery) inverter: productModel == 2
            storage_records = [r for r in records if str(r.get('productModel')) == '2']
            if len(storage_records) == 1:
                chosen = storage_records[0]
                log.info(
                    "Auto-selected storage inverter id=%s sn=%s name=%s",
                    chosen.get('id'),
                    chosen.get('sn'),
                    chosen.get('name')
                )
            elif len(storage_records) > 1:
                log.error(
                    "Multiple storage inverters found but no inverter_sn/inverter_id configured. "
                    "Please add one to your solis_smart_charging config."
                )
                return
            else:
                # No storage inverter – fallback to single inverter only
                if len(records) == 1:
                    chosen = records[0]
                    log.info(
                        "Only one inverter found, using id=%s sn=%s name=%s",
                        chosen.get('id'),
                        chosen.get('sn'),
                        chosen.get('name')
                    )
                else:
                    log.error(
                        "Multiple inverters found and none identified as storage. "
                        "Please set inverter_sn or inverter_id in your solis_smart_charging config."
                    )
                    return

        inverterId = chosen.get('id')

        if not inverterId:
            log.error("No inverter ID found after selection")
            return
        
        # Process dispatch windows
        dispatch_sensor = config.get('dispatch_sensor')
        if not dispatch_sensor:
            log.error("No dispatch sensor ID provided in configuration")
            return
        processor = WindowProcessor()
        
        try:
            dispatches = state.getattr(dispatch_sensor)
            if dispatches and 'planned_dispatches' in dispatches:
                processor.normalize_dispatches(dispatches['planned_dispatches'])
                processor.process_core_hours()
                additional_windows = processor.select_additional_windows()
                charging_windows = processor.format_charging_windows(additional_windows)
            else:
                charging_windows = processor.format_charging_windows([])  # Use default core hours
        except Exception as e:
            log.error(f"Error processing dispatch windows: {str(e)}")
            log.info("Using default core hours")
            charging_windows = processor.format_charging_windows([])

        # Check if the charging windows have changed
        current_state = hass.states.get("sensor.solis_charge_schedule")
        if current_state and current_state.attributes.get("charging_windows"):
            current_windows = current_state.attributes["charging_windows"]
            windows_match = True
            
            # Compare each window
            for new_window, existing_window in zip(charging_windows, current_windows):
                if (new_window["chargeStartTime"] != existing_window["chargeStartTime"] or
                    new_window["chargeEndTime"] != existing_window["chargeEndTime"]):
                    windows_match = False
                    break
            
            if windows_match:
                log.info("Charging windows unchanged - skipping API update")
                return "Windows unchanged - no update needed"
        
        # Send to Solis API
        control_data = control_body(inverterId, charging_windows)
        control_headers = prepare_header(config, control_data, CONTROL_URL)
        control_headers['token'] = token
        
        control_response = await session.post(
            "https://www.soliscloud.com:13333"+CONTROL_URL,
            data=control_data,
            headers=control_headers
        )
        
        response_text = control_response.text()  # No await here
        log.info(f"Solis API response: {response_text}")
        if control_response.status == HTTPStatus.OK:
            try:
                response_data = control_response.json()  # No await here
                if response_data.get("code") == "0" and response_data.get("data", [{}])[0].get("code") == 0:
                    schedule_text = ""
                    for window in charging_windows:
                        if window['chargeStartTime'] != "00:00" or window['chargeEndTime'] != "00:00":
                            schedule_text += f"{window['chargeStartTime']}-{window['chargeEndTime']}, "
                    
                    schedule_text = schedule_text.rstrip(", ")
                    
                    hass.states.async_set(
                        "sensor.solis_charge_schedule",
                        schedule_text,
                        {
                            "charging_windows": charging_windows,
                            "last_updated": datetime.now(timezone.utc).isoformat(),
                            "schedule_source": "octopus_dispatch",
                            "last_api_response": "success"
                        }
                    )
            except Exception as e:
                log.error(f"Failed to create sensor, but main script succeeded: {str(e)}")
        return response_text
        
    except Exception as e:
        log.error(f"Error in solis_smart_charging: {str(e)}")
        raise
