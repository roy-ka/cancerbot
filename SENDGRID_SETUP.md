# SendGrid Email Setup

SendGrid free tier: 100 emails/day, perfect for password resets and notifications.

## 1. Create SendGrid Account

1. Go to [sendgrid.com](https://sendgrid.com)
2. Sign up (free account)
3. Verify email
4. Go to Settings → API Keys
5. Create API Key:
   - Name: `cancerbot`
   - Permissions: Mail Send only
   - Click Create & Copy
6. Save the key (you'll only see it once)

## 2. Verify Sender Email

**You need to verify the email address that sends emails.**

Option A: Single Sender (simplest)
1. In SendGrid: Settings → Sender Authentication → Single Sender
2. Click "Create"
3. Fill in:
   - Email: `noreply@your-domain.com` (or any email you own)
   - Name: `CancerBot`
4. Check that email inbox for verification link
5. Click verification link

Option B: Domain Authentication (professional)
1. In SendGrid: Settings → Sender Authentication → Domain
2. Add your domain
3. Follow DNS setup instructions
4. (More steps, but allows any `*@your-domain.com` address)

## 3. Update .env

```bash
# Remove SMTP settings
# SMTP_HOST=
# SMTP_PORT=
# SMTP_USER=
# SMTP_PASSWORD=
# SMTP_FROM=

# Add SendGrid
SENDGRID_API_KEY=SG.xxxxxxxxxxxxx_your_key_here
EMAIL_FROM=noreply@your-domain.com
EMAIL_FROM_NAME=CancerBot
```

## 4. Update Email Utils

Replace `src/utils/email.py`:

```python
import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)

async def send_password_reset_email(to: str, code: str) -> None:
    """Send password reset email via SendGrid."""
    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        logger.warning("SendGrid not configured; skipping password reset email")
        return

    from_email = os.getenv("EMAIL_FROM", "noreply@example.com")
    from_name = os.getenv("EMAIL_FROM_NAME", "CancerBot")

    message = Mail(
        from_email=(from_email, from_name),
        to_emails=to,
        subject="Your CancerBot password reset code",
        html_content=f"""
        <h2>Reset your password</h2>
        <p>Enter this 6-digit code to reset your password. It expires in 15 minutes.</p>
        <h3 style="font-family: monospace; letter-spacing: 0.2em;">{code}</h3>
        <p>If you didn't request this, you can safely ignore this email.</p>
        """,
    )

    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info(f"Password reset email sent to {to}")
    except Exception as e:
        logger.error(f"Failed to send password reset email: {e}")
        raise
```

## 5. Install SendGrid SDK

```bash
pip install sendgrid
```

Update `requirements.txt`:
```
sendgrid>=6.10.0
```

## 6. Test Email

```bash
python3 << 'EOF'
import os
os.environ['SENDGRID_API_KEY'] = 'SG.your_key_here'
os.environ['EMAIL_FROM'] = 'noreply@your-domain.com'
os.environ['EMAIL_FROM_NAME'] = 'CancerBot'

import asyncio
from src.utils.email import send_password_reset_email

asyncio.run(send_password_reset_email('your-email@gmail.com', '123456'))
print("✓ Email sent!")
EOF
```

Check your inbox (check spam folder too).

## 7. Monitor Sends

**SendGrid Dashboard:**
1. Go to Mail Send → Overview
2. See email counts, delivery status, bounces

**Set up activity monitor:**
```bash
# View sent emails in real-time
curl -X GET "https://api.sendgrid.com/v3/mail/send" \
  -H "Authorization: Bearer SG.your_key_here"
```

## 8. Production Checklist

- [ ] Verified sender email in SendGrid
- [ ] API key in `.env` (not in code)
- [ ] Test email sent successfully
- [ ] SENDGRID_API_KEY env var set on Oracle Cloud instance
- [ ] EMAIL_FROM and EMAIL_FROM_NAME configured

## Troubleshooting

**"Invalid email from address"**
- Verify the sender email in SendGrid Settings → Sender Authentication
- It must match EMAIL_FROM in .env

**"Invalid API key"**
- Double-check the key from SendGrid (starts with `SG.`)
- Make sure SENDGRID_API_KEY is set in .env

**"Email not received"**
- Check spam folder
- Check SendGrid dashboard for bounce/drop reasons
- Verify recipient email address

## Upgrade Later

If you hit 100 emails/day limit:
1. SendGrid paid: $9.95/month → unlimited
2. Or switch to Mailgun (5,000/month free)

For now, SendGrid free = no credit card, no limits for password resets.
