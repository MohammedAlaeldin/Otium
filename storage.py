import os, json, keyring
from platformdirs import user_data_dir
from cryptography.fernet import Fernet

SERVICE_NAME = "OtiumStudentHub"
KEY_ACCOUNT = "MasterEncryptionKey"


def get_app_dir():
    app_dir = os.path.join(os.path.expanduser("~"), ".ebwise_app")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


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

    with open(os.path.join(get_app_dir(), "credentials.bin"), "wb") as f:
        f.write(encrypted)


def load_credentials():
    file_path = os.path.join(get_app_dir(), "credentials.bin")
    if not os.path.exists(file_path):
        return None
    try:
        fernet = Fernet(_get_or_create_master_key())
        with open(file_path, "rb") as f:
            return json.loads(fernet.decrypt(f.read()).decode('utf-8'))
    except Exception:
        return None

SESSION_FILE = os.path.join(get_app_dir(), "session.json")

def clear_all_saved_data():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
    # 2. Delete session.json if stored in working directory or app directory
    for session_path in ["session.json", os.path.join(get_app_dir(), "session.json")]:
        if os.path.exists(session_path):
            try:
                os.remove(session_path)
                print("🗑️ Removed active session cookies.")
            except Exception as e:
                print(f"⚠️ Failed to delete session file: {e}")