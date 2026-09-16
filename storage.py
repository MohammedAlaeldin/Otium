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


def clear_all_saved_data():
    """Completely deletes saved sessions, encrypted credentials, keyring entries, and browser caches."""

    # 1. Delete encrypted credentials
    if os.path.exists(CREDENTIALS_FILE):
        try:
            os.remove(CREDENTIALS_FILE)
            print("🗑️ Removed credentials.bin")
        except Exception as e:
            print(f"⚠️ Failed to delete {CREDENTIALS_FILE}: {e}")

    # 2. Delete Master Key from OS Keyring
    try:
        keyring.delete_password(SERVICE_NAME, KEY_ACCOUNT)
        print("🗑️ Removed keyring encryption password")
    except Exception as e:
        print(f"⚠️ Keyring entry not found or already deleted: {e}")

    # 3. Delete session state file
    if os.path.exists(SESSION_FILE):
        try:
            os.remove(SESSION_FILE)
            print("🗑️ Removed storage_state.json")
        except Exception as e:
            print(f"⚠️ Failed to delete {SESSION_FILE}: {e}")

    # 4. Remove persistent browser user data folder
    if os.path.exists(PLAYWRIGHT_USER_DATA_DIR):
        try:
            shutil.rmtree(PLAYWRIGHT_USER_DATA_DIR)
            print("🗑️ Removed user_data directory")
        except Exception as e:
            print(f"⚠️ Failed to remove browser data dir: {e}")

    # 5. Clear extra local files in root or app directory
    extra_files = ["session.json", "tokens.json", "cookies.json", "storage_state.json"]
    for file in extra_files:
        for path in [file, os.path.join(get_app_dir(), file)]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"🗑️ Removed {path}")
                except Exception as e:
                    print(f"⚠️ Failed to delete {path}: {e}")