#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
Nemlig.com CLI - A command-line interface for nemlig.com grocery shopping.

Usage:
    python nemlig_cli.py search "cocio"
    python nemlig_cli.py details PRODUCT_ID
    python nemlig_cli.py basket
    python nemlig_cli.py add PRODUCT_ID [--quantity N]
    python nemlig_cli.py history [ORDER_ID]

The username can be provided via config, NEMLIG_USER, or -u.
Passwords are prompted without echo and are never loaded from disk or arguments.
"""

import argparse
import getpass
from importlib import metadata
import itertools
import json
import os
import re
try:
    import readline
except ImportError:
    readline = None  # Optional tab completion; unavailable on standard Windows Python.
import sys
import subprocess
import threading
import time
import tomllib
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path

import argcomplete
import requests

# Optional: Anthropic for AI meal planning
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Optional: Google Sheets for form responses
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GSHEETS_AVAILABLE = True
except ImportError:
    GSHEETS_AVAILABLE = False

GSHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Optional: Barcode scanning and image recognition
try:
    import cv2
    from pyzbar import pyzbar
    from PIL import Image
    import openfoodfacts
    SCANNER_AVAILABLE = True
except ImportError:
    SCANNER_AVAILABLE = False

# Optional: Raspberry Pi AI Camera
try:
    from picamera2 import Picamera2
    from picamera2.devices.imx500 import IMX500
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False


# Interactive mode commands for tab completion
COMMANDS = ["search", "details", "list", "basket", "help", "quit", "exit"]
LIST_SUBCOMMANDS = ["add", "remove", "clear", "budget", "sync"]


class NemligCompleter:
    """Tab completer for interactive mode."""

    def __init__(self):
        self.matches = []

    def complete(self, text: str, state: int) -> str | None:
        if state == 0:
            line = readline.get_line_buffer()
            self.matches = self._get_matches(line, text)
        return self.matches[state] if state < len(self.matches) else None

    def _get_matches(self, line: str, text: str) -> list[str]:
        parts = line.split()

        # First word - complete commands
        if not parts or (len(parts) == 1 and not line.endswith(" ")):
            return [cmd + " " for cmd in COMMANDS if cmd.startswith(text)]

        # After "list" - complete subcommands
        if parts[0] == "list":
            if len(parts) == 1 and line.endswith(" "):
                return [sub + " " for sub in LIST_SUBCOMMANDS]
            elif len(parts) == 2 and not line.endswith(" "):
                return [sub + " " for sub in LIST_SUBCOMMANDS if sub.startswith(text)]

        return []


class Spinner:
    """Animated spinner for long-running operations.

    Renders to stderr, and only when stderr is an interactive terminal. Writing
    to stderr keeps stdout clean for redirection, so progress is still visible
    during `nemlig search cocio > results.txt`. Skipping the animation when
    stderr is not a tty keeps escape sequences out of log files, CI output, and
    programmatic consumers that import this module as a library.

    When inactive no thread is started at all, so nothing can be left spinning
    if stop() is missed.
    """

    def __init__(self, message: str = "Loading", stream=None):
        self.message = message
        self.stream = stream if stream is not None else sys.stderr
        self.running = False
        self.thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    @property
    def enabled(self) -> bool:
        """Whether to animate. False when output is piped or captured."""
        try:
            return self.stream.isatty()
        except (AttributeError, ValueError):
            # No isatty (a plain buffer), or the stream is already closed.
            return False

    def _spin(self):
        for frame in itertools.cycle(self.frames):
            if not self.running:
                break
            print(f"\r  {frame} {self.message}...", end="", flush=True, file=self.stream)
            time.sleep(0.08)

    def start(self):
        if not self.enabled:
            return
        self.running = True
        # Daemon, so a spinner that is never stopped cannot keep the process
        # alive on its own.
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self, final_message: str = None):
        self.running = False
        if self.thread:
            self.thread.join()
            self.thread = None
        if not self.enabled:
            return
        # Clear the line
        print(f"\r{' ' * (len(self.message) + 10)}\r", end="", file=self.stream)
        if final_message:
            print(f"  ✓ {final_message}", file=self.stream)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


def development_version() -> str:
    """Use the project version and identify the exact local Git revision."""
    root = Path(__file__).resolve().parent
    try:
        with (root / "pyproject.toml").open("rb") as source:
            version = tomllib.load(source)["project"]["version"]
    except FileNotFoundError:
        # A wheel's module directory need not contain the source pyproject.
        return f"{metadata.version('nemlig-cli')}+unknown"
    # This caller owns the child: check_output waits/reaps it and kills/reaps it
    # on timeout. Abrupt parent death can briefly orphan this finite read-only
    # Git query; it finishes independently, with no retry or persistent effects.
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root,
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return f"{version}+unknown"
    return f"{version}+g{revision}"


VERSION = development_version()

LOGO = r"""
    ░░░    ░░░  ░░░░░░░  ░░░    ░░░  ░░░      ░░░   ░░░░░░░
    ░░░░   ░░░  ░░░      ░░░░  ░░░░  ░░░      ░░░  ░░░
    ░░░░░  ░░░  ░░░░░░   ░░░░░░░░░░  ░░░      ░░░  ░░░  ░░░░
    ░░░ ░░ ░░░  ░░░      ░░░ ░░ ░░░  ░░░      ░░░  ░░░   ░░░
    ░░░  ░░░░░  ░░░░░░░  ░░░    ░░░  ░░░░░░░  ░░░   ░░░░░░░

    ─────────────────────────────────────────────────────

       ██████╗ ██╗      ██╗    grocery shopping from your terminal
      ██╔════╝ ██║      ██║    ─────────────────────────────────────
      ██║      ██║      ██║    search, list, sync - all from the cli
      ██║      ██║      ██║
       ██████╗ ███████╗ ██║    v{version}
       ╚═════╝ ╚══════╝ ╚═╝
"""


def print_welcome(username: str) -> None:
    """Print welcome banner with logo after login."""
    print(LOGO.format(version=VERSION))
    print(f"    Logged in as: {username}")
    print("    ─────────────────────────────────────────────────────\n")


def print_startup_logo() -> None:
    """Print startup logo before login."""
    print(LOGO.format(version=VERSION))
    print("    ─────────────────────────────────────────────────────\n")

CONFIG_FILE = Path.home() / ".config" / "nemlig" / "login.json"


def load_config_credentials() -> dict:
    """
    Load credentials from ~/.config/nemlig/login.json if it exists.

    Expected format: {"username": "user@example.com"}

    Returns non-password settings, or an empty dict if the file doesn't exist.

    Raises:
        ValueError: If file exists but contains invalid JSON or wrong structure.
        OSError: If file exists but cannot be read.
    """
    if not CONFIG_FILE.exists():
        return {}

    with open(CONFIG_FILE, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(
            f"Config file {CONFIG_FILE} must contain a JSON object, got {type(data).__name__}"
        )

    if "password" in data:
        raise ValueError(
            "Remove the password field from login.json; passwords are now prompted securely."
        )

    return {
        "username": data.get("username"),
        "anthropic_api_key": data.get("anthropic_api_key"),
    }


def read_password() -> str:
    """Fail closed instead of falling back to visible or piped password input."""
    if not sys.stdin.isatty():
        raise ValueError("Password entry requires an interactive terminal.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            password = getpass.getpass("Nemlig.com password: ")
        except getpass.GetPassWarning:
            raise ValueError("Hidden password entry is unavailable in this terminal.") from None
    if not password:
        raise ValueError("Password must not be empty.")
    return password


def get_anthropic_api_key() -> str | None:
    """Get Anthropic API key from config file or environment."""
    # Try environment first
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    # Try config file
    try:
        creds = load_config_credentials()
        return creds.get("anthropic_api_key")
    except Exception:
        return None


# Google Sheets config
GSHEETS_CONFIG_FILE = Path.home() / ".config" / "nemlig" / "gsheets.json"
GSHEETS_TOKEN_FILE = Path.home() / ".config" / "nemlig" / "gsheets_token.json"
GSHEETS_CREDENTIALS_FILE = Path.home() / ".config" / "nemlig" / "credentials.json"


def load_gsheets_config() -> dict:
    """Load Google Sheets configuration."""
    if GSHEETS_CONFIG_FILE.exists():
        return json.loads(GSHEETS_CONFIG_FILE.read_text())
    return {}


def save_gsheets_config(config: dict) -> None:
    """Save Google Sheets configuration."""
    GSHEETS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    GSHEETS_CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_gsheets_service():
    """Get authenticated Google Sheets service."""
    if not GSHEETS_AVAILABLE:
        raise RuntimeError("Google Sheets libraries not installed. Run: uv add google-api-python-client google-auth-oauthlib")

    creds = None

    # Load existing token
    if GSHEETS_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GSHEETS_TOKEN_FILE), GSHEETS_SCOPES)

    # Refresh or get new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GSHEETS_CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found at {GSHEETS_CREDENTIALS_FILE}\n"
                    "Download from Google Cloud Console: APIs & Services > Credentials > OAuth 2.0 Client IDs"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(GSHEETS_CREDENTIALS_FILE), GSHEETS_SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token for next time
        GSHEETS_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        GSHEETS_TOKEN_FILE.write_text(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def fetch_sheet_data(spreadsheet_id: str, range_name: str = "A:Z") -> list[list[str]]:
    """Fetch data from a Google Sheet."""
    service = get_gsheets_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    return result.get("values", [])


LIST_FILE = Path.home() / ".config" / "nemlig" / "grocery_list.json"


def load_grocery_list() -> dict:
    """Load grocery list from config file."""
    if LIST_FILE.exists():
        return json.loads(LIST_FILE.read_text())
    return {"budget": 500.0, "items": []}


def save_grocery_list(data: dict) -> None:
    """Save grocery list to config file."""
    LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIST_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# Fridge inventory storage
FRIDGE_FILE = Path.home() / ".config" / "nemlig" / "fridge_inventory.json"


def load_fridge_inventory() -> dict:
    """Load fridge inventory from config file."""
    if FRIDGE_FILE.exists():
        return json.loads(FRIDGE_FILE.read_text())
    return {"items": [], "last_scan": None}


def save_fridge_inventory(data: dict) -> None:
    """Save fridge inventory to config file."""
    FRIDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    FRIDGE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# Common produce items for YOLO detection mapping
PRODUCE_LABELS = {
    "apple": "æble",
    "banana": "banan",
    "orange": "appelsin",
    "lemon": "citron",
    "lime": "lime",
    "grape": "vindrue",
    "strawberry": "jordbær",
    "blueberry": "blåbær",
    "raspberry": "hindbær",
    "watermelon": "vandmelon",
    "pineapple": "ananas",
    "mango": "mango",
    "avocado": "avocado",
    "tomato": "tomat",
    "potato": "kartoffel",
    "carrot": "gulerod",
    "onion": "løg",
    "garlic": "hvidløg",
    "pepper": "peberfrugt",
    "cucumber": "agurk",
    "lettuce": "salat",
    "cabbage": "kål",
    "broccoli": "broccoli",
    "cauliflower": "blomkål",
    "spinach": "spinat",
    "mushroom": "champignon",
    "corn": "majs",
    "peas": "ærter",
    "beans": "bønner",
    "zucchini": "squash",
    "eggplant": "aubergine",
    "celery": "selleri",
    "asparagus": "asparges",
    "ginger": "ingefær",
    "parsley": "persille",
    "basil": "basilikum",
    "mint": "mynte",
    "cilantro": "koriander",
}


BASE_URL = "https://www.nemlig.com"
SEARCH_API_URL = "https://webapi.prod.knl.nemlig.it/searchgateway/api"


@dataclass
class AuthTokens:
    """Authentication tokens for Nemlig API."""
    xsrf_token: str
    bearer_token: str
    session: requests.Session


class ProductNotFoundError(Exception):
    """Raised when a product cannot be found by ID."""
    pass


# Order status codes from the API
ORDER_STATUS_MAP = {
    1: "Pending",
    2: "Processing",
    4: "Delivered",
}


# Maximum orders to scan when looking up by ID
MAX_ORDER_HISTORY_LOOKUP = 100


def get_common_headers() -> dict:
    """Return common headers used for all API requests."""
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Device-Size": "desktop",
        "Platform": "web",
        "Version": "11.201.0",
        "X-Correlation-Id": str(uuid.uuid4()),
    }


def login_http_error(error: requests.exceptions.HTTPError, stage: str) -> str:
    """Report only our stage labels and recognized numeric server categories."""
    response = error.response
    status = response.status_code if response is not None else "unknown"
    category = "unclassified response"
    if response is not None:
        try:
            body = response.json()
        except ValueError:
            body = None
        code = body.get("ErrorCode") if isinstance(body, dict) else None
        # Categories used by the website's login handler; never echo server text.
        categories = {0: "missing argument", 3: "invalid format",
                      4: "unauthorized access", 5: "validation error",
                      10: "account not activated", 11: "member not found"}
        if type(code) is int and code in categories:
            category = f"{categories[code]} (code {code})"
    return f"Login failed while {stage}: HTTP {status}; {category}."


def login(username: str, password: str) -> AuthTokens:
    """
    Authenticate with Nemlig.com using the 3-step login flow.

    1. Get XSRF token
    2. Get Bearer token
    3. Login with credentials
    """
    session = requests.Session()
    headers = get_common_headers()

    spinner = Spinner("Connecting to nemlig.com")
    spinner.start()

    stage = "requesting login protection"
    try:
        # Step 1: Get XSRF token
        resp = session.get(f"{BASE_URL}/webapi/AntiForgery", headers=headers)
        resp.raise_for_status()
        xsrf_data = resp.json()
        xsrf_token = xsrf_data["Value"]

        # Step 2: Get Bearer token
        stage = "requesting an access token"
        headers["X-Correlation-Id"] = str(uuid.uuid4())
        resp = session.get(f"{BASE_URL}/webapi/Token", headers=headers)
        resp.raise_for_status()
        token_data = resp.json()
        bearer_token = token_data["access_token"]

        # Step 3: Login
        stage = "submitting the login"
        headers["X-Correlation-Id"] = str(uuid.uuid4())
        headers["X-XSRF-TOKEN"] = xsrf_token
        headers["Authorization"] = f"Bearer {bearer_token}"
        headers["Referer"] = f"{BASE_URL}/login?returnUrl=%2F"

        login_payload = {
            "Username": username,
            "Password": password,
            "CheckForExistingProducts": True,
            "DoMerge": True,
            "AppInstalled": False,
            "SaveExistingBasket": False,
        }

        resp = session.post(f"{BASE_URL}/webapi/login", headers=headers, json=login_payload)
        resp.raise_for_status()
        login_result = resp.json()

        if "RedirectUrl" not in login_result:
            raise RuntimeError("Login rejected by nemlig.com.")

        # Get fresh tokens after login
        stage = "refreshing the access token after login"
        headers["X-Correlation-Id"] = str(uuid.uuid4())
        resp = session.get(f"{BASE_URL}/webapi/Token", headers=headers)
        resp.raise_for_status()
        token_data = resp.json()
        bearer_token = token_data["access_token"]

        # Get fresh XSRF token
        stage = "refreshing login protection after login"
        resp = session.get(f"{BASE_URL}/webapi/AntiForgery", headers=headers)
        resp.raise_for_status()
        xsrf_data = resp.json()
        xsrf_token = xsrf_data["Value"]
    except requests.exceptions.HTTPError as error:
        spinner.stop()
        raise RuntimeError(login_http_error(error, stage)) from None
    except BaseException:
        spinner.stop()
        raise

    spinner.stop("Connected!")

    return AuthTokens(xsrf_token=xsrf_token, bearer_token=bearer_token, session=session)


def get_app_settings(auth: AuthTokens) -> dict:
    """Get app settings including timestamps needed for search."""
    headers = get_common_headers()
    headers["Authorization"] = f"Bearer {auth.bearer_token}"
    headers["X-XSRF-TOKEN"] = auth.xsrf_token

    resp = auth.session.get(f"{BASE_URL}/webapi/v2/AppSettings/Website", headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_page_settings(auth: AuthTokens) -> dict:
    """Get page settings including timeslot info needed for search."""
    headers = get_common_headers()
    headers["Authorization"] = f"Bearer {auth.bearer_token}"
    headers["X-XSRF-TOKEN"] = auth.xsrf_token

    # First get app settings to get initial timestamp
    settings = get_app_settings(auth)
    timeslot_utc = "2025120216-180-1020"  # Default fallback

    # Get page JSON which contains timeslot info
    params = {"GetAsJson": "1", "d": "1"}
    resp = auth.session.get(f"{BASE_URL}/", headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    page_settings = data.get("Settings", {})
    if page_settings.get("TimeslotUtc"):
        timeslot_utc = page_settings["TimeslotUtc"]

    return {
        "timestamp": settings.get("CombinedProductsAndSitecoreTimestamp", ""),
        "timeslotUtc": timeslot_utc,
        "deliveryZoneId": page_settings.get("DeliveryZoneId", 1),
        "userId": page_settings.get("UserId", ""),
    }


def search_products(auth: AuthTokens, query: str, limit: int = 10) -> list:
    """
    Search for products on nemlig.com using the full search API.

    Returns a list of product dictionaries.
    """
    page_settings = get_page_settings(auth)

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {auth.bearer_token}",
        "X-Correlation-Id": str(uuid.uuid4()),
        "Referer": f"{BASE_URL}/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    }

    params = {
        "query": query,
        "take": limit,
        "skip": 0,
        "recipeCount": 0,
        "timestamp": page_settings["timestamp"],
        "timeslotUtc": page_settings["timeslotUtc"],
        "deliveryZoneId": page_settings["deliveryZoneId"],
    }

    # Add user favorites if logged in
    if page_settings.get("userId"):
        params["includeFavorites"] = page_settings["userId"]

    resp = auth.session.get(f"{SEARCH_API_URL}/search", headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    # Full search returns products in Products.Products structure
    products_data = data.get("Products", {})
    products = products_data.get("Products", [])
    return products


def get_basket(auth: AuthTokens) -> dict:
    """Get the current shopping basket."""
    headers = get_common_headers()
    headers["Authorization"] = f"Bearer {auth.bearer_token}"
    headers["X-XSRF-TOKEN"] = auth.xsrf_token

    resp = auth.session.get(f"{BASE_URL}/webapi/basket/GetBasket", headers=headers)
    resp.raise_for_status()
    return resp.json()


def add_to_basket(auth: AuthTokens, product_id: str, quantity: int = 1) -> dict:
    """Set the quantity of a product in the basket.

    `quantity` is the absolute quantity to end up with, not a delta to add. Passing 0
    removes the product; there is no separate remove endpoint.
    """
    headers = get_common_headers()
    headers["Authorization"] = f"Bearer {auth.bearer_token}"
    headers["X-XSRF-TOKEN"] = auth.xsrf_token
    headers["Referer"] = f"{BASE_URL}/"

    payload = {
        "ProductId": product_id,
        "quantity": quantity,
        "AffectPartialQuantity": False,
        "disableQuantityValidation": False,
    }

    resp = auth.session.post(f"{BASE_URL}/webapi/basket/AddToBasket", headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def get_order_history(auth: AuthTokens, skip: int = 0, take: int = 10) -> dict:
    """Get paginated list of past orders."""
    headers = get_common_headers()
    headers["Authorization"] = f"Bearer {auth.bearer_token}"
    headers["X-XSRF-TOKEN"] = auth.xsrf_token

    params = {"skip": skip, "take": take}
    resp = auth.session.get(
        f"{BASE_URL}/webapi/order/GetBasicOrderHistory", headers=headers, params=params
    )
    resp.raise_for_status()
    return resp.json()


def get_order_details(auth: AuthTokens, order_id: int) -> dict:
    """Get detailed line items for a specific order."""
    headers = get_common_headers()
    headers["Authorization"] = f"Bearer {auth.bearer_token}"
    headers["X-XSRF-TOKEN"] = auth.xsrf_token

    resp = auth.session.get(
        f"{BASE_URL}/webapi/v2/order/GetOrderHistory/{order_id}", headers=headers
    )
    resp.raise_for_status()
    return resp.json()


def get_product_details(auth: AuthTokens, product_id: str) -> dict:
    """
    Get detailed product information using the GetAsJson endpoint.

    First searches for the product to get its URL, then fetches the full details.

    Raises:
        ProductNotFoundError: If product_id is not found or details unavailable.
    """
    # First, search to get the product URL (required because URL contains product name slug)
    products = search_products(auth, product_id, limit=5)

    # Find the exact product by ID
    product_url = None
    for p in products:
        if p.get("Id") == product_id:
            product_url = p.get("Url")
            break

    if not product_url:
        raise ProductNotFoundError(
            f"Product {product_id} not found. "
            f"Search returned {len(products)} products but none matched ID."
        )

    # Get page settings for timeslot
    page_settings = get_page_settings(auth)

    headers = get_common_headers()
    headers["Authorization"] = f"Bearer {auth.bearer_token}"
    headers["X-XSRF-TOKEN"] = auth.xsrf_token

    params = {
        "GetAsJson": "1",
        "t": page_settings["timeslotUtc"],
        "d": "1",
    }

    resp = auth.session.get(f"{BASE_URL}/{product_url}", headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    # Extract product details from content array
    content = data.get("content", [])
    for item in content:
        if item.get("TemplateName") == "productdetailspot":
            return item

    template_names = [item.get("TemplateName", "unknown") for item in content]
    raise ProductNotFoundError(
        f"Product {product_id}: No 'productdetailspot' in response. "
        f"Found templates: {template_names}"
    )


def strip_html_tags(html: str) -> str:
    """Remove HTML tags from text, returning plain text."""
    return re.sub(r"<[^>]+>", "", html).strip()


def wrap_text(text: str, width: int = 80, indent: str = "  ") -> list[str]:
    """Wrap text to specified width with indentation."""
    lines = []
    words = text.split()
    current_line = indent

    for word in words:
        if len(current_line) + len(word) + 1 > width:
            lines.append(current_line)
            current_line = indent + word
        else:
            if current_line == indent:
                current_line += word
            else:
                current_line += " " + word

    if current_line.strip():
        lines.append(current_line)

    return lines


def format_product(product: dict) -> str:
    """Format a product for display."""
    price = product.get("Price", 0)
    name = product.get("Name", "Unknown")
    brand = product.get("Brand", "")
    description = product.get("Description", "")
    product_id = product.get("Id", "")
    image_url = product.get("PrimaryImage", "")
    available = product.get("Availability", {}).get("IsAvailableInStock", False)

    availability_str = "In stock" if available else "OUT OF STOCK"

    line = f"  [{product_id}] {name} ({brand}) - {price:.2f} kr - {description} [{availability_str}]"
    if image_url:
        line += f"\n    Image: {image_url}"
    return line


def format_basket_line(line: dict) -> str:
    """Format a basket line item for display."""
    name = line.get("Name", "Unknown")
    brand = line.get("Brand", "")
    quantity = line.get("Quantity", 0)
    item_price = line.get("ItemPrice", 0)
    total_price = line.get("Price", 0)
    product_id = line.get("Id", "")

    return f"  [{product_id}] {name} ({brand}) x{quantity} @ {item_price:.2f} kr = {total_price:.2f} kr"


def format_list_item(item: dict) -> str:
    """Format a grocery list item for display."""
    name = item.get("name", "Unknown")
    brand = item.get("brand", "")
    quantity = item.get("quantity", 1)
    unit_price = item.get("unit_price", 0)
    product_id = item.get("product_id", "")
    subtotal = unit_price * quantity

    brand_str = f" ({brand})" if brand else ""
    return f"  [{product_id}] {name}{brand_str} x{quantity} @ {unit_price:.2f} kr = {subtotal:.2f} kr"


CART_ART = r"""
   __________
  /         /|
 /_________/ |
 |  NEMLIG | |
 |_________|/
    O   O
"""

def format_list_summary(items: list, budget: float) -> str:
    """Format full grocery list with budget status."""
    lines = []

    if not items:
        lines.append("Your grocery list is empty.")
        lines.append(f"\nBudget: {budget:.2f} kr")
        lines.append("\nUse 'list add \"product\"' to add items")
        return "\n".join(lines)

    # Calculate total
    total = sum(item.get("unit_price", 0) * item.get("quantity", 1) for item in items)
    remaining = budget - total

    lines.append(f"Grocery List ({len(items)} items):\n")

    for item in items:
        lines.append(format_list_item(item))

    lines.append(f"\n  Subtotal:   {total:.2f} kr")
    lines.append(f"  Budget:     {budget:.2f} kr")
    lines.append(f"  Remaining:  {remaining:.2f} kr")

    # Budget bar visualization
    if budget > 0:
        bar_width = 30
        pct = (total / budget) * 100
        filled = min(int((total / budget) * bar_width), bar_width)
        empty = bar_width - filled

        # Color coding: green (<70%), yellow (70-90%), red (>90%)
        if pct > 100:
            bar = "\033[91m" + "█" * bar_width + "\033[0m"  # Red, overfilled
            status = "\033[91mOVER BUDGET!\033[0m"
        elif pct > 90:
            bar = "\033[91m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"  # Red
            status = f"\033[91m{pct:.0f}%\033[0m"
        elif pct > 70:
            bar = "\033[93m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"  # Yellow
            status = f"\033[93m{pct:.0f}%\033[0m"
        else:
            bar = "\033[92m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"  # Green
            status = f"\033[92m{pct:.0f}%\033[0m"

        lines.append(f"\n  [{bar}] {status}")

    return "\n".join(lines)


def format_order_summary(order: dict) -> str:
    """Format an order for the history list view."""
    order_num = order.get("OrderNumber", "Unknown")
    order_id = order.get("Id", "")
    total = order.get("Total", 0)
    status_code = order.get("Status", 0)
    order_date = order.get("OrderDate", "")

    # Parse date for display (ISO format: 2025-11-25T06:07:18Z)
    if order_date:
        date_part = order_date.split("T")[0]
    else:
        date_part = "Unknown"

    status = ORDER_STATUS_MAP.get(status_code, f"Status {status_code}")

    # Delivery time window
    delivery_time = order.get("DeliveryTime", {})
    delivery_start = delivery_time.get("Start", "")
    delivery_end = delivery_time.get("End", "")
    if delivery_start and delivery_end:
        # Extract time part (HH:MM)
        start_time = delivery_start.split("T")[1][:5] if "T" in delivery_start else ""
        end_time = delivery_end.split("T")[1][:5] if "T" in delivery_end else ""
        delivery_date = delivery_start.split("T")[0] if "T" in delivery_start else ""
        delivery_str = f"{delivery_date} {start_time}-{end_time}"
    else:
        delivery_str = "N/A"

    return f"  [{order_id}] {order_num} - {date_part} - {total:.2f} kr - {status} - Delivery: {delivery_str}"


def format_order_line(line: dict) -> str:
    """Format an order line item for display."""
    name = line.get("ProductName", "Unknown")
    quantity = line.get("Quantity", 0)
    amount = line.get("Amount", 0)
    avg_price = line.get("AverageItemPrice", 0)
    product_num = line.get("ProductNumber", "")
    description = line.get("Description", "")
    has_campaign = line.get("HasCampaign", False)

    campaign_str = " [OFFER]" if has_campaign else ""
    return f"  [{product_num}] {name} - {description} x{quantity:.0f} @ {avg_price:.2f} kr = {amount:.2f} kr{campaign_str}"


def format_order_details(order: dict, lines: list) -> str:
    """Format full order details with line items."""
    output = []

    order_num = order.get("OrderNumber", "Unknown")
    order_id = order.get("Id", "")
    total = order.get("Total", 0)
    subtotal = order.get("SubTotal", 0)
    delivery_fee = total - subtotal

    output.append(f"Order {order_num}")
    output.append("=" * (len(f"Order {order_num}")))
    output.append("")
    output.append(f"Order ID:     {order_id}")
    output.append(f"Subtotal:     {subtotal:.2f} kr")
    output.append(f"Delivery:     {delivery_fee:.2f} kr")
    output.append(f"Total:        {total:.2f} kr")
    output.append("")
    output.append(f"Items ({len(lines)}):")

    for line in lines:
        output.append(format_order_line(line))

    # Calculate totals from lines
    line_total = sum(line.get("Amount", 0) for line in lines)
    output.append("")
    output.append(f"  Lines total: {line_total:.2f} kr")

    return "\n".join(output)


def format_product_details(product: dict) -> str:
    """Format detailed product information for display."""
    lines = []

    # Basic info
    name = product.get("Name", "Unknown")
    brand = product.get("Brand", "")
    product_id = product.get("Id", "")
    price = product.get("Price", 0)
    unit_price = product.get("UnitPriceCalc", 0)
    unit_label = product.get("UnitPriceLabel", "")
    description = product.get("Description", "")
    category = product.get("Category", "")
    subcategory = product.get("SubCategory", "")

    lines.append(f"{name}")
    lines.append(f"{'=' * len(name)}")
    lines.append("")
    lines.append(f"ID:          {product_id}")
    lines.append(f"Brand:       {brand}")
    lines.append(f"Category:    {category} > {subcategory}")
    lines.append(f"Description: {description}")
    lines.append("")
    lines.append(f"Price:       {price:.2f} kr ({unit_price:.2f} {unit_label})")

    # Campaign info
    campaign = product.get("Campaign")
    if campaign:
        campaign_type = campaign.get("Type", "")
        min_qty = campaign.get("MinQuantity", 0)
        campaign_price = campaign.get("TotalPrice", 0)
        lines.append(f"Campaign:    {min_qty} for {campaign_price:.2f} kr ({campaign_type})")

    # Availability
    availability = product.get("Availability", {})
    in_stock = availability.get("IsAvailableInStock", False)
    delivery_ok = availability.get("IsDeliveryAvailable", False)
    stock_status = "In stock" if in_stock else "OUT OF STOCK"
    delivery_status = "Available" if delivery_ok else "Not available"
    lines.append("")
    lines.append(f"Stock:       {stock_status}")
    lines.append(f"Delivery:    {delivery_status}")

    # Attributes
    attributes = product.get("Attributes", [])
    if attributes:
        lines.append("")
        lines.append("Attributes:")
        for attr in attributes:
            attr_name = attr.get("Name", "")
            attr_value = attr.get("Value", "")
            lines.append(f"  {attr_name}: {attr_value}")

    # Labels
    labels = product.get("Labels", [])
    if labels:
        lines.append("")
        lines.append(f"Labels:      {', '.join(labels)}")

    # Product description (HTML text, strip tags for CLI)
    text = product.get("Text", "")
    if text:
        clean_text = strip_html_tags(text)
        if clean_text:
            lines.append("")
            lines.append("About:")
            lines.extend(wrap_text(clean_text))

    # URL
    url = product.get("Url", "")
    if url:
        lines.append("")
        lines.append(f"URL:         {BASE_URL}/{url}")

    return "\n".join(lines)


def cmd_search(auth: AuthTokens, args: argparse.Namespace) -> int:
    """Handle the search command."""
    query = args.query
    limit = args.limit

    print(f"Searching for '{query}'...", file=sys.stderr)
    products = search_products(auth, query, limit)

    if not products:
        print(f"No products found for '{query}'")
        return 1

    print(f"\nFound {len(products)} products:\n")
    for product in products:
        print(format_product(product))

    return 0


def cmd_basket(auth: AuthTokens, args: argparse.Namespace) -> int:
    """Handle the basket command."""
    print("Fetching basket...", file=sys.stderr)
    basket = get_basket(auth)

    lines = basket.get("Lines", [])

    if not lines:
        print("Your basket is empty.")
        return 0

    print(f"\nBasket ({len(lines)} items):\n")

    total = 0
    for line in lines:
        print(format_basket_line(line))
        total += line.get("Price", 0)

    print(f"\n  Total: {total:.2f} kr")

    return 0


def cmd_add(auth: AuthTokens, args: argparse.Namespace) -> int:
    """Handle the add command."""
    product_id = args.product_id
    quantity = args.quantity

    if quantity == 0:
        print(f"Removing product {product_id} from basket...", file=sys.stderr)
    else:
        print(f"Adding product {product_id} (quantity: {quantity}) to basket...", file=sys.stderr)

    result = add_to_basket(auth, product_id, quantity)

    # Find the added product in the result
    lines = result.get("Lines", [])
    added_line = None
    for line in lines:
        if line.get("Id") == product_id:
            added_line = line
            break

    if quantity == 0:
        # Quantity 0 removes the product, so it is absent from the returned basket.
        print(f"\nProduct {product_id} removed from basket.")
    elif added_line:
        print("\nAdded to basket:")
        print(format_basket_line(added_line))
    else:
        print(f"Product {product_id} added to basket.")

    # Show basket total
    total = sum(line.get("Price", 0) for line in lines)
    print(f"\nBasket total: {total:.2f} kr ({len(lines)} items)")

    return 0


def cmd_details(auth: AuthTokens, args: argparse.Namespace) -> int:
    """Handle the details command."""
    product_id = args.product_id

    print(f"Fetching details for product {product_id}...", file=sys.stderr)

    try:
        product = get_product_details(auth, product_id)
    except ProductNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print()
    print(format_product_details(product))

    return 0


def cmd_history(auth: AuthTokens, args: argparse.Namespace) -> int:
    """Handle the history command."""
    order_id = args.order_id
    limit = args.limit

    if order_id:
        # Show details for specific order
        print(f"Fetching order {order_id}...", file=sys.stderr)

        # Get order summary from recent history
        history = get_order_history(auth, skip=0, take=MAX_ORDER_HISTORY_LOOKUP)
        orders = history.get("Orders", [])
        order = None
        for o in orders:
            if o.get("Id") == order_id:
                order = o
                break

        if not order:
            print(
                f"Order {order_id} not found in last {MAX_ORDER_HISTORY_LOOKUP} orders.",
                file=sys.stderr,
            )
            return 1

        # Get line items
        details = get_order_details(auth, order_id)
        lines = details.get("Lines", [])

        print()
        print(format_order_details(order, lines))
    else:
        # List recent orders
        print("Fetching order history...", file=sys.stderr)
        history = get_order_history(auth, skip=0, take=limit)
        orders = history.get("Orders", [])
        num_pages = history.get("NumberOfPages", 1)

        if not orders:
            print("No orders found.")
            return 0

        print(f"\nOrder History ({len(orders)} orders, {num_pages} pages total):\n")
        for order in orders:
            print(format_order_summary(order))

        print("\nUse 'history ORDER_ID' to see order details.")

    return 0


def cmd_list_show(args: argparse.Namespace) -> int:
    """Display the current grocery list."""
    data = load_grocery_list()
    print(format_list_summary(data["items"], data["budget"]))
    return 0


def cmd_list_add(auth: AuthTokens, args: argparse.Namespace) -> int:
    """Add a product to the grocery list."""
    product_id = args.product_id
    quantity = args.quantity

    # If not a numeric ID, treat as search query
    if not product_id.isdigit():
        print(f"Searching for '{product_id}'...", file=sys.stderr)
        products = search_products(auth, product_id, limit=10)

        if not products:
            print(f"No products found for '{product_id}'")
            return 1

        print(f"\nFound {len(products)} products:\n")
        for i, p in enumerate(products, 1):
            price = p.get("Price", 0)
            name = p.get("Name", "Unknown")
            brand = p.get("Brand", "")
            pid = p.get("Id", "")
            available = p.get("Availability", {}).get("IsAvailableInStock", False)
            stock = "In stock" if available else "OUT OF STOCK"
            print(f"  [{i}] {name} ({brand}) - {price:.2f} kr [{stock}]")

        print()
        try:
            choice = input("Enter number to add (or 'q' to cancel): ").strip()
            if choice.lower() == 'q':
                print("Cancelled.")
                return 0
            idx = int(choice) - 1
            if idx < 0 or idx >= len(products):
                print("Invalid selection.", file=sys.stderr)
                return 1
            product = products[idx]
            product_id = product.get("Id")
        except (ValueError, EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 0
    else:
        print(f"Fetching product {product_id}...", file=sys.stderr)
        try:
            product = get_product_details(auth, product_id)
        except ProductNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    data = load_grocery_list()

    # Check if product already in list
    for item in data["items"]:
        if item["product_id"] == product_id:
            item["quantity"] += quantity
            item["unit_price"] = product.get("Price", item["unit_price"])
            save_grocery_list(data)
            print(f"Updated quantity: {item['name']} x{item['quantity']}")
            print(format_list_summary(data["items"], data["budget"]))
            return 0

    # Add new item
    new_item = {
        "product_id": product_id,
        "name": product.get("Name", "Unknown"),
        "brand": product.get("Brand", ""),
        "quantity": quantity,
        "unit_price": product.get("Price", 0),
    }
    data["items"].append(new_item)
    save_grocery_list(data)

    print(f"Added: {new_item['name']} x{quantity}")
    print()
    print(format_list_summary(data["items"], data["budget"]))
    return 0


def cmd_list_remove(args: argparse.Namespace) -> int:
    """Remove a product from the grocery list."""
    product_id = args.product_id

    data = load_grocery_list()

    for i, item in enumerate(data["items"]):
        if item["product_id"] == product_id:
            removed = data["items"].pop(i)
            save_grocery_list(data)
            print(f"Removed: {removed['name']}")
            print()
            print(format_list_summary(data["items"], data["budget"]))
            return 0

    print(f"Product {product_id} not found in list.", file=sys.stderr)
    return 1


def cmd_list_clear(args: argparse.Namespace) -> int:
    """Clear all items from the grocery list."""
    data = load_grocery_list()
    count = len(data["items"])
    data["items"] = []
    save_grocery_list(data)
    print(f"Cleared {count} items from list.")
    return 0


def cmd_list_budget(args: argparse.Namespace) -> int:
    """Show or set the budget."""
    data = load_grocery_list()

    if args.amount is not None:
        data["budget"] = args.amount
        save_grocery_list(data)
        print(f"Budget set to {args.amount:.2f} kr")
    else:
        budget = data["budget"]
        total = sum(item.get("unit_price", 0) * item.get("quantity", 1) for item in data["items"])
        remaining = budget - total
        print(f"Current budget: {budget:.2f} kr")
        print(f"List total:     {total:.2f} kr")
        print(f"Remaining:      {remaining:.2f} kr")

        # Progress bar
        if budget > 0:
            bar_width = 30
            pct = (total / budget) * 100
            filled = min(int((total / budget) * bar_width), bar_width)
            empty = bar_width - filled

            if pct > 100:
                bar = "\033[91m" + "█" * bar_width + "\033[0m"
                status = "\033[91mOVER BUDGET!\033[0m"
            elif pct > 90:
                bar = "\033[91m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"
                status = f"\033[91m{pct:.0f}%\033[0m"
            elif pct > 70:
                bar = "\033[93m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"
                status = f"\033[93m{pct:.0f}%\033[0m"
            else:
                bar = "\033[92m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"
                status = f"\033[92m{pct:.0f}%\033[0m"

            print(f"\n[{bar}] {status}")

    return 0


def cmd_list_sync(auth: AuthTokens, args: argparse.Namespace) -> int:
    """Sync grocery list to nemlig basket."""
    data = load_grocery_list()

    if not data["items"]:
        print("Grocery list is empty. Nothing to sync.")
        return 0

    print(f"Syncing {len(data['items'])} items to basket...", file=sys.stderr)

    success_count = 0
    for item in data["items"]:
        product_id = item["product_id"]
        quantity = item["quantity"]
        try:
            add_to_basket(auth, product_id, quantity)
            print(f"  ✓ {item['name']} x{quantity}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ {item['name']} - Error: {e}", file=sys.stderr)

    print(f"\nSynced {success_count}/{len(data['items'])} items to basket.")

    if success_count > 0:
        print("\nUse 'basket' command to view your nemlig basket.")

    return 0 if success_count == len(data["items"]) else 1


# ============================================================================
# AI Meal Planning
# ============================================================================

MEAL_PLAN_TOOLS = [
    {
        "name": "search_products",
        "description": "Search for grocery products on nemlig.com. Returns a list of products with their IDs, names, prices, and availability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search term (e.g., 'mælk', 'hakket oksekød', 'pasta')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_to_grocery_list",
        "description": "Add a product to the grocery list by its product ID. Use search_products first to find the product ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID from search results"
                },
                "quantity": {
                    "type": "integer",
                    "description": "Number of items to add (default: 1)",
                    "default": 1
                }
            },
            "required": ["product_id"]
        }
    },
    {
        "name": "view_grocery_list",
        "description": "View the current grocery list with all items, quantities, and budget status.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "remove_from_grocery_list",
        "description": "Remove a product from the grocery list by its product ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The product ID to remove"
                }
            },
            "required": ["product_id"]
        }
    },
    {
        "name": "set_budget",
        "description": "Set the budget limit for the grocery list in Danish kroner (kr).",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Budget amount in kr"
                }
            },
            "required": ["amount"]
        }
    },
    {
        "name": "clear_grocery_list",
        "description": "Clear all items from the grocery list. Use with caution.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]


def execute_meal_plan_tool(auth: AuthTokens, tool_name: str, tool_input: dict) -> str:
    """Execute a meal planning tool and return the result as a string."""
    try:
        if tool_name == "search_products":
            query = tool_input["query"]
            limit = tool_input.get("limit", 5)
            products = search_products(auth, query, limit=limit)

            if not products:
                return f"No products found for '{query}'"

            results = []
            for p in products:
                pid = p.get("Id", "")
                name = p.get("Name", "Unknown")
                brand = p.get("Brand", "")
                price = p.get("Price", 0)
                unit_price = p.get("UnitPrice", "")
                available = p.get("Availability", {}).get("IsAvailableInStock", False)
                stock = "In stock" if available else "OUT OF STOCK"

                results.append(
                    f"- ID: {pid} | {name} ({brand}) | {price:.2f} kr | {unit_price} | {stock}"
                )

            return f"Found {len(products)} products for '{query}':\n" + "\n".join(results)

        elif tool_name == "add_to_grocery_list":
            product_id = str(tool_input["product_id"])
            quantity = tool_input.get("quantity", 1)

            # Fetch product details
            try:
                product = get_product_details(auth, product_id)
            except ProductNotFoundError as e:
                return f"Error: {e}"

            data = load_grocery_list()

            # Check if already in list
            for item in data["items"]:
                if str(item["product_id"]) == product_id:
                    item["quantity"] += quantity
                    save_grocery_list(data)
                    return f"Updated quantity: {item['name']} x{item['quantity']} (was x{item['quantity'] - quantity})"

            # Add new item
            new_item = {
                "product_id": product_id,
                "name": product.get("Name", "Unknown"),
                "brand": product.get("Brand", ""),
                "unit_price": product.get("Price", 0),
                "quantity": quantity,
            }
            data["items"].append(new_item)
            save_grocery_list(data)

            total = sum(i["unit_price"] * i["quantity"] for i in data["items"])
            return f"Added: {new_item['name']} x{quantity} ({new_item['unit_price']:.2f} kr each)\nList total: {total:.2f} kr / Budget: {data['budget']:.2f} kr"

        elif tool_name == "view_grocery_list":
            data = load_grocery_list()
            if not data["items"]:
                return f"Grocery list is empty. Budget: {data['budget']:.2f} kr"

            lines = [f"Grocery List ({len(data['items'])} items):"]
            total = 0
            for item in data["items"]:
                subtotal = item["unit_price"] * item["quantity"]
                total += subtotal
                lines.append(f"- [{item['product_id']}] {item['name']} x{item['quantity']} = {subtotal:.2f} kr")

            lines.append(f"\nSubtotal: {total:.2f} kr")
            lines.append(f"Budget: {data['budget']:.2f} kr")
            lines.append(f"Remaining: {data['budget'] - total:.2f} kr")

            pct = (total / data['budget'] * 100) if data['budget'] > 0 else 0
            lines.append(f"Budget used: {pct:.0f}%")

            return "\n".join(lines)

        elif tool_name == "remove_from_grocery_list":
            product_id = str(tool_input["product_id"])
            data = load_grocery_list()

            for i, item in enumerate(data["items"]):
                if str(item["product_id"]) == product_id:
                    removed = data["items"].pop(i)
                    save_grocery_list(data)
                    return f"Removed: {removed['name']} x{removed['quantity']}"

            return f"Product {product_id} not found in grocery list"

        elif tool_name == "set_budget":
            amount = float(tool_input["amount"])
            data = load_grocery_list()
            data["budget"] = amount
            save_grocery_list(data)
            return f"Budget set to {amount:.2f} kr"

        elif tool_name == "clear_grocery_list":
            data = load_grocery_list()
            count = len(data["items"])
            data["items"] = []
            save_grocery_list(data)
            return f"Cleared {count} items from grocery list"

        else:
            return f"Unknown tool: {tool_name}"

    except Exception as e:
        return f"Error executing {tool_name}: {e}"


MEAL_PLAN_SYSTEM_PROMPT = """You are a helpful Danish grocery shopping assistant for nemlig.com. You help users plan their meals for the week and build a grocery list.

Your capabilities:
- Search for products on nemlig.com
- Add products to the user's grocery list
- View and manage the grocery list
- Set a budget and help users stay within it

Guidelines:
- Always search for products before adding them to understand what's available
- Consider the user's budget when making suggestions
- Prioritize essential ingredients for recipes over nice-to-haves
- When the user mentions a recipe or meal, think about all ingredients needed
- Products are priced in Danish kroner (kr)
- Be concise but helpful in your responses
- If a product isn't available, suggest alternatives
- When adding multiple items, add them one at a time to ensure accuracy

When the user describes meals or recipes they want to make:
1. First, understand all the ingredients needed
2. Search for each ingredient to find the best options
3. Consider price and availability
4. Add items to the list, prioritizing by importance to the recipes
5. Keep track of the budget and warn if getting close to the limit"""


def meal_plan_chat(auth: AuthTokens) -> int:
    """Run the AI meal planning chat interface."""
    if not ANTHROPIC_AVAILABLE:
        print("\n  Error: anthropic package not installed.")
        print("  Run: uv add anthropic")
        return 1

    api_key = get_anthropic_api_key()
    if not api_key:
        print("\n  Error: ANTHROPIC_API_KEY not found.")
        print("  Set it in ~/.config/nemlig/login.json or as environment variable.")
        print('  Example: {"username": "user@example.com", "anthropic_api_key": "sk-ant-..."}')
        return 1

    client = anthropic.Anthropic(api_key=api_key)
    messages = []

    print("\n  🍽️  AI Meal Planner")
    print("  ─────────────────────────────────────────────────────")
    print("  Tell me what meals you want to make this week, and I'll")
    print("  help you build a grocery list within your budget.")
    print()
    print("  Examples:")
    print("    'I want to make spaghetti bolognese and a chicken salad'")
    print("    'Set my budget to 500 kr'")
    print("    'What's on my list so far?'")
    print()
    print("  Type 'done' to exit meal planning.")
    print("  ─────────────────────────────────────────────────────\n")

    # Show current list status
    data = load_grocery_list()
    total = sum(i["unit_price"] * i["quantity"] for i in data["items"])
    print(f"  Current list: {len(data['items'])} items | {total:.2f} kr / {data['budget']:.2f} kr budget\n")

    while True:
        try:
            user_input = input("  you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Exiting meal planner.\n")
            return 0

        if not user_input:
            continue

        if user_input.lower() in ("done", "exit", "quit", "q"):
            print("\n  Exiting meal planner.\n")
            return 0

        messages.append({"role": "user", "content": user_input})

        # Show thinking indicator
        spinner = Spinner("Thinking")
        spinner.start()

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system=MEAL_PLAN_SYSTEM_PROMPT,
                tools=MEAL_PLAN_TOOLS,
                messages=messages
            )
        except Exception as e:
            spinner.stop("Error")
            print(f"\n  Error: {e}\n")
            messages.pop()  # Remove failed message
            continue

        spinner.stop("")

        # Process response
        while response.stop_reason == "tool_use":
            # Handle tool calls
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    print(f"  \033[90m[{tool_name}: {json.dumps(tool_input, ensure_ascii=False)}]\033[0m")

                    result = execute_meal_plan_tool(auth, tool_name, tool_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result
                    })

            messages.append({"role": "user", "content": tool_results})

            # Continue conversation
            spinner = Spinner("Processing")
            spinner.start()
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=MEAL_PLAN_SYSTEM_PROMPT,
                    tools=MEAL_PLAN_TOOLS,
                    messages=messages
                )
            except Exception as e:
                spinner.stop("Error")
                print(f"\n  Error: {e}\n")
                break
            spinner.stop("")

        # Print final text response
        for block in response.content:
            if hasattr(block, "text"):
                # Indent the response
                text = block.text
                indented = "\n".join(f"  {line}" for line in text.split("\n"))
                print(f"\n  \033[96m🤖\033[0m{indented[2:]}\n")

        messages.append({"role": "assistant", "content": response.content})

    return 0


# ============================================================================
# Google Form / Recipe Import
# ============================================================================

RECIPE_EXTRACT_PROMPT = """You are a grocery shopping assistant. Given a list of meals or recipes that someone wants to make, extract ALL the ingredients needed.

For each ingredient:
1. Identify the ingredient name in Danish (translate if needed for nemlig.com)
2. Estimate the quantity needed
3. Prioritize by importance (essential ingredients first, optional garnishes last)

Output your response as a JSON array of ingredients:
[
  {"ingredient": "hakket oksekød", "quantity": 500, "unit": "g", "priority": 1, "for_recipe": "Spaghetti Bolognese"},
  {"ingredient": "spaghetti", "quantity": 500, "unit": "g", "priority": 1, "for_recipe": "Spaghetti Bolognese"},
  ...
]

Be thorough - include all ingredients mentioned in recipes. Use Danish names for products when possible as this is for a Danish grocery store."""


def extract_ingredients_from_recipes(recipes_text: str) -> list[dict]:
    """Use Claude to extract ingredients from recipe text."""
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("anthropic package not installed")

    api_key = get_anthropic_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"Extract all ingredients from these meal plans/recipes:\n\n{recipes_text}\n\nRespond with ONLY a JSON array, no other text."
            }
        ],
        system=RECIPE_EXTRACT_PROMPT
    )

    # Parse JSON from response
    response_text = response.content[0].text.strip()

    # Handle markdown code blocks
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])

    return json.loads(response_text)


def process_form_recipes(auth: AuthTokens, spreadsheet_id: str | None = None) -> int:
    """Fetch recipes from Google Form responses and build grocery list."""
    print("\n  📋 Recipe Import from Google Form")
    print("  ─────────────────────────────────────────────────────\n")

    # Get spreadsheet ID
    config = load_gsheets_config()
    if spreadsheet_id:
        config["spreadsheet_id"] = spreadsheet_id
        save_gsheets_config(config)
    elif not config.get("spreadsheet_id"):
        print("  No spreadsheet ID configured.")
        print("  Usage: nemlig_cli.py import <SPREADSHEET_ID>")
        print("  Or: nemlig_cli.py import --setup")
        return 1

    sheet_id = config.get("spreadsheet_id", spreadsheet_id)

    # Fetch data from sheet
    print(f"  Fetching data from Google Sheet...")
    spinner = Spinner("Connecting to Google Sheets")
    spinner.start()

    try:
        rows = fetch_sheet_data(sheet_id)
    except FileNotFoundError as e:
        spinner.stop("Error")
        print(f"\n  {e}")
        return 1
    except Exception as e:
        spinner.stop("Error")
        print(f"\n  Error fetching sheet: {e}")
        return 1

    spinner.stop(f"Found {len(rows)} rows")

    if not rows:
        print("  No data in spreadsheet.")
        return 1

    # Assume first row is headers
    headers = rows[0] if rows else []
    data_rows = rows[1:] if len(rows) > 1 else []

    print(f"  Headers: {headers}")
    print(f"  Data rows: {len(data_rows)}\n")

    if not data_rows:
        print("  No form responses yet.")
        return 0

    # Combine all recipe text from form responses
    recipes_text = ""
    for i, row in enumerate(data_rows, 1):
        # Skip timestamp column (usually first), combine rest
        recipe_data = " | ".join(row[1:]) if len(row) > 1 else row[0] if row else ""
        if recipe_data.strip():
            recipes_text += f"\nSubmission {i}:\n{recipe_data}\n"

    if not recipes_text.strip():
        print("  No recipe data found in form responses.")
        return 0

    print("  Form responses:")
    print("  " + "-" * 50)
    for line in recipes_text.strip().split("\n"):
        print(f"  {line}")
    print("  " + "-" * 50)

    # Extract ingredients using LLM
    print("\n  Analyzing recipes with AI...")
    spinner = Spinner("Extracting ingredients")
    spinner.start()

    try:
        ingredients = extract_ingredients_from_recipes(recipes_text)
    except json.JSONDecodeError as e:
        spinner.stop("Error parsing AI response")
        print(f"\n  Could not parse ingredients: {e}")
        return 1
    except Exception as e:
        spinner.stop("Error")
        print(f"\n  Error extracting ingredients: {e}")
        return 1

    spinner.stop(f"Found {len(ingredients)} ingredients")

    if not ingredients:
        print("  No ingredients extracted.")
        return 0

    # Show extracted ingredients
    print("\n  Extracted ingredients:")
    print("  " + "-" * 50)
    for ing in ingredients:
        qty = ing.get("quantity", "")
        unit = ing.get("unit", "")
        name = ing.get("ingredient", "")
        recipe = ing.get("for_recipe", "")
        print(f"  • {name} ({qty}{unit}) - for {recipe}")
    print("  " + "-" * 50)

    # Confirm with user
    print(f"\n  Ready to search and add {len(ingredients)} ingredients to your grocery list.")
    try:
        confirm = input("  Proceed? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return 0

    if confirm and confirm != "y":
        print("  Cancelled.")
        return 0

    # Search and add each ingredient
    print("\n  Adding ingredients to grocery list...\n")
    added = 0
    failed = []

    for ing in ingredients:
        name = ing.get("ingredient", "")
        qty = ing.get("quantity", 1)

        # Determine quantity to add (default to 1 item)
        add_qty = 1
        if isinstance(qty, (int, float)) and qty > 0:
            # Rough conversion: if unit is 'g' or 'ml' and qty > 100, still add 1 package
            add_qty = 1

        spinner = Spinner(f"Searching: {name}")
        spinner.start()

        try:
            products = search_products(auth, name, limit=3)

            if not products:
                spinner.stop(f"✗ Not found: {name}")
                failed.append(name)
                continue

            # Pick first available product
            product = None
            for p in products:
                if p.get("Availability", {}).get("IsAvailableInStock", False):
                    product = p
                    break

            if not product:
                product = products[0]  # Use first even if out of stock

            product_id = str(product.get("Id"))
            product_name = product.get("Name", name)
            price = product.get("Price", 0)

            # Add to grocery list
            data = load_grocery_list()

            # Check if already in list
            existing = None
            for item in data["items"]:
                if str(item["product_id"]) == product_id:
                    existing = item
                    break

            if existing:
                existing["quantity"] += add_qty
                spinner.stop(f"✓ Updated: {product_name} (now x{existing['quantity']})")
            else:
                new_item = {
                    "product_id": product_id,
                    "name": product_name,
                    "brand": product.get("Brand", ""),
                    "unit_price": price,
                    "quantity": add_qty,
                }
                data["items"].append(new_item)
                spinner.stop(f"✓ Added: {product_name} - {price:.2f} kr")

            save_grocery_list(data)
            added += 1

        except Exception as e:
            spinner.stop(f"✗ Error: {name} - {e}")
            failed.append(name)

    # Summary
    print("\n  " + "=" * 50)
    print(f"  ✓ Added {added} items to grocery list")
    if failed:
        print(f"  ✗ Failed to find: {', '.join(failed)}")

    # Show list summary
    data = load_grocery_list()
    total = sum(i["unit_price"] * i["quantity"] for i in data["items"])
    print(f"\n  List total: {total:.2f} kr / Budget: {data['budget']:.2f} kr")

    if total > data["budget"]:
        print(f"  \033[91m⚠ Over budget by {total - data['budget']:.2f} kr!\033[0m")

    print("\n  Use 'list' to view full grocery list, 'list sync' to push to nemlig.\n")

    return 0


def cmd_import_setup() -> int:
    """Interactive setup for Google Sheets import."""
    print("\n  📋 Google Sheets Import Setup")
    print("  ─────────────────────────────────────────────────────\n")

    print("  Step 1: Google Cloud Setup")
    print("  ─────────────────────────────────────────────────────")
    print("  1. Go to https://console.cloud.google.com/")
    print("  2. Create a new project or select existing")
    print("  3. Enable 'Google Sheets API'")
    print("  4. Go to APIs & Services > Credentials")
    print("  5. Create OAuth 2.0 Client ID (Desktop app)")
    print("  6. Download the credentials JSON file")
    print(f"  7. Save it as: {GSHEETS_CREDENTIALS_FILE}")
    print()

    print("  Step 2: Spreadsheet ID")
    print("  ─────────────────────────────────────────────────────")
    print("  Your Google Form responses are saved to a linked spreadsheet.")
    print("  The spreadsheet ID is in the URL:")
    print("  https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit")
    print()

    try:
        sheet_id = input("  Enter spreadsheet ID: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return 0

    if sheet_id:
        config = load_gsheets_config()
        config["spreadsheet_id"] = sheet_id
        save_gsheets_config(config)
        print(f"\n  ✓ Spreadsheet ID saved to {GSHEETS_CONFIG_FILE}")
        print("  Run 'just import' to fetch and process recipes.")
    else:
        print("  No spreadsheet ID provided.")

    return 0


# ============================================================================
# Fridge Scanner (Raspberry Pi AI Camera)
# ============================================================================

def lookup_barcode(barcode: str) -> dict | None:
    """Look up product info from barcode using OpenFoodFacts."""
    if not SCANNER_AVAILABLE:
        return None

    try:
        api = openfoodfacts.API(user_agent="NemligCLI/1.0")
        product = api.product.get(barcode, fields=["code", "product_name", "brands", "quantity", "categories_tags"])

        if product and product.get("product_name"):
            return {
                "barcode": barcode,
                "name": product.get("product_name", "Unknown"),
                "brand": product.get("brands", ""),
                "quantity": product.get("quantity", ""),
                "categories": product.get("categories_tags", []),
                "source": "openfoodfacts"
            }
    except Exception:
        pass

    return None


def scan_barcodes_from_image(image) -> list[str]:
    """Detect and decode barcodes from an image using pyzbar."""
    if not SCANNER_AVAILABLE:
        return []

    # Convert to grayscale for better detection
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # Decode barcodes
    barcodes = pyzbar.decode(gray)
    return [barcode.data.decode("utf-8") for barcode in barcodes]


def detect_produce_from_image(image, imx500=None) -> list[dict]:
    """Detect fruits/vegetables using YOLO on IMX500 or fallback to basic detection."""
    detected = []

    if PICAMERA_AVAILABLE and imx500:
        # Use IMX500 AI accelerator for object detection
        try:
            # Get detections from IMX500 (assumes YOLO model loaded)
            detections = imx500.get_outputs()
            if detections:
                for det in detections:
                    label = det.get("label", "").lower()
                    confidence = det.get("confidence", 0)

                    if confidence > 0.5 and label in PRODUCE_LABELS:
                        detected.append({
                            "name": PRODUCE_LABELS.get(label, label),
                            "name_en": label,
                            "confidence": confidence,
                            "source": "imx500_yolo"
                        })
        except Exception:
            pass

    # Fallback: Use color-based detection for common produce
    # This is a simplified approach - real implementation would use a proper model
    if not detected and SCANNER_AVAILABLE:
        try:
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

            # Detect yellow (banana, lemon)
            yellow_mask = cv2.inRange(hsv, (20, 100, 100), (35, 255, 255))
            if cv2.countNonZero(yellow_mask) > 5000:
                detected.append({"name": "banan/citron", "name_en": "banana/lemon", "confidence": 0.3, "source": "color"})

            # Detect orange
            orange_mask = cv2.inRange(hsv, (10, 100, 100), (20, 255, 255))
            if cv2.countNonZero(orange_mask) > 5000:
                detected.append({"name": "appelsin", "name_en": "orange", "confidence": 0.3, "source": "color"})

            # Detect red (apple, tomato, pepper)
            red_mask1 = cv2.inRange(hsv, (0, 100, 100), (10, 255, 255))
            red_mask2 = cv2.inRange(hsv, (160, 100, 100), (180, 255, 255))
            red_mask = cv2.bitwise_or(red_mask1, red_mask2)
            if cv2.countNonZero(red_mask) > 5000:
                detected.append({"name": "æble/tomat", "name_en": "apple/tomato", "confidence": 0.3, "source": "color"})

            # Detect green (cucumber, lettuce, broccoli)
            green_mask = cv2.inRange(hsv, (35, 50, 50), (85, 255, 255))
            if cv2.countNonZero(green_mask) > 5000:
                detected.append({"name": "grøntsag", "name_en": "vegetable", "confidence": 0.3, "source": "color"})

        except Exception:
            pass

    return detected


def run_fridge_scanner(auth: AuthTokens | None = None) -> int:
    """Run the fridge scanner to inventory items."""
    print("\n  📷 Fridge Scanner")
    print("  ─────────────────────────────────────────────────────")

    if not SCANNER_AVAILABLE:
        print("\n  Error: Scanner libraries not installed.")
        print("  Run: uv add pyzbar opencv-python Pillow openfoodfacts")
        return 1

    # Check for Raspberry Pi AI Camera
    imx500 = None
    picam2 = None
    use_webcam = True

    if PICAMERA_AVAILABLE:
        try:
            print("  Detected Raspberry Pi - initializing AI Camera...")
            picam2 = Picamera2()

            # Try to load YOLO model for produce detection
            try:
                imx500 = IMX500("/usr/share/imx500-models/imx500_network_yolov8n_pp.rpk")
                print("  ✓ YOLO model loaded on IMX500")
            except Exception:
                print("  ⚠ YOLO model not available, using basic detection")

            picam2.configure(picam2.create_preview_configuration())
            picam2.start()
            use_webcam = False
            print("  ✓ Raspberry Pi AI Camera ready")
        except Exception as e:
            print(f"  ⚠ Could not initialize Pi Camera: {e}")
            print("  Falling back to webcam...")
            use_webcam = True

    if use_webcam:
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("\n  Error: No camera available.")
                print("  Connect a webcam or run on Raspberry Pi with AI Camera.")
                return 1
            print("  ✓ Webcam ready")
        except Exception as e:
            print(f"\n  Error initializing camera: {e}")
            return 1

    print("\n  Instructions:")
    print("  - Point camera at items in your fridge")
    print("  - Barcodes will be scanned automatically")
    print("  - Fruits/vegetables will be detected by AI")
    print("  - Press 'a' to add detected item to inventory")
    print("  - Press 's' to suggest items to buy")
    print("  - Press 'q' to quit")
    print("  ─────────────────────────────────────────────────────\n")

    inventory = load_fridge_inventory()
    scanned_barcodes = set()
    detected_items = []
    last_detection_time = 0

    try:
        while True:
            # Capture frame
            if use_webcam:
                ret, frame = cap.read()
                if not ret:
                    continue
            else:
                frame = picam2.capture_array()

            current_time = time.time()

            # Scan barcodes
            barcodes = scan_barcodes_from_image(frame)
            for barcode in barcodes:
                if barcode not in scanned_barcodes:
                    scanned_barcodes.add(barcode)
                    print(f"  🔍 Barcode detected: {barcode}")

                    product = lookup_barcode(barcode)
                    if product:
                        print(f"     ✓ Found: {product['name']} ({product['brand']})")
                        detected_items.append(product)

                        # Auto-add to inventory
                        existing = next((i for i in inventory["items"] if i.get("barcode") == barcode), None)
                        if existing:
                            existing["count"] = existing.get("count", 1) + 1
                            print(f"     Updated count: {existing['count']}")
                        else:
                            inventory["items"].append({
                                "barcode": barcode,
                                "name": product["name"],
                                "brand": product.get("brand", ""),
                                "count": 1,
                                "added": time.strftime("%Y-%m-%d %H:%M"),
                                "source": "barcode"
                            })
                            print(f"     Added to inventory!")
                        save_fridge_inventory(inventory)
                    else:
                        print(f"     ⚠ Product not found in database")

            # Detect produce (throttle to every 2 seconds)
            if current_time - last_detection_time > 2:
                produce = detect_produce_from_image(frame, imx500)
                for item in produce:
                    if item["confidence"] > 0.5:
                        print(f"  🥬 Detected: {item['name']} (confidence: {item['confidence']:.0%})")
                last_detection_time = current_time

            # Show frame with overlays
            display = frame.copy()

            # Draw barcode boxes
            if SCANNER_AVAILABLE:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
                for barcode in pyzbar.decode(gray):
                    pts = barcode.polygon
                    if pts:
                        pts = [(p.x, p.y) for p in pts]
                        cv2.polylines(display, [cv2.convexHull(cv2.array(pts, dtype="int32").reshape((-1, 1, 2)))], True, (0, 255, 0), 2)

            # Show inventory count
            cv2.putText(display, f"Inventory: {len(inventory['items'])} items", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(display, "Press 'q' to quit, 's' to suggest shopping", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            cv2.imshow("Fridge Scanner", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                # Suggest items to buy based on what's running low
                print("\n  📋 Suggested items to add to grocery list:")
                for item in inventory["items"]:
                    if item.get("count", 1) <= 1:
                        print(f"     - {item['name']} (running low)")
                print()

    except KeyboardInterrupt:
        print("\n  Stopped scanning.")
    finally:
        if use_webcam:
            cap.release()
        elif picam2:
            picam2.stop()
        cv2.destroyAllWindows()

    # Update last scan time
    inventory["last_scan"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_fridge_inventory(inventory)

    print(f"\n  ✓ Inventory saved: {len(inventory['items'])} items")
    return 0


def cmd_fridge_show() -> int:
    """Show current fridge inventory."""
    inventory = load_fridge_inventory()

    print("\n  🧊 Fridge Inventory")
    print("  ─────────────────────────────────────────────────────")

    if not inventory["items"]:
        print("  Your fridge inventory is empty.")
        print("  Run 'scan' to start scanning items.")
        return 0

    print(f"  Last scan: {inventory.get('last_scan', 'Never')}")
    print(f"  Total items: {len(inventory['items'])}\n")

    for item in inventory["items"]:
        name = item.get("name", "Unknown")
        brand = item.get("brand", "")
        count = item.get("count", 1)
        added = item.get("added", "")
        source = item.get("source", "")

        brand_str = f" ({brand})" if brand else ""
        print(f"  • {name}{brand_str} x{count}")
        if added:
            print(f"    Added: {added} [{source}]")

    print("  ─────────────────────────────────────────────────────\n")
    return 0


def cmd_fridge_clear() -> int:
    """Clear fridge inventory."""
    inventory = load_fridge_inventory()
    count = len(inventory["items"])
    inventory["items"] = []
    save_fridge_inventory(inventory)
    print(f"  Cleared {count} items from fridge inventory.")
    return 0


def cmd_fridge_suggest(auth: AuthTokens) -> int:
    """Suggest grocery items based on fridge contents using AI."""
    if not ANTHROPIC_AVAILABLE:
        print("  Error: Anthropic not available for AI suggestions.")
        return 1

    api_key = get_anthropic_api_key()
    if not api_key:
        print("  Error: ANTHROPIC_API_KEY not configured.")
        return 1

    inventory = load_fridge_inventory()
    grocery_list = load_grocery_list()

    if not inventory["items"]:
        print("  Fridge inventory is empty. Run 'scan' first.")
        return 1

    # Build context
    fridge_items = ", ".join(item["name"] for item in inventory["items"])
    list_items = ", ".join(item["name"] for item in grocery_list["items"]) if grocery_list["items"] else "empty"

    print("\n  🤖 Analyzing fridge contents and suggesting items...\n")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Based on my fridge contents and current grocery list, suggest what I should buy.

Fridge contents: {fridge_items}
Current grocery list: {list_items}
Budget: {grocery_list['budget']:.2f} kr

Please suggest:
1. Items that would complement what I have (for complete meals)
2. Staples that might be running low
3. Fresh items that need regular replenishment

Keep suggestions practical for a Danish grocery store (nemlig.com).
Format as a simple bullet list with item names in Danish."""
        }],
        system="You are a helpful Danish grocery shopping assistant. Give practical, concise suggestions."
    )

    print("  Suggestions based on your fridge:")
    print("  ─────────────────────────────────────────────────────")
    for block in response.content:
        if hasattr(block, "text"):
            for line in block.text.split("\n"):
                print(f"  {line}")
    print("  ─────────────────────────────────────────────────────\n")

    return 0


def interactive_mode(auth: AuthTokens, username: str) -> int:
    """Run interactive REPL mode."""
    print_welcome(username)

    # Set up tab completion
    if readline is not None:
        completer = NemligCompleter()
        readline.set_completer(completer.complete)
        readline.set_completer_delims(" ")

        # macOS uses libedit which needs different binding syntax
        if readline.__doc__ and "libedit" in readline.__doc__:
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

    # Show quick help
    print("    Commands: search <query> | list | plan | basket | help | quit\n")

    while True:
        try:
            cmd = input("  nemlig> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n    Goodbye! 👋\n")
            return 0

        if not cmd:
            continue

        parts = cmd.split()
        command = parts[0].lower()

        if command in ("quit", "exit", "q"):
            print("\n    Goodbye! 👋\n")
            return 0

        elif command == "help":
            print("""
    Available commands:
    ─────────────────────────────────────────────────────
    search <query>      Search for products
    details <id>        Show product details
    list                Show your grocery list
    list add <query>    Add product to list (search by name)
    list remove <id>    Remove product from list
    list clear          Clear grocery list
    list budget [amt]   Show/set budget
    list sync           Push list to nemlig basket
    basket              Show nemlig basket
    plan                🤖 AI meal planner (interactive chat)
    import              📋 Import recipes from Google Form
    scan                📷 Scan fridge with camera
    fridge              🧊 View fridge inventory
    fridge suggest      🤖 AI suggestions based on fridge
    fridge clear        Clear fridge inventory
    help                Show this help
    quit                Exit
    ─────────────────────────────────────────────────────
""")

        elif command == "plan":
            meal_plan_chat(auth)

        elif command == "import":
            process_form_recipes(auth)

        elif command == "scan":
            run_fridge_scanner(auth)

        elif command == "fridge":
            if len(parts) > 1:
                subcmd = parts[1].lower()
                if subcmd == "clear":
                    cmd_fridge_clear()
                elif subcmd == "suggest":
                    cmd_fridge_suggest(auth)
                else:
                    cmd_fridge_show()
            else:
                cmd_fridge_show()

        elif command == "search" and len(parts) > 1:
            query = " ".join(parts[1:])
            spinner = Spinner(f"Searching for '{query}'")
            spinner.start()
            products = search_products(auth, query, limit=10)
            if not products:
                spinner.stop(f"No products found for '{query}'")
            else:
                spinner.stop(f"Found {len(products)} products")
                print()
                for p in products:
                    price = p.get("Price", 0)
                    name = p.get("Name", "Unknown")
                    brand = p.get("Brand", "")
                    pid = p.get("Id", "")
                    available = p.get("Availability", {}).get("IsAvailableInStock", False)
                    stock = "In stock" if available else "OUT OF STOCK"
                    print(f"  [{pid}] {name} ({brand}) - {price:.2f} kr [{stock}]")
            print()

        elif command == "details" and len(parts) > 1:
            product_id = parts[1]
            spinner = Spinner(f"Loading product {product_id}")
            spinner.start()
            try:
                product = get_product_details(auth, product_id)
                spinner.stop("Product loaded")
                print()
                print(format_product_details(product))
                print()
            except ProductNotFoundError as e:
                spinner.stop()
                print(f"Error: {e}\n")

        elif command == "list":
            if len(parts) == 1:
                # Show list
                data = load_grocery_list()
                print(format_list_summary(data["items"], data["budget"]))
                print()
            elif parts[1] == "add" and len(parts) > 2:
                query = " ".join(parts[2:])
                spinner = Spinner(f"Searching for '{query}'")
                spinner.start()
                products = search_products(auth, query, limit=10)
                if not products:
                    spinner.stop(f"No products found for '{query}'")
                else:
                    spinner.stop(f"Found {len(products)} products")
                    print()
                    for i, p in enumerate(products, 1):
                        price = p.get("Price", 0)
                        name = p.get("Name", "Unknown")
                        brand = p.get("Brand", "")
                        available = p.get("Availability", {}).get("IsAvailableInStock", False)
                        stock = "In stock" if available else "OUT OF STOCK"
                        print(f"  [{i}] {name} ({brand}) - {price:.2f} kr [{stock}]")
                    print()
                    try:
                        choice = input("  Enter number to add (or 'q' to cancel): ").strip()
                        if choice.lower() != 'q':
                            idx = int(choice) - 1
                            if 0 <= idx < len(products):
                                product = products[idx]
                                data = load_grocery_list()
                                product_id = product.get("Id")
                                # Check if already in list
                                found = False
                                for item in data["items"]:
                                    if item["product_id"] == product_id:
                                        item["quantity"] += 1
                                        item["unit_price"] = product.get("Price", item["unit_price"])
                                        found = True
                                        break
                                if not found:
                                    data["items"].append({
                                        "product_id": product_id,
                                        "name": product.get("Name", "Unknown"),
                                        "brand": product.get("Brand", ""),
                                        "quantity": 1,
                                        "unit_price": product.get("Price", 0),
                                    })
                                save_grocery_list(data)
                                print(f"\n  ✓ Added: {product.get('Name')}")
                                print(format_list_summary(data["items"], data["budget"]))
                    except (ValueError, KeyboardInterrupt):
                        print("Cancelled.")
                    print()
            elif parts[1] == "remove" and len(parts) > 2:
                product_id = parts[2]
                data = load_grocery_list()
                for i, item in enumerate(data["items"]):
                    if item["product_id"] == product_id:
                        removed = data["items"].pop(i)
                        save_grocery_list(data)
                        print(f"  ✓ Removed: {removed['name']}\n")
                        break
                else:
                    print(f"  Product {product_id} not in list\n")
            elif parts[1] == "clear":
                data = load_grocery_list()
                count = len(data["items"])
                data["items"] = []
                save_grocery_list(data)
                print(f"  ✓ Cleared {count} items\n")
            elif parts[1] == "budget":
                data = load_grocery_list()
                if len(parts) > 2:
                    try:
                        data["budget"] = float(parts[2])
                        save_grocery_list(data)
                        print(f"  ✓ Budget set to {data['budget']:.2f} kr\n")
                    except ValueError:
                        print("  Invalid amount\n")
                else:
                    total = sum(item.get("unit_price", 0) * item.get("quantity", 1) for item in data["items"])
                    budget = data["budget"]
                    remaining = budget - total
                    print(f"  Budget: {budget:.2f} kr | Used: {total:.2f} kr | Remaining: {remaining:.2f} kr")

                    # Progress bar
                    if budget > 0:
                        bar_width = 30
                        pct = (total / budget) * 100
                        filled = min(int((total / budget) * bar_width), bar_width)
                        empty = bar_width - filled

                        if pct > 100:
                            bar = "\033[91m" + "█" * bar_width + "\033[0m"
                            status = "\033[91mOVER BUDGET!\033[0m"
                        elif pct > 90:
                            bar = "\033[91m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"
                            status = f"\033[91m{pct:.0f}%\033[0m"
                        elif pct > 70:
                            bar = "\033[93m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"
                            status = f"\033[93m{pct:.0f}%\033[0m"
                        else:
                            bar = "\033[92m" + "█" * filled + "\033[90m" + "░" * empty + "\033[0m"
                            status = f"\033[92m{pct:.0f}%\033[0m"

                        print(f"  [{bar}] {status}\n")
            elif parts[1] == "sync":
                data = load_grocery_list()
                if not data["items"]:
                    print("  List is empty\n")
                else:
                    print(f"  Syncing {len(data['items'])} items...")
                    for item in data["items"]:
                        try:
                            add_to_basket(auth, item["product_id"], item["quantity"])
                            print(f"    ✓ {item['name']} x{item['quantity']}")
                        except Exception as e:
                            print(f"    ✗ {item['name']} - {e}")
                    print("  Done! Use 'basket' to view.\n")
            else:
                print("  Usage: list | list add <query> | list remove <id> | list clear | list budget [amt] | list sync\n")

        elif command == "basket":
            spinner = Spinner("Loading basket")
            spinner.start()
            basket = get_basket(auth)
            spinner.stop("Basket loaded")
            lines = basket.get("Lines", [])
            if not lines:
                print("  Basket is empty\n")
            else:
                print(f"\n  Basket ({len(lines)} items):\n")
                total = 0
                for line in lines:
                    print(f"  {format_basket_line(line)}")
                    total += line.get("Price", 0)
                print(f"\n  Total: {total:.2f} kr\n")

        else:
            print("  Unknown command. Type 'help' for available commands.\n")


def main():
    # Windows terminals and redirected files may use a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    # Do not let argparse echo a rejected password argument into logs.
    if any(arg.startswith("-p") or (
            arg.startswith("--") and len(arg.partition("=")[0]) > 2
            and "--password".startswith(arg.partition("=")[0]))
           for arg in sys.argv[1:]):
        print("Password arguments are disabled; use the hidden terminal prompt.", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(
        description=LOGO.format(version=VERSION),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
        epilog="""
Credentials:
  Username: -u, NEMLIG_USER, or ~/.config/nemlig/login.json.
  Password: hidden interactive prompt; never saved.

  Config file format:
    {"username": "user@example.com"}

Examples:
  %(prog)s search "cocio"
  %(prog)s list add "mælk"
  %(prog)s list
  %(prog)s list sync
  %(prog)s basket
        """
    )

    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("-u", "--username", help="Nemlig.com email/username (overrides config file)")

    subparsers = parser.add_subparsers(dest="command", required=False)

    # Search command
    search_parser = subparsers.add_parser("search", help="Search for products")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-l", "--limit", type=int, default=10, help="Max results (default: 10)")

    # Details command
    details_parser = subparsers.add_parser("details", help="Show detailed product info")
    details_parser.add_argument("product_id", help="Product ID to view")

    # Basket command
    subparsers.add_parser("basket", help="Show current basket")

    # Add command
    add_parser = subparsers.add_parser("add", help="Set product quantity in basket")
    add_parser.add_argument("product_id", help="Product ID to add")
    add_parser.add_argument(
        "-q",
        "--quantity",
        type=int,
        default=1,
        help="Quantity to end up with, not to add (default: 1). Use 0 to remove the product",
    )

    # History command
    history_parser = subparsers.add_parser("history", help="Show order history")
    history_parser.add_argument("order_id", nargs="?", type=int, help="Order ID for details (optional)")
    history_parser.add_argument("-l", "--limit", type=int, default=10, help="Max orders to show (default: 10)")

    # List command with subcommands
    list_parser = subparsers.add_parser("list", help="Manage grocery list")
    list_sub = list_parser.add_subparsers(dest="list_cmd")

    # list (show) - default when no subcommand
    list_sub.add_parser("show", help="Show current grocery list")

    # list add
    list_add_parser = list_sub.add_parser("add", help="Add product to list")
    list_add_parser.add_argument("product_id", help="Product ID or search term")
    list_add_parser.add_argument("-q", "--quantity", type=int, default=1, help="Quantity (default: 1)")

    # list remove
    list_remove_parser = list_sub.add_parser("remove", help="Remove product from list")
    list_remove_parser.add_argument("product_id", help="Product ID to remove")

    # list clear
    list_sub.add_parser("clear", help="Clear all items from list")

    # list budget
    list_budget_parser = list_sub.add_parser("budget", help="Show or set budget")
    list_budget_parser.add_argument("amount", nargs="?", type=float, help="New budget amount in kr")

    # list sync
    list_sub.add_parser("sync", help="Push list items to nemlig basket")

    # Plan command (AI meal planning)
    subparsers.add_parser("plan", help="🤖 AI meal planner - build grocery list from recipes")

    # Import command (Google Form recipes)
    import_parser = subparsers.add_parser("import", help="📋 Import recipes from Google Form/Sheet")
    import_parser.add_argument("spreadsheet_id", nargs="?", help="Google Spreadsheet ID (from URL)")
    import_parser.add_argument("--setup", action="store_true", help="Run interactive setup")

    # Scan command (fridge camera scanner)
    subparsers.add_parser("scan", help="📷 Scan fridge with camera (barcode + AI detection)")

    # Fridge command (inventory management)
    fridge_parser = subparsers.add_parser("fridge", help="🧊 Manage fridge inventory")
    fridge_sub = fridge_parser.add_subparsers(dest="fridge_cmd")
    fridge_sub.add_parser("show", help="Show fridge inventory (default)")
    fridge_sub.add_parser("clear", help="Clear fridge inventory")
    fridge_sub.add_parser("suggest", help="AI suggestions based on fridge contents")

    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    # Handle list commands that don't require authentication
    if args.command == "list":
        list_cmd = args.list_cmd
        # Commands that don't need auth
        if list_cmd is None or list_cmd == "show":
            return cmd_list_show(args)
        elif list_cmd == "remove":
            return cmd_list_remove(args)
        elif list_cmd == "clear":
            return cmd_list_clear(args)
        elif list_cmd == "budget":
            return cmd_list_budget(args)
        # Commands that need auth fall through to below

    # Handle import --setup (no auth needed)
    if args.command == "import" and args.setup:
        return cmd_import_setup()

    # Handle fridge commands that don't need auth
    if args.command == "fridge":
        fridge_cmd = args.fridge_cmd
        if fridge_cmd is None or fridge_cmd == "show":
            return cmd_fridge_show()
        elif fridge_cmd == "clear":
            return cmd_fridge_clear()
        # suggest needs auth, falls through

    # Load credentials: config file first, CLI overrides
    try:
        config_creds = load_config_credentials()
    except (json.JSONDecodeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    username = args.username or os.environ.get("NEMLIG_USER") or config_creds.get("username")

    if not username:
        print(
            "Error: Provide your username with -u, NEMLIG_USER, or login.json.",
            file=sys.stderr,
        )
        return 1

    try:
        # Authenticate
        password = read_password()
        try:
            auth = login(username, password)
        finally:
            del password

        # Interactive mode if no command given
        if args.command is None:
            return interactive_mode(auth, username)

        # Single command mode - show welcome banner
        print_welcome(username)

        # Execute command
        if args.command == "search":
            return cmd_search(auth, args)
        elif args.command == "details":
            return cmd_details(auth, args)
        elif args.command == "basket":
            return cmd_basket(auth, args)
        elif args.command == "add":
            return cmd_add(auth, args)
        elif args.command == "history":
            return cmd_history(auth, args)
        elif args.command == "list":
            # List commands that require auth
            if args.list_cmd == "add":
                return cmd_list_add(auth, args)
            elif args.list_cmd == "sync":
                return cmd_list_sync(auth, args)
        elif args.command == "plan":
            return meal_plan_chat(auth)
        elif args.command == "import":
            return process_form_recipes(auth, args.spreadsheet_id)
        elif args.command == "scan":
            return run_fridge_scanner(auth)
        elif args.command == "fridge":
            # Only suggest needs auth (show/clear handled above)
            if args.fridge_cmd == "suggest":
                return cmd_fridge_suggest(auth)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            return 1

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        print(f"HTTP Error: {status}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Login or operation cancelled.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
