import os
import json
import shutil
import keyring
from platformdirs import user_data_dir
from cryptography.fernet import Fernet

SERVICE_NAME = "OtiumStudentHub"
KEY_ACCOUNT = "MasterEncryptionKey"


def get_app_dir():
    app_dir = os.path.join(os.path.expanduser("~"), ".otium_app")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


# --- Explicit File Paths ---
CREDENTIALS_FILE = os.path.join(get_app_dir(), "credentials.bin")
SESSION_FILE = os.path.join(get_app_dir(), "storage_state.json")
PREFERENCES_FILE = os.path.join(get_app_dir(), "preferences.json")
PLAYWRIGHT_USER_DATA_DIR = os.path.join(get_app_dir(), "user_data")


def _get_or_create_master_key():
    secret = keyring.get_password(SERVICE_NAME, KEY_ACCOUNT)
    if not secret:
        new_key = Fernet.generate_key().decode('utf-8')
        keyring.set_password(SERVICE_NAME, KEY_ACCOUNT, new_key)
        return new_key.encode('utf-8')
    return secret.encode('utf-8')


def save_credentials(email: str, password: str, secret_key: str):
    fernet = Fernet(_get_or_create_master_key())
    payload = {"email": email, "password": password, "totp_secret": secret_key}
    encrypted = fernet.encrypt(json.dumps(payload).encode('utf-8'))

    with open(CREDENTIALS_FILE, "wb") as f:
        f.write(encrypted)


def load_credentials():
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    try:
        fernet = Fernet(_get_or_create_master_key())
        with open(CREDENTIALS_FILE, "rb") as f:
            return json.loads(fernet.decrypt(f.read()).decode('utf-8'))
    except Exception:
        return None


# --- USER PREFERENCES (Tab Order & Course Order) ---
def load_preferences() -> dict:
    default_prefs = {
        "tab_order": ["In Progress", "Past", "Future", "All"],
        "course_orders": {}  # e.g., {"In Progress": ["CSP1123", "CMT1134"]}
    }
    if not os.path.exists(PREFERENCES_FILE):
        return default_prefs
    try:
        with open(PREFERENCES_FILE, "r") as f:
            data = json.load(f)
            # Guarantee default tab keys exist
            if "tab_order" not in data:
                data["tab_order"] = default_prefs["tab_order"]
            if "course_orders" not in data:
                data["course_orders"] = {}
            return data
    except Exception:
        return default_prefs


def save_preferences(prefs: dict):
    try:
        with open(PREFERENCES_FILE, "w") as f:
            json.dump(prefs, f, indent=2)
            print("💾 Preferences saved to preferences.json")
    except Exception as e:
        print(f"⚠️ Failed to save preferences: {e}")


def clear_all_saved_data():
    """Completely deletes saved sessions, encrypted credentials, preferences, keyring entries, and browser caches."""

    for file_path in [CREDENTIALS_FILE, SESSION_FILE, PREFERENCES_FILE]:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"🗑️ Removed {os.path.basename(file_path)}")
            except Exception as e:
                print(f"⚠️ Failed to delete {file_path}: {e}")

    try:
        keyring.delete_password(SERVICE_NAME, KEY_ACCOUNT)
        print("🗑️ Removed keyring encryption password")
    except Exception as e:
        print(f"⚠️ Keyring entry not found or already deleted: {e}")

    if os.path.exists(PLAYWRIGHT_USER_DATA_DIR):
        try:
            shutil.rmtree(PLAYWRIGHT_USER_DATA_DIR)
            print("🗑️ Removed user_data directory")
        except Exception as e:
            print(f"⚠️ Failed to remove browser data dir: {e}")