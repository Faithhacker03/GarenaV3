# --- START OF FILE set_cookie.py ---
# This module provides a "Numbered Set" of cookies by either using a
# fixed number specified by the user or by cycling through the full list.

import threading
from colorama import Fore, Style

# --- Global State for this Module ---
_FIXED_NUMBER = None  # Stores the user-specified, 0-based index
_CYCLING_INDEX = -1   # Used only if no fixed number is set
_lock = threading.Lock()

# --- Load Cookies from Configuration ---
try:
    from cookie_config import COOKIE_POOL
    if not isinstance(COOKIE_POOL, list) or not COOKIE_POOL:
        print(f"{Fore.RED}[Error: Numbered Set] COOKIE_POOL in cookie_config.py is empty or malformed.{Style.RESET_ALL}")
        COOKIE_POOL = [{"datadome": "error_pool_is_malformed"}]
except ImportError:
    print(f"{Fore.RED}[Error: Numbered Set] cookie_config.py was not found. This module is disabled.{Style.RESET_ALL}")
    COOKIE_POOL = [{"datadome": "error_cookie_config_not_found"}]


def set_fixed_number(number):
    """
    Sets the fixed cookie number to use for the entire session.
    This function is called once by app.py when a check starts.
    
    Args:
        number (int): The 1-based number from the user input.
    """
    global _FIXED_NUMBER
    with _lock:
        # User input is 1-based, list index is 0-based
        _FIXED_NUMBER = number - 1


def get_cookies():
    """
    Provides a cookie from the COOKIE_POOL.
    
    - If a fixed number has been set, it will ALWAYS return that specific cookie.
    - If no fixed number is set, it will cycle through the list sequentially.
    """
    global _CYCLING_INDEX

    selected_index = -1

    with _lock:
        if _FIXED_NUMBER is not None:
            # A fixed number was provided, use it for every call.
            selected_index = _FIXED_NUMBER
        else:
            # No fixed number, cycle through the list.
            _CYCLING_INDEX = (_CYCLING_INDEX + 1) % len(COOKIE_POOL)
            selected_index = _CYCLING_INDEX

    # --- Error Handling & Cookie Selection ---
    if selected_index >= len(COOKIE_POOL):
        # This happens if the user enters a number larger than the list size.
        print(f"{Fore.YELLOW}[Warning: Numbered Set] Number {selected_index + 1} is out of bounds. The list only has {len(COOKIE_POOL)} cookies. Using the last available one instead.{Style.RESET_ALL}")
        selected_index = len(COOKIE_POOL) - 1
    elif selected_index < 0:
        # This is a safeguard in case of an unexpected issue.
        print(f"{Fore.RED}[Error: Numbered Set] Invalid index {selected_index}. Using first cookie.{Style.RESET_ALL}")
        selected_index = 0
        
    # Get the cookie object and the datadome value
    selected_cookie_object = COOKIE_POOL[selected_index]
    datadome_value = selected_cookie_object.get("datadome", "VALUE_NOT_FOUND_IN_DICT")

    # Log which cookie is being used for transparency
    mode = "FIXED" if _FIXED_NUMBER is not None else "Cycling"
    print(f"{Fore.CYAN}[Numbered Set] Using cookie #{selected_index + 1} (Mode: {mode}): ...{datadome_value[-12:]}{Style.RESET_ALL}")

    # Construct and return the full cookie dictionary required by the application
    return {
        "datadome": datadome_value,
        "token_session": "token_from_set_cookie_module",
        "sso_key": "sso_from_set_cookie_module",
    }

# --- END OF FILE set_cookie.py ---