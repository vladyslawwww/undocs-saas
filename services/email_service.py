import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app


def send_confirmation_email(user_email, code):
    """
    Sends a 6-digit OTP code to the user
    """
    # --- FAILSAFE PRINT ---
    print("\n" + "=" * 60)
    print(f" 🔐 OTP CODE: {code}")
    print("=" * 60 + "\n")
    # ----------------------

    # 2. Get Config
    smtp_server = current_app.config.get("MAIL_SERVER")
    smtp_port = current_app.config.get("MAIL_PORT")
    smtp_user = current_app.config.get("MAIL_USERNAME")
    smtp_password = current_app.config.get("MAIL_PASSWORD")
    smtp_sender = current_app.config.get("MAIL_DEFAULT_SENDER")

    if not smtp_user or not smtp_password:
        return False

    # 3. Construct Email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Verification Code: {code}"
    msg["From"] = smtp_sender
    msg["To"] = user_email

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
        <h2>Welcome to Undocs.ai</h2>
        <p>Please enter this code to verify your account:</p>
        <h1 style="background: #f3f4f6; padding: 10px; display: inline-block; letter-spacing: 5px; color: #333; border: 1px dashed #ccc;">{code}</h1>
        <p>This code expires in 15 minutes.</p>
        <p style="color: #666; font-size: 12px;">If you did not request this, please ignore this email.</p>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_content, "html"))

    # 4. Send
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.ehlo()
        if current_app.config.get("MAIL_USE_TLS"):
            server.starttls()
            server.ehlo()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_sender, [user_email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f" >> EMAIL FAILED: {e}")
        return False
