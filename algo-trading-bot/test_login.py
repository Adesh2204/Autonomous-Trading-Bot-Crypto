import os
from dotenv import load_dotenv


def run_login_test() -> None:
    import pyotp
    from SmartApi import SmartConnect

    # Load credentials from .env
    load_dotenv()

    api_key = os.getenv("BROKER_API_KEY")
    client_id = os.getenv("BROKER_CLIENT_ID")
    pin = os.getenv("BROKER_PIN")
    totp_secret = os.getenv("BROKER_TOTP_SECRET")

    print("Generating 2FA Token...")
    # Automatically generate the live 6-digit TOTP code
    totp = pyotp.TOTP(totp_secret).now()
    print(f"Current TOTP Code: {totp}")

    print("Attempting to log into Angel One SmartAPI...")
    # Initialize the API
    smartApi = SmartConnect(api_key=api_key)

    # Log in using Client ID, PIN, and the auto-generated TOTP
    login_data = smartApi.generateSession(client_id, pin, totp)

    if login_data.get('status') is True:
        print("✅ SUCCESS! Your bot has successfully logged into your Angel One account!")
        print(f"Auth Token Received: {login_data['data']['jwtToken'][:15]}...")
    else:
        print("❌ LOGIN FAILED. Please check your credentials.")
        print(login_data)


if __name__ == "__main__":
    run_login_test()