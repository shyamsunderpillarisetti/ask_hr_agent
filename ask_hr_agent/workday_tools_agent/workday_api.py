import json
import os
import time
import urllib.parse
import requests
from urllib.parse import urlparse, parse_qs
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.common.exceptions import WebDriverException


def load_config(config_path: str) -> Dict[str, str]:
    """Load Workday config, allowing env vars to override file values."""
    config: Dict[str, str] = {}

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}") from e
        except IOError as e:
            raise IOError(f"Error reading config file: {e}") from e

    # Overlay environment variables (prefer WORKDAY_* prefix, then bare)
    keys = [
        "auth_url",
        "token_url",
        "base_url",
        "tenant",
        "client_id",
        "client_secret",
        "redirect_uri",
        "response_type",
        "grant_type",
        "scope",
    ]
    for key in keys:
        env_val = os.getenv(f"WORKDAY_{key.upper()}") or os.getenv(key.upper())
        if env_val:
            config[key] = env_val

    return config


def get_auth_code(config_path: str = None, auth_url: str = None, client_id: str = None, 
                  redirect_uri: str = None, scope: str = None, response_type: str = "code") -> Optional[str]:
    """Get OAuth authorization code using automated browser (Chrome/Edge).

    Env toggles:
    - ASKHR_BROWSER: "chrome" (default) or "edge"
    - ASKHR_HEADLESS: "true" (default) or "false" to show the browser
    - ASKHR_SELENIUM_TIMEOUT: seconds (default 300)
    """
    config = {}
    if config_path:
        config = load_config(config_path)
    
    auth_url = auth_url or config.get('auth_url')
    client_id = client_id or config.get('client_id')
    redirect_uri = redirect_uri or config.get('redirect_uri')
    scope = scope or config.get('scope')
    response_type = response_type or config.get('response_type') or 'code'
    
    if not all([auth_url, client_id, redirect_uri, scope]):
        raise ValueError("Missing required parameters: auth_url, client_id, redirect_uri, scope")
    
    params = {
        'response_type': response_type,
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': scope
    }
    
    full_auth_url = f"{auth_url}?{urllib.parse.urlencode(params)}"
    
    browser_pref = os.getenv('ASKHR_BROWSER', 'chrome').lower()
    headless = os.getenv('ASKHR_HEADLESS', 'true').lower() in ('1','true','yes')
    wait_seconds = int(os.getenv('ASKHR_SELENIUM_TIMEOUT', '300'))

    verbose = os.getenv('ASKHR_SELENIUM_DEBUG', 'false').lower() in ('1','true','yes')

    def _apply_common_opts(opts):
        opts.add_argument('--ignore-certificate-errors')
        opts.add_argument('--ignore-ssl-errors')
        opts.add_argument('--allow-insecure-localhost')
        opts.add_argument('--disable-web-security')
        opts.add_argument('--disable-features=IsolateOrigins,site-per-process')
        opts.add_argument('--disable-gpu')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--window-size=1400,900')
        opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        if headless:
            opts.add_argument('--headless=new')
        return opts
    
    driver = None
    try:
        driver = None
        launch_errors = []

        # Try preferred browser first, then fallback
        for choice in ([browser_pref] if browser_pref in ('chrome','edge') else ['chrome','edge']):
            try:
                if choice == 'edge':
                    edge_opts = _apply_common_opts(EdgeOptions())
                    driver = webdriver.Edge(options=edge_opts)
                else:
                    chrome_opts = _apply_common_opts(ChromeOptions())
                    driver = webdriver.Chrome(options=chrome_opts)
                break
            except Exception as e:
                launch_errors.append(f"{choice}: {e}")
                driver = None
                continue

        if driver is None:
            raise RuntimeError(f"Failed to start browser. Errors: {launch_errors}")

        driver.get(full_auth_url)

        max_wait_time = wait_seconds
        start_time = time.time()
        last_url = None

        log_every = 5
        next_log = time.time() + log_every

        while time.time() - start_time < max_wait_time:
            try:
                current_url = driver.current_url
                last_url = current_url
            except Exception as e:
                if verbose:
                    print(f"[Workday][Selenium] current_url error: {e}")
                time.sleep(0.5)
                continue

            redirect_base = redirect_uri.split('?')[0] if redirect_uri else ''

            if (redirect_base and redirect_base in current_url) or 'localhost' in current_url:
                parsed_url = urlparse(current_url)
                query_params = parse_qs(parsed_url.query)

                if parsed_url.fragment:
                    fragment_params = parse_qs(parsed_url.fragment)
                    query_params.update(fragment_params)

                if 'code' in query_params:
                    auth_code = query_params['code'][0]
                    if verbose:
                        print(f"[Workday][Selenium] Auth code captured")
                    return auth_code
                elif 'error' in query_params:
                    error = query_params['error'][0]
                    raise ValueError(f"Authorization error: {error}")

            time.sleep(0.5)

            if verbose and time.time() >= next_log:
                print(f"[Workday][Selenium] Still waiting; current_url={current_url}")
                next_log = time.time() + log_every

        raise TimeoutError(f"Authorization not completed within {max_wait_time} seconds. Last URL: {last_url}")
        
        raise TimeoutError("Authorization not completed within 5 minutes")
        
    except WebDriverException as e:
        raise WebDriverException(f"Browser error: {e}. Ensure Chrome or Edge is installed.") from e
    except (ValueError, TimeoutError):
        raise
    except Exception as e:
        raise RuntimeError(f"Unexpected error during authorization: {e}") from e
    finally:
        if driver:
            driver.quit()



def get_access_token(config_path: str = None, code: str = None, token_url: str = None, 
                     grant_type: str = None, client_id: str = None, client_secret: str = None, 
                     redirect_uri: str = None, scope: str = None) -> Dict[str, Any]:
    """Exchange authorization code for access token."""
    config = {}
    if config_path:
        config = load_config(config_path)
    
    if not code:
        raise ValueError("Authorization code is required")
    
    token_url = token_url or config.get('token_url')
    grant_type = grant_type or config.get('grant_type') or 'authorization_code'
    client_id = client_id or config.get('client_id')
    client_secret = client_secret or config.get('client_secret')
    redirect_uri = redirect_uri or config.get('redirect_uri')
    scope = scope or config.get('scope')
    
    if not all([token_url, client_id, client_secret, redirect_uri]):
        raise ValueError("Missing required parameters: token_url, client_id, client_secret, redirect_uri")
    
    data = {
        'grant_type': grant_type,
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri
    }
    
    if scope:
        data['scope'] = scope
    
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        response = requests.post(token_url, data=data, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            raise ValueError(f"Token request failed with status {response.status_code}: {response.text}")
    except requests.exceptions.Timeout as e:
        raise TimeoutError(f"Token request timed out: {e}") from e
    except requests.exceptions.RequestException as e:
        raise requests.RequestException(f"Request error: {e}") from e


def extract_workday_id(user_data: Dict[str, Any]) -> Optional[str]:
    """Extract Workday ID from user data."""
    if not isinstance(user_data, dict):
        return None
    for key in ('id', 'workerId', 'worker_id', 'workdayId', 'workday_id'):
        if key in user_data:
            return user_data[key]
    return None


def get_workday_data_merged(base_url: str, tenant: str, access_token: str, 
                           endpoints: List[str]) -> Dict[str, Any]:
    """Fetch data from multiple endpoints and merge."""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    merged_data = {}
    errors = {}
    
    for url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                merged_data.update(response.json())
            else:
                errors[url] = f"Status {response.status_code}"
        except requests.exceptions.Timeout:
            errors[url] = "Request timeout"
        except requests.exceptions.RequestException as e:
            errors[url] = str(e)
    
    if not merged_data:
        detail = "; ".join([f"{url} -> {err}" for url, err in errors.items()])
        raise ValueError(f"Failed to get data from any endpoint. Attempts: {detail}")
    
    return merged_data



def complete_oauth_flow(config_path: str) -> Dict[str, Any]:
    """Complete OAuth flow."""
    config = load_config(config_path)
    print("[Workday] Starting OAuth flow...")
    auth_code = get_auth_code(config_path=config_path)
    print("[Workday] Auth code obtained")
    token_data = get_access_token(config_path=config_path, code=auth_code)
    print("[Workday] Access token retrieved")
    access_token = token_data['access_token']
    
    base_url = config.get('base_url')
    tenant = config.get('tenant')

    if not base_url or not tenant:
        token_url = config.get('token_url', '')
        if '/ccx/' in token_url:
            base_url = base_url or token_url.split('/ccx')[0]
            parts = token_url.split('/')
            tenant = tenant or (parts[-2] if len(parts) >= 2 else None)

    if not base_url or not tenant:
        raise ValueError("Missing base_url or tenant in config; please set them explicitly")

    primary_endpoints = [
        f"{base_url}/api/staffing/v7/{tenant}/workers/me",
        f"{base_url}/api/staffing/v7/{tenant}/workers/me/serviceDates",
        f"{base_url}/api/person/v4/{tenant}/people/me/legalName",
    ]

    print("[Workday] Fetching primary user endpoints...")
    user_data = get_workday_data_merged(base_url, tenant, access_token, primary_endpoints)
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    try:
        legal_name_response = requests.get(f"{base_url}/api/person/v4/{tenant}/people/me/legalName", headers=headers, timeout=30)
        if legal_name_response.status_code == 200:
            user_data['legalName'] = legal_name_response.json()
    except Exception:
        pass
    
    try:
        service_dates_response = requests.get(f"{base_url}/api/staffing/v7/{tenant}/workers/me/serviceDates", headers=headers, timeout=30)
        if service_dates_response.status_code == 200:
            user_data['serviceDates'] = service_dates_response.json()
    except Exception:
        pass
    
    workday_id = extract_workday_id(user_data)
    print(f"[Workday] Workday ID: {workday_id}")
    
    if workday_id:
        absence_endpoints = [
            f"{base_url}/api/absenceManagement/v3/{tenant}/balances?worker={workday_id}",
        ]
        try:
            absence_data = get_workday_data_merged(base_url, tenant, access_token, absence_endpoints)
            user_data['absence_balances'] = absence_data
        except ValueError:
            pass

        eligible_types_endpoint = f"{base_url}/api/absenceManagement/v3/{tenant}/workers/{workday_id}/eligibleAbsenceTypes"
        try:
            eligible_data = get_workday_data_merged(base_url, tenant, access_token, [eligible_types_endpoint])
            user_data['eligible_absence_types'] = eligible_data
        except ValueError:
            pass
    
    return {
        'auth_code': auth_code,
        'access_token': access_token,
        'refresh_token': token_data.get('refresh_token'),
        '_token_expires_in': token_data.get('expires_in', 3600),
        'user_data': user_data,
        'workday_id': workday_id,
        'debug': {
            'primary_endpoints': primary_endpoints,
            'base_url': base_url,
            'tenant': tenant,
            'absence_endpoints': {
                'balances': f"{base_url}/api/absenceManagement/v3/{tenant}/balances?worker={workday_id}" if workday_id else None,
                'eligible_types': f"{base_url}/api/absenceManagement/v3/{tenant}/workers/{workday_id}/eligibleAbsenceTypes" if workday_id else None,
                'valid_dates': f"{base_url}/api/absenceManagement/v3/{tenant}/workers/{workday_id}/validTimeOffDates?timeOff={{type_id}}&date={{date}}" if workday_id else None,
                'request_time_off': f"{base_url}/api/absenceManagement/v3/{tenant}/workers/{workday_id}/requestTimeOff" if workday_id else None,
            }
        }
    }


def get_valid_time_off_dates(base_url: str, tenant: str, access_token: str, workday_id: str, 
                            time_off_type_id: str, dates: List[str]) -> Dict[str, Any]:
    """Check if dates are valid for time off request."""
    date_params = "&".join([f"date={date}" for date in dates])
    endpoint = f"{base_url}/api/absenceManagement/v3/{tenant}/workers/{workday_id}/validTimeOffDates?timeOff={time_off_type_id}&{date_params}"
    
    return get_workday_data_merged(base_url, tenant, access_token, [endpoint])


def submit_time_off_request(base_url: str, tenant: str, access_token: str, workday_id: str, 
                           time_off_type_id: str, start_date: str, end_date: str, 
                           quantity_per_day: float, comment: Optional[str] = None) -> Dict[str, Any]:
    """Submit a time off request."""
    endpoint = f"{base_url}/api/absenceManagement/v3/{tenant}/workers/{workday_id}/requestTimeOff"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    days = []
    while current <= end_dt:
        day_entry = {
            "timeOffType": {
                "id": time_off_type_id
            },
            "date": current.strftime("%Y-%m-%d"),
            "dailyQuantity": quantity_per_day
        }
        if comment:
            day_entry["comment"] = comment
        days.append(day_entry)
        current += timedelta(days=1)
    
    payload = {
        "days": days,
        "businessProcessParameters": {
            "action": {
                "id": "d9e4223e446c11de98360015c5e6daf6"
            }
        }
    }
    
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            return {
                "success": True,
                "data": response.json(),
                "message": "Time off request submitted successfully"
            }
        else:
            return {
                "success": False,
                "status_code": response.status_code,
                "error": response.text,
                "message": f"Failed to submit request. Status: {response.status_code}"
            }
            
    except requests.exceptions.Timeout as e:
        return {
            "success": False,
            "error": "Request timeout",
            "message": f"Request timed out: {e}"
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Request error: {e}"
        }
