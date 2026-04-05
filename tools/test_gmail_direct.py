import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

SMTP_SERVER = os.getenv("MAIL_SERVER")
SMTP_PORT = int(os.getenv("MAIL_PORT", 587))
SMTP_USERNAME = os.getenv("MAIL_USERNAME")
SMTP_PASSWORD = os.getenv("MAIL_PASSWORD")

print(f"Connecting to {SMTP_SERVER}:{SMTP_PORT} as {SMTP_USERNAME}...")

try:
    # 1. Connect
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.set_debuglevel(1)  # Show detailed network communication
    server.ehlo()

    # 2. Start TLS
    if os.getenv("MAIL_USE_TLS") == "True":
        print("Starting TLS...")
        server.starttls()
        server.ehlo()

    # 3. Login
    print("Logging in...")
    server.login(SMTP_USERNAME, SMTP_PASSWORD)
    print("Login success!")

    # 4. Send
    msg = MIMEText("This is a test email from Python.")
    msg["Subject"] = "Undocs Test"
    msg["From"] = SMTP_USERNAME
    msg["To"] = SMTP_USERNAME

    server.sendmail(SMTP_USERNAME, [SMTP_USERNAME], msg.as_string())
    print("Email sent!")
    server.quit()

except Exception as e:
    print("\n❌ FAILURE:")
    print(e)
