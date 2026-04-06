import os
import threading

import resend

# Initialize Resend with your API Key
resend.api_key = os.getenv("RESEND_API_KEY")


def send_confirmation_email(user_email, code):
    """
    Sends a 6-digit OTP code to the user via Resend API in a background thread
    to prevent blocking the main process and saving memory.
    """
    # 1. ALWAYS print to console first (fail-safe for testing)
    print(f"\n[INTERNAL] 🔐 OTP CODE FOR {user_email}: {code}\n")

    if not resend.api_key:
        print("⚠️ RESEND_API_KEY missing. Email not sent via API.")
        return False

    def _send_action():
        try:
            params = {
                "from": os.getenv("MAIL_DEFAULT_SENDER", "onboarding@resend.dev"),
                "to": [user_email],
                "subject": f"Your Verification Code: {code}",
                "html": f"""
                <div style="font-family: sans-serif; text-align: center; padding: 40px; border: 1px solid #eee; border-radius: 10px;">
                    <h2 style="color: #111;">Welcome to Undocs.ai</h2>
                    <p style="color: #666;">Enter this code to verify your account:</p>
                    <h1 style="background: #f4f4f4; padding: 20px; display: inline-block; letter-spacing: 10px; border-radius: 8px;">{code}</h1>
                    <p style="color: #999; font-size: 12px; margin-top: 20px;">Expires in 15 minutes.</p>
                </div>
                """,
            }
            resend.Emails.send(params)
            print(f"✅ Email sent successfully to {user_email}")
        except Exception as e:
            print(f"❌ Resend Error: {e}")

    # 2. Run in a background thread so the Flask worker can return 'Redirect' immediately
    threading.Thread(target=_send_action).start()
    return True
