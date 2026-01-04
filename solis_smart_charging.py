import json
import re
import asyncio
import logging
import hashlib
import hmac
import base64

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from homeassistant.helpers.aiohttp_client import async_get_clientsession

log = logging.getLogger("pyscript.solis_smart_charging")
log.setLevel(logging.DEBUG)

# -----------------------------
# SolisCloud endpoints / constants
# -----------------------------
BASE_URL = "https://www.soliscloud.com:13333"
VERB = "POST"

LOGIN_URL = "/v2/api/login"
CONTROL_URL = "/v2/api/control"
AT_READ_URL = "/v2/api/atRead"

INVERTER_LIST_URL = "/v1/api/inverterList"
INVERTER_DETAIL_URL = "/v1/api/inverterDetail"

# Legacy 3-slot schedule CID
LEGACY_SCHEDULE_CID = "103"

# 6-slot firmware (HMI >= 4B00) time CIDs from hultenvp/solis-sensor control_const.py (True map)
CHARGE_TIME_CIDS = ["5946", "5949", "5952", "5955", "5958", "5961"]
DISCHARGE_TIME_CIDS = ["5964", "5968", "5972", "5976", "5980", "5987"]

# Optional per-slot current / SOC CIDs (only if enabled)
CHARGE_CURRENT_CIDS = ["5948", "5951", "5954", "5957", "5960", "5963"]
CHARGE_SOC_CIDS = ["5928", "5929", "5930", "5931", "5932", "5933"]

DISCHARGE_CURRENT_CIDS = ["5967", "5971", "5975", "5979", "5983", "5986"]
DISCHARGE_SOC_CIDS = ["5965", "5969", "5973", "5977", "5981", "5984"]


# -----------------------------
# SolisCloud auth helpers
# -----------------------------
def digest(body: str) -> str:
    return base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode("utf-8")


def passwordEncode(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def prepare_header(config: dict[str, str], body: str, canonicalized_resource: str) -> dict[str, str]:
    content_md5 = digest(body)
    content_type = "application/json"

    now = datetime.now(timezone.utc)
    date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

    encrypt_str = (
        VERB + "\n" + content_md5 + "\n" + content_type + "\n" + date + "\n" + canonicalized_resource
    )

    hmac_obj = hmac.new(
        config["secret"].encode("utf-8"),
        msg=encrypt_str.encode("utf-8"),
        digestmod=hashlib.sha1,
    )
    sign = base64.b64encode(hmac_obj.digest())
    authorization = "API " + str(config["key_id"]) + ":" + sign.decode("utf-8")

    return {
        "Content-MD5": content_md5,
        "Content-Type": content_type,
        "Date": date,
        "Authorization": authorization,
    }


def _clean_json_text(text: str) -> str:
    # SolisCloud sometimes returns JSON with trailing commas.
    return re.sub(r'("(?:\\?.)*?")|,\s*([]}])', r"\1\2", text)


# -----------------------------
# Legacy CID103 payload builder (3-slot)
# -----------------------------
def legacy_control_body(inverterId, chargeSettings) -> str:
    # Robust join (removes old hard-coded index != 2 logic)
    parts = []
    for w in chargeSettings:
        parts.append(
            f"{w['chargeCurrent']},{w['dischargeCurrent']},"
            f"{w['chargeStartTime']},{w['chargeEndTime']},"
            f"{w['dischargeStartTime']},{w['dischargeEndTime']}"
        )
    value = ",".join(parts)
    return f'{{"inverterId":"{inverterId}", "cid":"{LEGACY_SCHEDULE_CID}","value":"{value}"}}'


# -----------------------------
# Dispatch window processing (your logic; slot-count aware)
# -----------------------------
class WindowProcessor:
    def __init__(self, max_slots: int):
        self.max_slots = max_slots
        self.core_window = None
        self.dispatch_blocks = []

    def initialize_core_window(self, first_dispatch_time):
        dispatch_tz = first_dispatch_time.tzinfo
        dispatch_hour = first_dispatch_time.hour

        if 0 <= dispatch_hour < 12:
            dispatch_date = (first_dispatch_time - timedelta(days=1)).date()
        else:
            dispatch_date = first_dispatch_time.date()

        next_date = dispatch_date + timedelta(days=1)

        core_start = datetime.combine(
            dispatch_date, datetime.strptime("23:30", "%H:%M").time()
        ).replace(tzinfo=dispatch_tz)
        core_end = datetime.combine(
            next_date, datetime.strptime("05:30", "%H:%M").time()
        ).replace(tzinfo=dispatch_tz)

        self.core_window = {"start": core_start, "end": core_end}
        log.debug("Initialized core window: %s to %s", core_start, core_end)

    def round_to_slot(self, dt: datetime, is_end_time: bool = False) -> datetime:
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
        normalized = {
            "start": self.round_to_slot(dispatch["start"], False),
            "end": self.round_to_slot(dispatch["end"], True),
            "duration_minutes": (dispatch["end"] - dispatch["start"]).total_seconds() / 60,
        }
        for k, v in dispatch.items():
            if k not in ["start", "end"]:
                normalized[k] = v
        return normalized

    def normalize_dispatches(self, dispatches: list) -> list:
        if not dispatches:
            return []

        if self.core_window is None:
            self.initialize_core_window(dispatches[0]["start"])

        # Build normalized list (PyScript doesn't support list comprehensions in some contexts)
        valid = []
        for d in dispatches:
            valid.append(self.normalize_dispatch(d))
        
        # Sort by start time manually (PyScript lambda support is unreliable)
        # Bubble sort for simplicity and PyScript compatibility
        for i in range(len(valid)):
            for j in range(len(valid) - 1 - i):
                if valid[j]["start"] > valid[j + 1]["start"]:
                    valid[j], valid[j + 1] = valid[j + 1], valid[j]

        merged = []
        current = valid[0].copy()
        for nxt in valid[1:]:
            if (nxt["start"] - current["end"]).total_seconds() <= 1:
                current["end"] = max(current["end"], nxt["end"])
                current["duration_minutes"] = (current["end"] - current["start"]).total_seconds() / 60
            else:
                merged.append(current)
                current = nxt.copy()
        merged.append(current)

        self.dispatch_blocks = merged
        return merged

    def process_core_hours(self):
        if not self.core_window:
            return

        while True:
            changes = False
            remaining = []

            for window in self.dispatch_blocks:
                overlaps = (
                    window["start"] <= self.core_window["end"]
                    and window["end"] >= self.core_window["start"]
                )
                if overlaps:
                    if window["start"] < self.core_window["start"]:
                        self.core_window["start"] = window["start"]
                        changes = True
                    if window["end"] > self.core_window["end"]:
                        self.core_window["end"] = window["end"]
                        changes = True
                else:
                    remaining.append(window)

            self.dispatch_blocks = remaining
            if not changes:
                break

    def select_additional_windows(self):
        if not self.dispatch_blocks:
            return []

        blocks = self.dispatch_blocks.copy()
        
        # Sort by duration (longest first) - manual sort for PyScript compatibility
        for i in range(len(blocks)):
            for j in range(len(blocks) - 1 - i):
                if blocks[j]["duration_minutes"] < blocks[j + 1]["duration_minutes"]:
                    blocks[j], blocks[j + 1] = blocks[j + 1], blocks[j]

        keep = max(0, self.max_slots - 1)
        return blocks[:keep]

    def format_windows(self, additional_windows):
        if not self.core_window:
            self.initialize_core_window(datetime.now(timezone.utc))

        windows = [{
            "chargeCurrent": "60",
            "dischargeCurrent": "100",
            "chargeStartTime": self.core_window["start"].strftime("%H:%M"),
            "chargeEndTime": self.core_window["end"].strftime("%H:%M"),
            "dischargeStartTime": "00:00",
            "dischargeEndTime": "00:00",
        }]

        for w in additional_windows:
            windows.append({
                "chargeCurrent": "60",
                "dischargeCurrent": "100",
                "chargeStartTime": w["start"].strftime("%H:%M"),
                "chargeEndTime": w["end"].strftime("%H:%M"),
                "dischargeStartTime": "00:00",
                "dischargeEndTime": "00:00",
            })

        while len(windows) < self.max_slots:
            windows.append({
                "chargeCurrent": "60",
                "dischargeCurrent": "100",
                "chargeStartTime": "00:00",
                "chargeEndTime": "00:00",
                "dischargeStartTime": "00:00",
                "dischargeEndTime": "00:00",
            })

        return windows[:self.max_slots]


# -----------------------------
# SolisCloud I/O helpers
# -----------------------------
async def solis_post(session, config, url_path, body_dict, token=None):
    body = json.dumps(body_dict, separators=(",", ":"))
    headers = prepare_header(config, body, url_path)
    if token:
        headers["token"] = token
    return await session.post(BASE_URL + url_path, data=body, headers=headers)


async def resp_json(resp):
    text = await resp.text()
    return json.loads(_clean_json_text(text))


async def get_control_value(session, config, token, inverter_sn, cid, retries):
    for attempt in range(1, retries + 1):
        r = await solis_post(
            session,
            config,
            AT_READ_URL,
            {"inverterSn": str(inverter_sn), "cid": str(cid)},
            token=token,
        )
        if r.status != HTTPStatus.OK:
            log.warning("AT_READ cid=%s attempt %s/%s http=%s", cid, attempt, retries, r.status)
            await asyncio.sleep(0.2)
            continue

        try:
            data = await resp_json(r)
            if str(data.get("code")) != "0":
                await asyncio.sleep(0.2)
                continue
            payload = data.get("data") or []
            if payload and str(payload[0].get("code")) == "0":
                return payload[0]
        except Exception as e:
            log.warning("AT_READ cid=%s attempt %s/%s parse error: %s", cid, attempt, retries, e)

        await asyncio.sleep(0.2)

    return None


async def write_control(session, config, token, inverter_sn, cid, value, retries, delay, verify):
    last_text = None

    for attempt in range(1, retries + 1):
        r = await solis_post(
            session,
            config,
            CONTROL_URL,
            {"inverterSn": str(inverter_sn), "cid": str(cid), "value": str(value)},
            token=token,
        )
        try:
            last_text = await r.text()
        except Exception:
            last_text = None

        if r.status != HTTPStatus.OK:
            log.warning("CONTROL cid=%s attempt %s/%s http=%s", cid, attempt, retries, r.status)
            await asyncio.sleep(0.3)
            continue

        try:
            data = json.loads(_clean_json_text(last_text or ""))
            if str(data.get("code")) == "0":
                payload = data.get("data") or []
                if payload and str(payload[0].get("code")) == "0":
                    if verify:
                        await asyncio.sleep(delay)
                        rb = await get_control_value(session, config, token, inverter_sn, cid, retries)
                        log.debug("Readback cid=%s: %s", cid, rb)
                    return True
        except Exception as e:
            log.warning("CONTROL cid=%s attempt %s/%s parse error: %s", cid, attempt, retries, e)

        await asyncio.sleep(0.3)

    log.error("CONTROL cid=%s failed after %s attempts. Last response: %s", cid, retries, last_text)
    return False


# -----------------------------
# Service: same name as your original for drop-in replacement
# -----------------------------
@service
async def solis_smart_charging(config=None):
    if not config:
        log.error("No configuration provided")
        return

    if isinstance(config, str):
        config = json.loads(config)

    required_keys = ["secret", "key_id", "username", "password", "plantId", "dispatch_sensor"]
    
    # Check for missing keys (PyScript doesn't support list comprehensions in some contexts)
    missing = []
    for k in required_keys:
        if k not in config:
            missing.append(k)
    
    if missing:
        log.error("Missing required configuration keys: %s", ", ".join(missing))
        return

    # Configuration parameters
    diagnostics_only = bool(config.get("diagnostics_only", False))
    force_mode = str(config.get("force_mode", "auto")).lower()  # legacy | six_slot | auto

    max_slots = int(config.get("max_slots", 3))
    control_retries = int(config.get("control_retries", 3))
    control_delay = float(config.get("control_delay", 0.1))
    inter_write_delay = float(config.get("inter_write_delay", 0.25))
    verify_readback = str(config.get("verify_readback", "true")).lower() not in ("false", "0", "no")

    # Time sync configuration (v3.2.0 feature)
    sync_inverter_time = str(config.get("sync_inverter_time", "true")).lower() not in ("false", "0", "no")
    inverter_timezone = str(config.get("inverter_timezone", "UTC"))

    # Optional per-slot writes (disabled by default)
    set_charge_current = str(config.get("set_charge_current", "false")).lower() in ("true", "1", "yes")
    set_charge_soc = str(config.get("set_charge_soc", "false")).lower() in ("true", "1", "yes")
    charge_current_value = str(config.get("charge_current", "60"))
    charge_soc_value = str(config.get("charge_soc", "100"))

    log.info("=== Solis Smart Charging v4.0.0 ===")
    log.info("Configuration: diagnostics_only=%s, force_mode=%s, max_slots=%s", 
             diagnostics_only, force_mode, max_slots)
    log.info("Time sync: enabled=%s, timezone=%s", sync_inverter_time, inverter_timezone)

    session = async_get_clientsession(hass)

    # Login
    login_body = {"userInfo": str(config["username"]), "password": passwordEncode(str(config["password"]))}
    login_resp = await solis_post(session, config, LOGIN_URL, login_body)
    if login_resp.status != HTTPStatus.OK:
        log.error("Login failed with status %s", login_resp.status)
        return
    login_data = await resp_json(login_resp)
    token = login_data.get("csrfToken")
    if not token:
        log.error("Login succeeded but csrfToken missing: %s", login_data)
        return
    log.info("Login successful, token obtained")

    # Inverter list
    inv_list_resp = await solis_post(session, config, INVERTER_LIST_URL, {"stationId": str(config["plantId"])})
    if inv_list_resp.status != HTTPStatus.OK:
        log.error("inverterList failed status %s", inv_list_resp.status)
        return
    
    try:
        inv_list_data = await resp_json(inv_list_resp)
    except Exception as e:
        log.error("Failed to decode inverter list JSON: %s", e)
        return

    if not isinstance(inv_list_data, dict):
        log.error("Unexpected inverter data format: %s", type(inv_list_data))
        return
    
    if 'data' not in inv_list_data:
        log.error("No 'data' field in inverter response: %s", inv_list_data)
        return

    records = inv_list_data.get("data", {}).get("page", {}).get("records", []) or []
    if not records:
        log.error("No inverters returned from inverterList")
        return
    
    log.info("Found %s inverter(s) in plant", len(records))

    # Multi-inverter selection logic (v3.2.0 enhanced)
    cfg_sn = str(config.get("inverter_sn", "")).strip()
    cfg_id = str(config.get("inverter_id", "")).strip()
    
    # Handle undefined secrets (v3.2.0 feature)
    if cfg_sn.lower() in ("unknown", "unavailable", "none"):
        cfg_sn = ""
    if cfg_id.lower() in ("unknown", "unavailable", "none"):
        cfg_id = ""

    chosen = None
    if cfg_sn or cfg_id:
        log.info("Searching for configured inverter: SN=%s, ID=%s", cfg_sn or "not set", cfg_id or "not set")
        for r in records:
            if cfg_sn and str(r.get("sn")) == cfg_sn:
                chosen = r
                log.info("Matched inverter by SN: %s", cfg_sn)
                break
            if cfg_id and str(r.get("id")) == cfg_id:
                chosen = r
                log.info("Matched inverter by ID: %s", cfg_id)
                break
        
        if not chosen:
            log.error("Configured inverter_sn/inverter_id not found in inverterList")
            log.error("Available inverters:")
            for r in records:
                log.error("  - ID: %s, SN: %s, Name: %s, ProductModel: %s", 
                         r.get("id"), r.get("sn"), r.get("name"), r.get("productModel"))
            return
    else:
        # Auto-selection logic - filter for storage inverters (PyScript doesn't support list comprehensions in some contexts)
        storage_records = []
        for r in records:
            if str(r.get("productModel")) == "2":
                storage_records.append(r)
        
        if len(storage_records) == 1:
            chosen = storage_records[0]
            log.info("Auto-selected storage inverter (ProductModel=2)")
        elif len(storage_records) > 1:
            log.error("Multiple storage inverters found; please set inverter_sn or inverter_id")
            log.error("Available storage inverters:")
            for r in storage_records:
                log.error("  - ID: %s, SN: %s, Name: %s, ProductModel: %s",
                         r.get("id"), r.get("sn"), r.get("name"), r.get("productModel"))
            return
        elif len(records) == 1:
            chosen = records[0]
            log.info("Only one inverter found, using ID=%s, SN=%s, Name=%s",
                    chosen.get("id"), chosen.get("sn"), chosen.get("name"))
        else:
            log.error("Multiple inverters found but none identified as storage (ProductModel=2)")
            log.error("Available inverters:")
            for r in records:
                log.error("  - ID: %s, SN: %s, Name: %s, ProductModel: %s",
                         r.get("id"), r.get("sn"), r.get("name"), r.get("productModel"))
            return

    inverter_id = chosen.get("id")
    inverter_sn = chosen.get("sn")
    if not inverter_id or not inverter_sn:
        log.error("Chosen inverter missing id/sn: %s", chosen)
        return

    log.info("Using inverter - ID: %s, SN: %s, Name: %s, ProductModel: %s",
             inverter_id, inverter_sn, chosen.get("name"), chosen.get("productModel"))

    # ========================================
    # TIME SYNCHRONIZATION (v3.2.0 feature)
    # ========================================
    if sync_inverter_time:
        try:
            log.info("Syncing inverter time (CID 56)...")
            
            # Get timezone-aware current time
            try:
                from zoneinfo import ZoneInfo
                inverter_tz = ZoneInfo(inverter_timezone)
                log.debug("Using timezone: %s", inverter_timezone)
            except Exception as e:
                log.warning("Invalid timezone '%s': %s, falling back to UTC", inverter_timezone, e)
                inverter_tz = timezone.utc
            
            current_time = datetime.now(inverter_tz)
            time_value = current_time.strftime("%Y-%m-%d %H:%M:%S")
            
            time_sync_body = f'{{"inverterId":"{inverter_id}","cid":"56","value":"{time_value}"}}'
            time_headers = prepare_header(config, time_sync_body, CONTROL_URL)
            time_headers["token"] = token
            
            log.debug("Time sync payload: %s", time_sync_body)
            
            time_resp = await session.post(BASE_URL + CONTROL_URL, data=time_sync_body, headers=time_headers)
            
            if time_resp.status == HTTPStatus.OK:
                try:
                    time_data = await resp_json(time_resp)
                    if str(time_data.get("code")) == "0":
                        log.info("Successfully synced inverter time to %s (%s)", 
                                time_value, inverter_timezone)
                    else:
                        log.warning("Time sync returned code: %s, msg: %s", 
                                   time_data.get("code"), time_data.get("msg"))
                except Exception as e:
                    log.warning("Failed to parse time sync response: %s", e)
            else:
                log.warning("Time sync HTTP status: %s", time_resp.status)
                
        except Exception as e:
            log.error("Time sync failed: %s", e)
            # Don't abort - continue with schedule programming
    else:
        log.info("Time sync disabled by configuration")

    # Detect 6-slot firmware by HMI version (>= 4B00), unless forced
    hmi_version = None
    is_six_slot = False

    if force_mode == "six_slot":
        is_six_slot = True
        log.info("Six-slot mode FORCED by configuration")
    elif force_mode == "legacy":
        is_six_slot = False
        log.info("Legacy mode FORCED by configuration")
    else:
        log.info("Auto-detecting firmware mode via HMI version...")
        detail_resp = await solis_post(
            session,
            config,
            INVERTER_DETAIL_URL,
            {"id": str(inverter_id), "sn": str(inverter_sn)},
        )
        if detail_resp.status == HTTPStatus.OK:
            detail = await resp_json(detail_resp)
            payload = detail.get("data")

            if isinstance(payload, dict):
                hmi_version = payload.get("hmiVersionAll") or payload.get("hmi_version_all")
            elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
                hmi_version = payload[0].get("hmiVersionAll") or payload[0].get("hmi_version_all")

            if hmi_version:
                try:
                    hmi_int = int(str(hmi_version), 16)
                    is_six_slot = hmi_int >= int("4b00", 16)
                    log.info("HMI version detected: %s (decimal: %s, six_slot: %s)", 
                            hmi_version, hmi_int, is_six_slot)
                except Exception as e:
                    log.warning("Could not parse HMI version '%s': %s", hmi_version, e)
                    is_six_slot = False
            else:
                log.warning("HMI version not found in inverter detail")
        else:
            log.warning("inverterDetail failed http=%s; defaulting to legacy", detail_resp.status)

    # If six-slot detected, ensure max_slots at least 6
    if is_six_slot and max_slots < 6:
        log.info("Six-slot detected but max_slots=%s, increasing to 6", max_slots)
        max_slots = 6

    log.info("Firmware detection complete: HMI=%s, six_slot=%s, force_mode=%s, final_max_slots=%s",
             hmi_version, is_six_slot, force_mode, max_slots)

    # Process dispatch windows
    processor = WindowProcessor(max_slots=max_slots)
    dispatch_sensor = str(config["dispatch_sensor"])

    try:
        dispatches = state.getattr(dispatch_sensor)
        if dispatches and "planned_dispatches" in dispatches:
            log.info("Processing %s planned dispatches from %s", 
                    len(dispatches["planned_dispatches"]), dispatch_sensor)
            processor.normalize_dispatches(dispatches["planned_dispatches"])
            processor.process_core_hours()
            additional = processor.select_additional_windows()
            windows = processor.format_windows(additional)
            
            # Count non-empty windows (PyScript doesn't support list comprehensions in some contexts)
            non_empty_count = 0
            for w in windows:
                if w["chargeStartTime"] != "00:00":
                    non_empty_count += 1
            
            log.info("Calculated %s charging windows (core + %s additional)", 
                    non_empty_count, len(additional))
        else:
            log.warning("No planned dispatches found, using core window only")
            windows = processor.format_windows([])
    except Exception as e:
        log.error("Error processing dispatch windows: %s", e)
        windows = processor.format_windows([])

    # Log calculated windows for debugging
    for i, w in enumerate(windows):
        if w["chargeStartTime"] != "00:00" or w["chargeEndTime"] != "00:00":
            log.debug("Window %s: charge %s-%s, discharge %s-%s", 
                     i + 1, w["chargeStartTime"], w["chargeEndTime"],
                     w["dischargeStartTime"], w["dischargeEndTime"])

    # Skip update if unchanged (length-aware; compares key fields)
    current_state = hass.states.get("sensor.solis_charge_schedule")
    if current_state and current_state.attributes.get("charging_windows"):
        existing = current_state.attributes.get("charging_windows")
        same = isinstance(existing, list) and len(existing) == len(windows)
        if same:
            for n, o in zip(windows, existing):
                for k in ("chargeStartTime", "chargeEndTime", "dischargeStartTime", "dischargeEndTime",
                          "chargeCurrent", "dischargeCurrent"):
                    if str(n.get(k)) != str(o.get(k)):
                        same = False
                        break
                if not same:
                    break
        if same:
            log.info("Charging windows unchanged - skipping API update")
            return "Windows unchanged - no update needed"

    # Write schedule
    if is_six_slot:
        # Build 6 slot values as "HH:MM-HH:MM" for charge schedule
        log.info("=== Six-Slot Mode: Building CID operations ===")
        slot_values = []
        for i in range(6):
            if i < len(windows):
                s = windows[i]["chargeStartTime"]
                e = windows[i]["chargeEndTime"]
            else:
                s = "00:00"
                e = "00:00"
            slot_values.append(f"{s}-{e}")
            log.debug("Slot %s time: %s", i + 1, slot_values[i])

        ops = []
        for i, cid in enumerate(CHARGE_TIME_CIDS):
            ops.append(("charge_time", i + 1, cid, slot_values[i]))

        # Optional: write per-slot charge current / SOC
        if set_charge_current:
            log.info("set_charge_current enabled, adding current operations")
            for i, cid in enumerate(CHARGE_CURRENT_CIDS):
                ops.append(("charge_current", i + 1, cid, charge_current_value))

        if set_charge_soc:
            log.info("set_charge_soc enabled, adding SOC operations")
            for i, cid in enumerate(CHARGE_SOC_CIDS):
                ops.append(("charge_soc", i + 1, cid, charge_soc_value))

        log.info("Total operations to execute: %s", len(ops))
        for kind, slot, cid, val in ops:
            log.info("  Operation: %s slot_%s CID=%s value='%s'", kind, slot, cid, val)

        if diagnostics_only:
            log.warning("=== DIAGNOSTICS MODE: Not writing to inverter ===")
            
            # Build schedule text (PyScript doesn't support generator expressions)
            schedule_parts = []
            for w in windows:
                if w["chargeStartTime"] != "00:00" or w["chargeEndTime"] != "00:00":
                    schedule_parts.append(f"{w['chargeStartTime']}-{w['chargeEndTime']}")
            schedule_text = ", ".join(schedule_parts)
            
            # Build operations list (PyScript doesn't support list comprehensions in some contexts)
            operations_list = []
            for k, s, c, v in ops:
                operations_list.append({"type": k, "slot": s, "cid": c, "value": v})
            
            hass.states.async_set(
                "sensor.solis_charge_schedule",
                schedule_text if schedule_text else "diagnostics_only",
                {
                    "charging_windows": windows,
                    "mode": "six_slot",
                    "hmi_version": hmi_version,
                    "operations": operations_list,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "last_api_response": "not_sent_diagnostics_mode",
                    "time_sync": "enabled" if sync_inverter_time else "disabled",
                    "timezone": inverter_timezone,
                },
            )
            log.info("Diagnostics complete - check sensor.solis_charge_schedule attributes")
            return {"mode": "six_slot_diagnostics", "operations": ops}

        # Execute writes
        log.info("=== Executing six-slot control writes ===")
        ok = True
        failed_ops = []
        
        for kind, slot, cid, val in ops:
            log.info("Writing: %s slot_%s CID=%s value='%s'", kind, slot, cid, val)
            success = await write_control(
                session=session,
                config=config,
                token=token,
                inverter_sn=inverter_sn,
                cid=cid,
                value=val,
                retries=control_retries,
                delay=control_delay,
                verify=verify_readback,
            )
            if not success:
                ok = False
                failed_ops.append({"type": kind, "slot": slot, "cid": cid, "value": val})
                log.error("FAILED: %s slot_%s CID=%s", kind, slot, cid)
            else:
                log.info("SUCCESS: %s slot_%s CID=%s", kind, slot, cid)
            
            await asyncio.sleep(inter_write_delay)

        if failed_ops:
            log.error("=== Six-slot update completed with %s failures ===", len(failed_ops))
            for op in failed_ops:
                log.error("  Failed: %s slot_%s CID=%s value='%s'", 
                         op["type"], op["slot"], op["cid"], op["value"])
        else:
            log.info("=== Six-slot update completed successfully ===")

        # Build schedule text (PyScript doesn't support generator expressions)
        schedule_parts = []
        for w in windows:
            if w["chargeStartTime"] != "00:00" or w["chargeEndTime"] != "00:00":
                schedule_parts.append(f"{w['chargeStartTime']}-{w['chargeEndTime']}")
        schedule_text = ", ".join(schedule_parts)

        hass.states.async_set(
            "sensor.solis_charge_schedule",
            schedule_text,
            {
                "charging_windows": windows,
                "mode": "six_slot",
                "hmi_version": hmi_version,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "schedule_source": "octopus_dispatch",
                "last_api_response": "success" if ok else "partial_failure",
                "failed_operations": failed_ops if failed_ops else None,
                "time_sync": "enabled" if sync_inverter_time else "disabled",
                "timezone": inverter_timezone,
            },
        )

        return "six_slot update complete" if ok else f"six_slot update had {len(failed_ops)} failures"

    # Legacy: send CID103 (always 3 windows)
    log.info("=== Legacy Mode: Building CID 103 payload ===")
    legacy_windows = windows[:3]
    control_data = legacy_control_body(inverter_id, legacy_windows)
    control_headers = prepare_header(config, control_data, CONTROL_URL)
    control_headers["token"] = token

    log.info("CID 103 payload: %s", control_data)

    if diagnostics_only:
        log.warning("=== DIAGNOSTICS MODE: Not writing to inverter ===")
        
        # Build schedule text (PyScript doesn't support generator expressions)
        schedule_parts = []
        for w in legacy_windows:
            if w["chargeStartTime"] != "00:00" or w["chargeEndTime"] != "00:00":
                schedule_parts.append(f"{w['chargeStartTime']}-{w['chargeEndTime']}")
        schedule_text = ", ".join(schedule_parts)
        
        hass.states.async_set(
            "sensor.solis_charge_schedule",
            schedule_text if schedule_text else "diagnostics_only",
            {
                "charging_windows": legacy_windows,
                "mode": "legacy",
                "hmi_version": hmi_version,
                "payload": control_data,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "schedule_source": "octopus_dispatch",
                "last_api_response": "not_sent_diagnostics_mode",
                "time_sync": "enabled" if sync_inverter_time else "disabled",
                "timezone": inverter_timezone,
            },
        )
        log.info("Diagnostics complete - check sensor.solis_charge_schedule attributes")
        return {"mode": "legacy_diagnostics", "payload": control_data}

    log.info("=== Executing legacy CID 103 write ===")
    resp = await session.post(BASE_URL + CONTROL_URL, data=control_data, headers=control_headers)
    resp_text = await resp.text()
    
    log.info("Solis API response status: %s", resp.status)
    log.debug("Solis API response body: %s", resp_text)

    # Build schedule text (PyScript doesn't support generator expressions)
    schedule_parts = []
    for w in legacy_windows:
        if w["chargeStartTime"] != "00:00" or w["chargeEndTime"] != "00:00":
            schedule_parts.append(f"{w['chargeStartTime']}-{w['chargeEndTime']}")
    schedule_text = ", ".join(schedule_parts)

    hass.states.async_set(
        "sensor.solis_charge_schedule",
        schedule_text,
        {
            "charging_windows": legacy_windows,
            "mode": "legacy",
            "hmi_version": hmi_version,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "schedule_source": "octopus_dispatch",
            "last_api_response": "sent",
            "time_sync": "enabled" if sync_inverter_time else "disabled",
            "timezone": inverter_timezone,
        },
    )

    log.info("=== Legacy update complete ===")
    return resp_text
