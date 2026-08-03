# app/services/email_service.py
"""
Sends transactional emails via Brevo (formerly Sendinblue) HTTP API.
Works on Railway — no SMTP ports needed, no firewall issues.

Required env vars:
  BREVO_API_KEY                 Your Brevo API key (starts with xkeysib-)
  SMTP_FROM_NAME                Display name e.g. HoBS
  SMTP_USER                     Your verified sender email in Brevo
  APP_URL                       https://hobs.altekflo.xyz
  HOBS_SUPPORT_WHATSAPP     e.g. 2349012345678
"""

import os
import logging
import httpx
from html import escape as _html_escape

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _cfg():
    return {
        "api_key":    os.getenv("BREVO_API_KEY", ""),
        # FIX: was SMTP_FROM_NAME / SMTP_USER — Railway vars are BREVO_SENDER_NAME / BREVO_SENDER_EMAIL
        "from_name":  os.getenv("BREVO_SENDER_NAME", os.getenv("SMTP_FROM_NAME", "HoBS")),
        "from_email": os.getenv("BREVO_SENDER_EMAIL", os.getenv("SMTP_USER", "")),
        "app_url":    os.getenv("APP_URL", "https://hobs.altekflo.xyz"),
        # Base URL of the FastAPI backend itself (hobs.shaddies.space), as opposed
        # to app_url (the Next.js frontend, hobs.altekflo.xyz). Needed for links to
        # pages that main.py serves directly, e.g. /apply/whatsapp-number/{token}
        # — that route only exists on the backend, not on the frontend domain.
        "api_base_url": os.getenv("API_BASE_URL", "https://hobs.shaddies.space"),
        "support_wa": os.getenv("HOBS_SUPPORT_WHATSAPP", ""),
    }


async def send_email(to_email: str, subject: str, html: str, text: str) -> bool:
    cfg = _cfg()
    if not cfg["api_key"] or not cfg["from_email"]:
        logger.warning("Brevo not configured — email to %s skipped", to_email)
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                BREVO_URL,
                json={
                    "sender":      {"name": cfg["from_name"], "email": cfg["from_email"]},
                    "to":          [{"email": to_email}],
                    "subject":     subject,
                    "htmlContent": html,
                    "textContent": text,
                },
                headers={
                    "api-key":      cfg["api_key"],
                    "Content-Type": "application/json",
                },
            )
        if res.status_code in (200, 201):
            logger.info("Email sent to %s: %s", to_email, subject)
            return True
        logger.error("Brevo error %s: %s", res.status_code, res.text)
        return False
    except Exception as e:
        logger.error("Email send failed to %s: %s", to_email, e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 1. VERIFICATION EMAIL
#    Sent immediately on registration. Contains: 6-digit code, Merchant ID,
#    Store ID, and confirmation that their WhatsApp number was received.
# ─────────────────────────────────────────────────────────────────────────────

async def send_verification_email(
    to_email: str,
    merchant_name: str,
    merchant_id: str,
    token: str,
    client_id: str = None,
    whatsapp_number: str = None,
) -> bool:
    """
    Registration verification email.
    - token is a 6-digit numeric code
    - client_id is the auto-created Store ID
    - whatsapp_number is shown back to confirm it was received (optional)
    """
    subject = "Your HoBS verification code"

    store_id_block = (
        f'''<div style="background:#F5F4F0;border-radius:8px;padding:10px 20px;margin-bottom:12px">
            <div style="font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
              color:#bbb;margin-bottom:2px">Store ID</div>
            <div style="font-size:18px;font-weight:700;color:#111;letter-spacing:.04em">{client_id}</div>
            <div style="font-size:12px;color:#999;margin-top:2px">Save this — you may need it when contacting support.</div>
          </div>'''
        if client_id else ""
    )

    wa_block = (
        f'''<div style="background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;
              padding:10px 20px;margin-bottom:12px">
            <div style="font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
              color:#16A34A;margin-bottom:2px">WhatsApp Number Received</div>
            <div style="font-size:16px;font-weight:600;color:#111">+{whatsapp_number}</div>
            <div style="font-size:12px;color:#15803D;margin-top:2px">
              We'll begin activation within 24 hours. Watch your email.
            </div>
          </div>'''
        if whatsapp_number else
        '''<div style="background:#FFF8E1;border:1px solid #FCD34D;border-radius:8px;
              padding:10px 20px;margin-bottom:12px">
            <div style="font-size:12px;color:#92400E;line-height:1.5">
              ⚠️ No WhatsApp number submitted. You can add one from your dashboard settings
              before we begin onboarding.
            </div>
          </div>'''
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:32px 40px 28px;text-align:center">
          <div style="display:inline-block;width:44px;height:44px;background:#25D366;
            border-radius:11px;line-height:44px;text-align:center;font-size:22px;margin-bottom:12px">🛒</div>
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:5px;
            letter-spacing:.08em;text-transform:uppercase">WhatsApp Commerce</div>
        </td></tr>
        <tr><td style="padding:40px 40px 32px">
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111;letter-spacing:-.02em">
            Welcome, {merchant_name}! 👋
          </h1>
          <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6">
            Enter the code below to verify your email and activate your account.
          </p>

          <!-- Verification code -->
          <div style="background:#F5F4F0;border-radius:10px;padding:20px 24px;margin-bottom:12px;text-align:center">
            <div style="font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
              color:#999;margin-bottom:10px">Verification code</div>
            <div style="font-size:40px;font-weight:800;color:#111;letter-spacing:.18em">{token}</div>
            <div style="font-size:12px;color:#aaa;margin-top:8px">Expires in 30 minutes</div>
          </div>

          <!-- Merchant ID -->
          <div style="background:#F5F4F0;border-radius:10px;padding:14px 20px;margin-bottom:12px">
            <div style="font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
              color:#999;margin-bottom:4px">Your Merchant ID</div>
            <div style="font-size:22px;font-weight:700;color:#111;letter-spacing:.05em">{merchant_id}</div>
            <div style="font-size:12px;color:#999;margin-top:4px">Save this — you'll use it to sign in.</div>
          </div>

          {store_id_block}
          {wa_block}

          <p style="margin:16px 0 0;font-size:13px;color:#aaa;text-align:center;line-height:1.6">
            Sign in to your dashboard and enter the code when prompted.<br>
            If you didn't create this account, you can ignore this email.
          </p>
        </td></tr>
        <tr><td style="padding:20px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS by AltekFlo · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    wa_text = f"WhatsApp number received: +{whatsapp_number}" if whatsapp_number else "No WhatsApp number submitted."
    store_text = f"Your Store ID: {client_id}" if client_id else ""

    text = f"""Welcome to HoBS, {merchant_name}!

Your verification code: {token}
(Expires in 30 minutes)

Your Merchant ID: {merchant_id}
{store_text}
{wa_text}

Sign in at your dashboard and enter the code when prompted.
"""
    return await send_email(to_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# 2. WELCOME EMAIL
#    Sent after email verification is confirmed.
# ─────────────────────────────────────────────────────────────────────────────

async def send_welcome_email(
    to_email: str,
    merchant_name: str,
    merchant_id: str,
) -> bool:
    cfg           = _cfg()
    dashboard_url = f"{cfg['app_url']}/dashboard"
    first_name    = merchant_name.split()[0]
    subject       = f"Welcome to HoBS, {first_name}! Here's how to get started."

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:32px 40px 28px;text-align:center">
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:5px;
            letter-spacing:.08em;text-transform:uppercase">WhatsApp Commerce</div>
        </td></tr>
        <tr><td style="padding:40px 40px 32px">
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111">
            You're in, {first_name}! 🎉
          </h1>
          <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6">
            Your HoBS account is verified and your store is ready. Here's what to do now
            while your WhatsApp number is being set up.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:0 0 10px">
              <table width="100%" cellpadding="0" cellspacing="0"
                style="background:#F0FDF4;border:1px solid #86EFAC;border-radius:10px;padding:14px 16px">
                <tr>
                  <td width="32" valign="top" style="padding-right:12px">
                    <div style="width:26px;height:26px;background:#16A34A;border-radius:50%;
                      text-align:center;line-height:26px;color:#fff;font-weight:700;font-size:13px">1</div>
                  </td>
                  <td>
                    <div style="font-weight:600;font-size:14px;color:#111">Log in and add your products</div>
                    <div style="font-size:13px;color:#555;margin-top:3px;line-height:1.5">
                      Head to your dashboard and add everything you sell — name, price, stock.
                      This is what your customers will browse and order from.
                    </div>
                  </td>
                </tr>
              </table>
            </td></tr>
            <tr><td style="padding:0 0 10px">
              <table width="100%" cellpadding="0" cellspacing="0"
                style="background:#F5F4F0;border-radius:10px;padding:14px 16px">
                <tr>
                  <td width="32" valign="top" style="padding-right:12px">
                    <div style="width:26px;height:26px;background:#555;border-radius:50%;
                      text-align:center;line-height:26px;color:#fff;font-weight:700;font-size:13px">2</div>
                  </td>
                  <td>
                    <div style="font-weight:600;font-size:14px;color:#111">Set your operator number</div>
                    <div style="font-size:13px;color:#777;margin-top:3px;line-height:1.5">
                      Go to <strong>Settings</strong> and add your personal WhatsApp number.
                      This is where you'll receive order alerts — and it's how your assigned
                      onboarding specialist will reach you to complete your WhatsApp setup.
                    </div>
                  </td>
                </tr>
              </table>
            </td></tr>
            <tr><td style="padding:0 0 20px">
              <table width="100%" cellpadding="0" cellspacing="0"
                style="background:#F5F4F0;border-radius:10px;padding:14px 16px">
                <tr>
                  <td width="32" valign="top" style="padding-right:12px">
                    <div style="width:26px;height:26px;background:#555;border-radius:50%;
                      text-align:center;line-height:26px;color:#fff;font-weight:700;font-size:13px">3</div>
                  </td>
                  <td>
                    <div style="font-weight:600;font-size:14px;color:#111">Your specialist completes activation</div>
                    <div style="font-size:13px;color:#777;margin-top:3px;line-height:1.5">
                      Once you've added your operator number, your onboarding specialist will
                      reach out via WhatsApp to verify your store number and get you live.
                      The whole process takes under 24 hours.
                    </div>
                  </td>
                </tr>
              </table>
            </td></tr>
          </table>

          <div style="background:#FFF8E1;border:1px solid #F59E0B;border-radius:10px;
            padding:14px 18px;margin-bottom:24px">
            <p style="margin:0;font-size:13px;color:#92400E;line-height:1.5">
              <strong>Note:</strong> The WhatsApp number you submitted for your store must
              <strong>not</strong> currently be active on WhatsApp or WhatsApp Business App.
              If it is, you'll need to delete it as a WhatsApp account from your phone settings first.
              Your onboarding specialist will guide you through this if needed.
            </p>
          </div>

          <a href="{dashboard_url}"
            style="display:block;background:#25D366;color:#fff;text-align:center;
              padding:14px 24px;border-radius:8px;font-weight:600;font-size:15px;
              text-decoration:none;letter-spacing:.01em">
            Go to Dashboard
          </a>
        </td></tr>
        <tr><td style="padding:20px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">
            HoBS by AltekFlo &middot; WhatsApp Commerce &middot; Nigeria<br>
            Questions? <a href="mailto:hello@altekflo.xyz" style="color:#25D366;text-decoration:none">hello@altekflo.xyz</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""You're in, {first_name}!

Your HoBS account is verified. Here's what to do now:

1. Log in and add your products
   Head to your dashboard and add everything you sell.
   Dashboard: {dashboard_url}

2. Set your operator number
   Go to Settings and add your personal WhatsApp number.
   This is how your onboarding specialist will reach you.

3. Your specialist completes activation
   Once your operator number is set, your assigned onboarding specialist
   will reach out via WhatsApp and get your store live within 24 hours.

Note: The store WhatsApp number you submitted must NOT currently be active
on WhatsApp or WhatsApp Business App. Your specialist will guide you if needed.

Questions? hello@altekflo.xyz
"""
    return await send_email(to_email, subject, html, text)

# ─────────────────────────────────────────────────────────────────────────────
# 3. OTP REQUESTED EMAIL
#    Sent when you (admin) click Activate in the dashboard.
#    Tells the merchant to open their store dashboard and enter the code.
# ─────────────────────────────────────────────────────────────────────────────

async def send_otp_requested_email(
    to_email: str,
    merchant_name: str,
    store_name: str,
    client_id: str,
    whatsapp_number: str,
    store_dashboard_url: str,
) -> bool:
    """
    Fires when admin calls /admin/wa/activate.
    Merchant receives this and knows to go enter their OTP.
    """
    subject = f"Action required: Enter your WhatsApp verification code — {store_name}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:28px 40px;text-align:center">
          <div style="font-size:24px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:4px;
            letter-spacing:.08em;text-transform:uppercase">WhatsApp Activation</div>
        </td></tr>
        <tr><td style="padding:36px 40px 32px">
          <h1 style="margin:0 0 6px;font-size:20px;font-weight:700;color:#111">
            Your verification code is on its way 📲
          </h1>
          <p style="margin:0 0 24px;font-size:14px;color:#777;line-height:1.6">
            Hi {merchant_name.split()[0]}, we've started activating your WhatsApp number for
            <strong>{store_name}</strong>. Meta is sending a 6-digit verification code to
            <strong>+{whatsapp_number}</strong> right now via SMS or call.
          </p>

          <div style="background:#FEF9C3;border:1px solid #FDE047;border-radius:10px;
            padding:16px 20px;margin-bottom:20px">
            <p style="margin:0;font-size:14px;font-weight:600;color:#713F12;line-height:1.5">
              👉 As soon as you receive the code, open your store dashboard and enter it there.
              The code expires in 10 minutes.
            </p>
          </div>

          <div style="background:#F5F4F0;border-radius:10px;padding:14px 20px;margin-bottom:20px">
            <p style="margin:0 0 4px;font-size:12px;color:#999;text-transform:uppercase;
              font-weight:600;letter-spacing:.06em">Store</p>
            <p style="margin:0;font-size:16px;font-weight:700;color:#111">{store_name}</p>
            <p style="margin:4px 0 0;font-size:13px;color:#777">Store ID: {client_id}</p>
          </div>

          <a href="{store_dashboard_url}"
            style="display:block;background:#25D366;color:#fff;text-align:center;
              padding:14px 24px;border-radius:8px;font-weight:600;font-size:15px;
              text-decoration:none">
            Open My Dashboard to Enter Code
          </a>

          <p style="margin:16px 0 0;font-size:12px;color:#aaa;text-align:center;line-height:1.6">
            Didn't receive a code? It can take up to 2 minutes. Check both SMS and missed calls.<br>
            If you still don't receive it, contact us.
          </p>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS by AltekFlo · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""Hi {merchant_name.split()[0]},

We've started activating your WhatsApp number (+{whatsapp_number}) for {store_name}.

Meta is sending a 6-digit code to that number right now via SMS or call.

👉 As soon as you receive it, open your store dashboard and enter the code.
The code expires in 10 minutes.

Store: {store_name} ({client_id})
Dashboard: {store_dashboard_url}

Didn't receive the code? It can take up to 2 minutes. Check SMS and missed calls.
"""
    return await send_email(to_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# 4. STORE LIVE EMAIL
#    Sent automatically after OTP is verified and the store goes fully active.
# ─────────────────────────────────────────────────────────────────────────────

async def send_store_live_email(
    to_email: str,
    merchant_name: str,
    store_name: str,
    client_id: str,
    whatsapp_number: str,
    store_dashboard_url: str,
) -> bool:
    """
    Fires after the auto-chain (register + subscribe-webhook) completes
    and the credential is marked active.
    """
    subject = f"🚀 {store_name} is live on WhatsApp!"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#16A34A;padding:32px 40px 28px;text-align:center">
          <div style="font-size:40px;margin-bottom:8px">🚀</div>
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">You're live!</div>
          <div style="font-size:14px;color:rgba(255,255,255,.8);margin-top:6px">
            {store_name} is now accepting orders on WhatsApp
          </div>
        </td></tr>
        <tr><td style="padding:36px 40px 32px">
          <p style="margin:0 0 20px;font-size:15px;color:#555;line-height:1.6">
            Hi {merchant_name.split()[0]}, your WhatsApp number has been verified and your store
            is now fully connected. Customers can start messaging to place orders right now.
          </p>

          <div style="background:#F0FDF4;border:1px solid #86EFAC;border-radius:10px;
            padding:16px 20px;margin-bottom:20px">
            <p style="margin:0 0 6px;font-size:12px;color:#16A34A;text-transform:uppercase;
              font-weight:600;letter-spacing:.06em">Your WhatsApp number</p>
            <p style="margin:0;font-size:24px;font-weight:800;color:#111;letter-spacing:.04em">
              +{whatsapp_number}
            </p>
            <p style="margin:4px 0 0;font-size:12px;color:#555">
              Share this number with your customers to start receiving orders.
            </p>
          </div>

          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px">
            <tr><td style="padding:0 0 10px">
              <table width="100%" cellpadding="0" cellspacing="0"
                style="background:#F5F4F0;border-radius:8px;padding:12px 16px">
                <tr>
                  <td width="24" style="padding-right:10px;font-size:18px">📦</td>
                  <td>
                    <div style="font-weight:600;font-size:14px;color:#111">Add your products</div>
                    <div style="font-size:12px;color:#777;margin-top:2px">
                      Go to your dashboard and add your product catalogue.
                    </div>
                  </td>
                </tr>
              </table>
            </td></tr>
            <tr><td style="padding:0 0 10px">
              <table width="100%" cellpadding="0" cellspacing="0"
                style="background:#F5F4F0;border-radius:8px;padding:12px 16px">
                <tr>
                  <td width="24" style="padding-right:10px;font-size:18px">💳</td>
                  <td>
                    <div style="font-weight:600;font-size:14px;color:#111">Connect your bank account</div>
                    <div style="font-size:12px;color:#777;margin-top:2px">
                      Set up your Flutterwave subaccount to receive payments.
                    </div>
                  </td>
                </tr>
              </table>
            </td></tr>
            <tr><td>
              <table width="100%" cellpadding="0" cellspacing="0"
                style="background:#F5F4F0;border-radius:8px;padding:12px 16px">
                <tr>
                  <td width="24" style="padding-right:10px;font-size:18px">📣</td>
                  <td>
                    <div style="font-weight:600;font-size:14px;color:#111">Share your number</div>
                    <div style="font-size:12px;color:#777;margin-top:2px">
                      Put it on your Instagram bio, flyers, and anywhere customers can find you.
                    </div>
                  </td>
                </tr>
              </table>
            </td></tr>
          </table>

          <a href="{store_dashboard_url}"
            style="display:block;background:#25D366;color:#fff;text-align:center;
              padding:14px 24px;border-radius:8px;font-weight:600;font-size:15px;
              text-decoration:none">
            Open My Dashboard
          </a>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS by AltekFlo · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""🚀 {store_name} is live on WhatsApp!

Hi {merchant_name.split()[0]},

Your WhatsApp number (+{whatsapp_number}) is now fully connected and active.
Customers can message that number right now to place orders.

What to do next:
1. Add your products in the dashboard
2. Connect your bank account (Flutterwave subaccount)
3. Share your number with customers

Dashboard: {store_dashboard_url}
"""
    return await send_email(to_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# 5. STORE CREATED EMAIL  (kept from original — fires when merchant adds a
#    second/additional store from settings, not on initial registration)
# ─────────────────────────────────────────────────────────────────────────────

async def send_store_created_email(
    merchant_email: str,
    store_name: str,
    client_id: str,
    whatsapp_number: str | None,
) -> bool:
    cfg          = _cfg()
    app_url      = cfg["app_url"]
    store_login_url = f"{app_url}/store-login"
    subject      = f"New store created: {store_name} ({client_id})"

    if whatsapp_number:
        # ── WITH WhatsApp: team will reach out to complete onboarding ──────────
        wa_line = (
            f"<p style='margin:0 0 8px;font-size:14px;color:#555'>"
            f"<strong>WhatsApp number submitted:</strong> +{whatsapp_number}</p>"
        )
        body_para = (
            "A new store has been created on your account. Our team will reach out within "
            "24 hours to activate the WhatsApp number for this store."
        )
        notice_html = """
          <div style="background:#FFF8E1;border:1px solid #F59E0B;border-radius:10px;padding:14px 18px">
            <p style="margin:0;font-size:13px;color:#92400E;line-height:1.5">
              ⚠️ A HoBS agent will contact you within 24 hours to activate the WhatsApp
              number for this store. The number must <strong>not</strong> currently be on
              WhatsApp Business App.
            </p>
          </div>"""
        text_footer = (
            "A HoBS agent will contact you within 24 hours to complete WhatsApp onboarding.\n"
            "The number must not currently be on WhatsApp Business App."
        )
    else:
        # ── WITHOUT WhatsApp: show login credentials and self-serve instructions ─
        wa_line = (
            "<p style='margin:0 0 8px;font-size:14px;color:#999'>"
            "No WhatsApp number submitted — you can add one from your store dashboard.</p>"
        )
        body_para = (
            "Your new store has been created. You can sign in right now using your Store ID "
            "and the password you set during creation."
        )
        notice_html = f"""
          <div style="background:#E8F5E9;border:1px solid #4CAF50;border-radius:10px;padding:14px 18px;margin-bottom:12px">
            <p style="margin:0 0 6px;font-size:13px;color:#2E7D32;font-weight:600">Sign in to your store dashboard</p>
            <p style="margin:0 0 4px;font-size:13px;color:#2E7D32">
              URL: <a href="{store_login_url}" style="color:#1B5E20">{store_login_url}</a>
            </p>
            <p style="margin:0;font-size:13px;color:#2E7D32">Use your Store ID and the password you created.</p>
          </div>
          <div style="background:#E3F2FD;border:1px solid #2196F3;border-radius:10px;padding:14px 18px">
            <p style="margin:0 0 6px;font-size:13px;color:#0D47A1;font-weight:600">Add your WhatsApp number later</p>
            <p style="margin:0;font-size:13px;color:#0D47A1;line-height:1.5">
              Once signed in, go to <strong>Settings → WhatsApp</strong> and enter the number
              you want customers to order through. Our team will then activate it for you.
            </p>
          </div>"""
        text_footer = (
            f"Sign in at: {store_login_url}\n"
            "Use your Store ID and the password you created.\n\n"
            "To add a WhatsApp number later, sign in and go to Settings → WhatsApp."
        )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:28px 40px;text-align:center">
          <div style="font-size:24px;font-weight:700;color:#fff">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:4px;
            letter-spacing:.08em;text-transform:uppercase">Store Created</div>
        </td></tr>
        <tr><td style="padding:36px 40px 32px">
          <h1 style="margin:0 0 6px;font-size:20px;font-weight:700;color:#111">New store added ✅</h1>
          <p style="margin:0 0 24px;font-size:14px;color:#777;line-height:1.5">
            {body_para}
          </p>
          <div style="background:#F5F4F0;border-radius:10px;padding:16px 20px;margin-bottom:16px">
            <p style="margin:0 0 8px;font-size:14px;color:#555"><strong>Store name:</strong> {store_name}</p>
            <p style="margin:0 0 8px;font-size:14px;color:#555">
              <strong>Store ID:</strong>
              <span style="font-family:monospace;font-size:15px;font-weight:700;color:#111">{client_id}</span>
            </p>
            {wa_line}
          </div>
          {notice_html}
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS by AltekFlo · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""New store created on your HoBS account.

Store name: {store_name}
Store ID:   {client_id}

{text_footer}
"""
    return await send_email(merchant_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# 6. PASSWORD RESET EMAIL
# ─────────────────────────────────────────────────────────────────────────────

async def send_password_reset_email(
    to_email: str,
    merchant_name: str,
    code: str,
) -> bool:
    cfg        = _cfg()
    first_name = merchant_name.split()[0]
    subject    = "Your HoBS password reset code"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:28px 40px;text-align:center">
          <div style="font-size:24px;font-weight:700;color:#fff">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:4px;
            letter-spacing:.08em;text-transform:uppercase">Password Reset</div>
        </td></tr>
        <tr><td style="padding:40px 40px 36px">
          <p style="margin:0 0 6px;font-size:16px;font-weight:700;color:#111">Hi {first_name},</p>
          <p style="margin:0 0 28px;font-size:14px;color:#777;line-height:1.6">
            We received a request to reset your HoBS merchant password.
            Use the code below to continue. It expires in <strong>10 minutes</strong>.
          </p>

          <!-- Big code block -->
          <div style="background:#F5F4F0;border-radius:12px;padding:24px;text-align:center;margin-bottom:28px">
            <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:#999;
              text-transform:uppercase;letter-spacing:.08em">Your reset code</p>
            <p style="margin:0;font-family:monospace;font-size:40px;font-weight:800;
              letter-spacing:12px;color:#111">{code}</p>
          </div>

          <div style="background:#FFF8E1;border:1px solid #F59E0B;border-radius:10px;padding:14px 18px;margin-bottom:8px">
            <p style="margin:0;font-size:13px;color:#92400E;line-height:1.5">
              ⚠️ If you didn't request this, you can safely ignore this email.
              Your password will not change.
            </p>
          </div>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS by AltekFlo · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""Hi {first_name},

Your HoBS password reset code is:

  {code}

This code expires in 10 minutes. If you didn't request a reset, ignore this email.
"""
    return await send_email(to_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# 7. STORE LOGIN ALERT
#    Sent to the merchant whenever a store manager logs in to the store dashboard.
#    Security notice — if it wasn't them, they can revoke access.
# ─────────────────────────────────────────────────────────────────────────────

async def send_store_login_alert(
    to_email: str,
    merchant_name: str,
    store_name: str,
    client_id: str,
) -> bool:
    from datetime import datetime, timezone
    cfg        = _cfg()
    app_url    = cfg["app_url"]
    first_name = merchant_name.split()[0]
    now_str    = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    subject    = f"Store sign-in alert — {store_name}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:28px 40px;text-align:center">
          <div style="font-size:24px;font-weight:700;color:#fff">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:4px;
            letter-spacing:.08em;text-transform:uppercase">Security Alert</div>
        </td></tr>
        <tr><td style="padding:36px 40px 32px">
          <p style="margin:0 0 6px;font-size:16px;font-weight:700;color:#111">Hi {first_name},</p>
          <p style="margin:0 0 20px;font-size:14px;color:#555;line-height:1.6">
            Someone just signed in to your store dashboard.
          </p>
          <div style="background:#F5F4F0;border-radius:10px;padding:16px 20px;margin-bottom:20px">
            <p style="margin:0 0 6px;font-size:13px;color:#999;text-transform:uppercase;
              font-weight:600;letter-spacing:.06em">Store</p>
            <p style="margin:0 0 10px;font-size:18px;font-weight:700;color:#111">{store_name}</p>
            <p style="margin:0 0 4px;font-size:13px;color:#777">Store ID: <strong>{client_id}</strong></p>
            <p style="margin:0;font-size:13px;color:#777">Time: {now_str}</p>
          </div>
          <div style="background:#FFF8E1;border:1px solid #F59E0B;border-radius:10px;
            padding:14px 18px;margin-bottom:20px">
            <p style="margin:0;font-size:13px;color:#92400E;line-height:1.5">
              <strong>Not you?</strong> Sign in to your merchant dashboard immediately and
              reset the store password from Settings to revoke access.
            </p>
          </div>
          <a href="{app_url}/dashboard"
            style="display:block;background:#111;color:#fff;text-align:center;
              padding:13px 24px;border-radius:8px;font-weight:600;font-size:14px;
              text-decoration:none">
            Go to Merchant Dashboard
          </a>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS by AltekFlo · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""Hi {first_name},

Someone just signed in to your store dashboard.

Store: {store_name} ({client_id})
Time:  {now_str}

If this wasn't you, sign in to your merchant dashboard immediately and reset
the store password in Settings to revoke access.

Dashboard: {app_url}/dashboard
"""
    return await send_email(to_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION RECEIVED — sent to the applicant immediately on form submission
# ─────────────────────────────────────────────────────────────────────────────
async def send_application_received_email(
    to_email: str,
    applicant_name: str,
    business_name: str,
    whatsapp_number: str = None,
    link_token: str = None,
) -> bool:
    """
    The one email sent the moment someone submits the "Apply to Use" form.

    Branches on whether they gave a WhatsApp number:
      - Gave one: tells them we'll contact THEM on that number.
      - Didn't:   tells them plainly, with a link to add it
                  (templates/add_whatsapp_number.html, via link_token).
    """
    cfg        = _cfg()
    first_name = applicant_name.split()[0]
    subject    = f"We got your application, {first_name}! 🎉"

    if whatsapp_number:
        next_step_html = f"""
          <div style="background:#f9f9f7;border-radius:10px;padding:16px 20px;margin-bottom:24px">
            <p style="margin:0;font-size:14px;color:#333;line-height:1.6">
              📱 When we're ready to set you up, we'll message you directly on WhatsApp at
              <strong>+{whatsapp_number}</strong> — that's how we'll verify your number and
              get your store connected, so keep an eye on it.
            </p>
          </div>"""
        next_step_text = (
            f"When we're ready to set you up, we'll message you directly on WhatsApp at "
            f"+{whatsapp_number} to verify your number and connect your store. Keep an eye on it."
        )
    else:
        add_number_url = f"{cfg['api_base_url']}/apply/whatsapp-number/{link_token}"
        next_step_html = f"""
          <div style="background:#fff7ed;border:1px solid #fde4c2;border-radius:10px;padding:16px 20px;margin-bottom:24px">
            <p style="margin:0 0 12px;font-size:14px;color:#7a4a00;line-height:1.6">
              ⚠️ You didn't include a WhatsApp number for us to reach you on. We need one
              to verify and connect your store.
            </p>
            <a href="{add_number_url}"
              style="display:inline-block;background:#111;color:#fff;text-align:center;
                padding:10px 18px;border-radius:8px;font-weight:600;font-size:14px;
                text-decoration:none">
              Add your WhatsApp number →
            </a>
          </div>"""
        next_step_text = (
            f"You didn't include a WhatsApp number for us to reach you on, and we need one "
            f"to verify and connect your store. Add it here: {add_number_url}"
        )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:32px 40px 28px;text-align:center">
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:5px;
            letter-spacing:.08em;text-transform:uppercase">WhatsApp Commerce</div>
        </td></tr>
        <tr><td style="padding:40px 40px 32px">
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111">
            Application received! ✅
          </h1>
          <p style="margin:0 0 20px;font-size:15px;color:#555;line-height:1.6">
            Hi {first_name}, thanks for applying to use HoBS for
            <strong>{business_name}</strong>.
          </p>
          <p style="margin:0 0 20px;font-size:15px;color:#555;line-height:1.6">
            Our team will review your application within <strong>1–2 business days</strong>.
          </p>
          {next_step_html}
          <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6">
            Once approved, you'll receive a separate email with your login details.
            In the meantime, feel free to reply to this email if you have any questions.
          </p>
          <div style="background:#f9f9f7;border-radius:10px;padding:16px 20px">
            <p style="margin:0;font-size:13px;color:#888;line-height:1.6">
              <strong style="color:#333">Business:</strong> {business_name}<br>
              <strong style="color:#333">Applicant:</strong> {applicant_name}<br>
              <strong style="color:#333">Email:</strong> {to_email}
            </p>
          </div>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""Hi {first_name},

Thanks for applying to use HoBS for {business_name}.

Our team will review your application within 1–2 business days.

{next_step_text}

Once approved, you'll receive your login credentials by separate email.

If you have any questions, just reply to this email.

— The HoBS Team
"""
    return await send_email(to_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# ONBOARDING WIZARD — idle draft reminder
# Sent by the reminder job (app/api/v1/workers/reminder_job.py) on a 1hr /
# 48hr / 7-day cadence to anyone who started the "Apply to Use" wizard but
# hasn't finished. Stops after reminder_number 3 — the job itself enforces
# that ceiling.
#
# Copy is driven by TWO things:
#   - current_step: which step of the wizard they stopped at (2, 3, or 4),
#     so the email tells them specifically what's left rather than a vague
#     "finish your application".
#   - reminder_number: how many times we've already nudged them (1st/2nd/3rd),
#     which controls the urgency/tone and subject line.
# ─────────────────────────────────────────────────────────────────────────────

# What's left to do, keyed by MerchantApplication.current_step for an idle
# draft. A draft can only be idle at step 2, 3, or 4 — step 1 (contact info)
# is what *creates* the draft, and a completed step 4 flips status away from
# "draft" entirely, so it's never idle at step 1 or "step 5".
_STEP_COPY = {
    2: {
        "whats_left": "add your business details",
        "detail": "You told us who you are — next we just need a few details "
                   "about your business (name, type, and city).",
    },
    3: {
        "whats_left": "verify your business or identity",
        "detail": "Your business details are saved — next is a quick verification "
                   "step (CAC, BVN, or NIN) so we can review your account.",
    },
    4: {
        "whats_left": "accept the terms and submit",
        "detail": "You're one step away — just review and accept the terms "
                   "to submit your application.",
    },
}
_DEFAULT_STEP_COPY = {
    "whats_left": "finish your application",
    "detail": "Your application is still saved right where you left it.",
}


async def send_application_reminder_email(
    to_email: str,
    full_name: str,
    resume_url: str,
    reminder_number: int,
    current_step: int = None,
) -> bool:
    cfg        = _cfg()
    first_name = full_name.split()[0]
    step_copy  = _STEP_COPY.get(current_step, _DEFAULT_STEP_COPY)

    tier = {
        1: {
            "subject": f"Pick up where you left off, {first_name}",
            "tone": f"You started applying to use HoBS but didn't quite finish — "
                    f"you just need to {step_copy['whats_left']}.",
        },
        2: {
            "subject": "Still want to set up your store on HoBS?",
            "tone": f"Your application is still saved. {step_copy['detail']}",
        },
        3: {
            "subject": "Last reminder: your HoBS application is waiting",
            "tone": f"This is our final reminder — after this we'll stop following up, "
                    f"but your progress stays saved if you come back on your own. "
                    f"{step_copy['detail']}",
        },
    }.get(reminder_number, {
        "subject": "Continue your HoBS application",
        "tone": f"Your application is still saved. {step_copy['detail']}",
    })
    copy = {"subject": tier["subject"], "lead": tier["tone"]}

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:32px 40px 28px;text-align:center">
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
        </td></tr>
        <tr><td style="padding:40px 40px 32px">
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111">
            Hi {first_name} 👋
          </h1>
          <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6">
            {copy['lead']}
          </p>
          <a href="{resume_url}"
            style="display:inline-block;background:#111;color:#fff;text-align:center;
              padding:12px 22px;border-radius:8px;font-weight:600;font-size:14px;
              text-decoration:none">
            Continue my application →
          </a>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"Hi {first_name},\n\n{copy['lead']}\n\nContinue here: {resume_url}\n\n— The HoBS Team\n"

    return await send_email(to_email, copy["subject"], html, text)


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION GRACE PERIOD — 5 distinct emails sent by
# app/api/v1/workers/verification_grace_job.py to applicants who finished
# the wizard without submitting CAC/BVN/NIN. Cadence: day 2, day 4, day 6,
# day 7 morning, day 7 evening. Each one is written fresh — no shared
# boilerplate paragraph — so the sequence reads like a real person checking
# in, not a repeating cron job. Tone stays warm throughout, even at #5:
# the account is never deactivated, only WhatsApp messaging pauses, and
# it's instantly reversible the moment they verify.
# ─────────────────────────────────────────────────────────────────────────────
_GRACE_COPY = {
    1: {  # day 2 — light, no pressure yet
        "subject": "One small thing left on your HoBS account",
        "heading": "Almost fully set up",
        "body": (
            "Just a friendly note — your HoBS account is live and working great, "
            "but we noticed you skipped adding your CAC or NIN when you applied. "
            "Totally fine, it happens. Whenever you get a free minute, adding it "
            "takes about two minutes and keeps everything running smoothly long-term."
        ),
        "cta": "Add my verification →",
        "footnote": "No rush at all — just wanted to put it on your radar.",
    },
    2: {  # day 4 — first real mention of the window
        "subject": "Heads up: 3 days left on your verification window",
        "heading": "Still time to sort this",
        "body": (
            "Quick update — it's been a few days since you set up your HoBS "
            "account, and your CAC/NIN is still outstanding. Here's the honest "
            "version: after day 7, WhatsApp messaging pauses on your account "
            "until it's added. Nothing else is affected, and it's a two-minute "
            "fix whenever you're ready — you've got 3 days left to knock it out "
            "before that kicks in."
        ),
        "cta": "Verify now — 2 minutes →",
        "footnote": "Your account stays exactly as it is otherwise. This is the only thing standing between now and a fully unlocked account.",
    },
    3: {  # day 6 — urgency building, still kind
        "subject": "Tomorrow's the deadline for WhatsApp messaging",
        "heading": "One day to go",
        "body": (
            "We don't want this to catch you off guard: tomorrow marks 7 days "
            "since your account went live, and WhatsApp messaging will pause "
            "until your CAC or NIN is on file. Everything else — your dashboard, "
            "orders, payments — keeps working exactly as before. It's genuinely "
            "a quick step, and the moment you complete it, messaging switches "
            "back on immediately."
        ),
        "cta": "Verify before tomorrow →",
        "footnote": "Your account is never deactivated — this only affects WhatsApp messaging, and only until you verify.",
    },
    4: {  # day 7 AM — today's the day, still reassuring
        "subject": "Today's the day — here's what happens",
        "heading": "This is happening today",
        "body": (
            "Today is day 7. If your CAC or NIN isn't added by tonight, WhatsApp "
            "messaging on your HoBS account will pause. We know that sounds "
            "alarming, so to be clear: your account is not being deactivated, "
            "your data isn't going anywhere, and nothing else about your setup "
            "changes. The pause lifts the instant you verify — even if that's "
            "next week. We'd just rather you didn't lose messaging over "
            "something this quick to fix."
        ),
        "cta": "Verify right now →",
        "footnote": "This is a 2-minute form. You've got the rest of today.",
    },
    5: {  # day 7 PM — last call, still warm and clear
        "subject": "Last call today — exactly what to expect",
        "heading": "Final reminder for today",
        "body": (
            "This is our last nudge before WhatsApp messaging pauses on your "
            "account tonight. One more time, so it's totally clear: your account "
            "stays active, your dashboard and orders keep working, and this is "
            "fully reversible — the moment you add your CAC or NIN, messaging "
            "turns back on right away, no waiting, no review queue. If tonight "
            "isn't a good time, that's okay too — just come back whenever you're "
            "ready and pick up exactly where you left off."
        ),
        "cta": "Verify before tonight →",
        "footnote": "Whenever you're ready — even after tonight — this switches messaging back on immediately.",
    },
}


async def send_verification_grace_email(
    to_email: str,
    full_name: str,
    resume_url: str,
    reminder_number: int,
    business_name: str = None,
) -> bool:
    first_name = (full_name or "there").split()[0]
    copy = _GRACE_COPY.get(reminder_number, _GRACE_COPY[1])
    biz_line = f" for {business_name}" if business_name else ""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:32px 40px 28px;text-align:center">
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
        </td></tr>
        <tr><td style="padding:40px 40px 32px">
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111">
            {copy['heading']}
          </h1>
          <p style="margin:0 0 20px;font-size:15px;color:#555;line-height:1.65">
            Hi {first_name}, {copy['body']}
          </p>
          <a href="{resume_url}"
            style="display:inline-block;background:#111;color:#fff;text-align:center;
              padding:12px 22px;border-radius:8px;font-weight:600;font-size:14px;
              text-decoration:none">
            {copy['cta']}
          </a>
          <p style="margin:20px 0 0;font-size:12px;color:#999;line-height:1.6">
            {copy['footnote']}
          </p>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = (
        f"Hi {first_name},\n\n{copy['body']}\n\n"
        f"Verify here{biz_line}: {resume_url}\n\n{copy['footnote']}\n\n— The HoBS Team\n"
    )

    return await send_email(to_email, copy["subject"], html, text)
# NOTE: no longer called by apply_to_use(). The Slack alert + the admin
# dashboard's "Pending Applications" panel cover this now, so a separate
# team email would just be a third duplicate notification. Left defined
# here in case it's ever wanted again.
# ─────────────────────────────────────────────────────────────────────────────
async def send_team_application_alert(
    application: dict,
) -> bool:
    """
    Sends a rich HTML summary of the application to the TEAM_EMAIL env var.
    `application` is a dict of the MerchantApply payload fields.
    """
    import os
    cfg       = _cfg()
    team_email = os.getenv("TEAM_EMAIL", cfg["from_email"])
    if not team_email:
        logger.warning("TEAM_EMAIL not configured — application alert skipped")
        return False

    def _s(v) -> str:
        """Escape a field for safe HTML interpolation. Applicant-controlled —
        never trust it to be free of markup or injection attempts."""
        return _html_escape(str(v), quote=True)

    # Raw values — safe for the plaintext part of the email, and for the
    # subject line once newlines are stripped (below).
    biz_raw   = str(application.get("business_name", "—"))
    name_raw  = str(application.get("full_name", "—"))
    email_raw = str(application.get("email", "—"))
    phone_raw = str(application.get("phone_number", "—"))
    wa_raw    = str(application.get("whatsapp_number", "—"))
    btype_raw = str(application.get("business_type", "—"))
    city_raw  = str(application.get("city_state", "—"))
    branches_raw = str(application.get("num_branches", "—"))
    volume_raw   = str(application.get("monthly_order_volume", "—"))
    uses_wa  = "Yes" if application.get("uses_whatsapp_manual") else "No"
    uses_del = "Yes" if application.get("uses_delivery_service") else "No"
    heard_raw    = str(application.get("heard_about_us", "—"))
    comments_raw = str(application.get("comments") or "—")

    # HTML-escaped versions — used only inside the HTML email body.
    biz, name, email   = _s(biz_raw), _s(name_raw), _s(email_raw)
    phone, wa          = _s(phone_raw), _s(wa_raw)
    btype, city        = _s(btype_raw), _s(city_raw)
    branches, volume   = _s(branches_raw), _s(volume_raw)
    heard, comments    = _s(heard_raw), _s(comments_raw)

    # Strip CR/LF from subject fields — applicant-controlled values must
    # never be able to inject extra email headers via a raw subject line.
    _subj_biz  = biz_raw.replace("\r", "").replace("\n", " ")
    _subj_name = name_raw.replace("\r", "").replace("\n", " ")
    subject = f"[HoBS Application] {_subj_biz} — {_subj_name}"

    def _row(label, value):
        return f"""<tr>
          <td style="padding:8px 12px;font-size:13px;color:#666;white-space:nowrap;
            border-bottom:1px solid #f0f0f0;width:180px">{label}</td>
          <td style="padding:8px 12px;font-size:13px;color:#111;
            border-bottom:1px solid #f0f0f0;font-weight:500">{value}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:28px 40px;text-align:center">
          <div style="font-size:20px;font-weight:700;color:#fff">🆕 New Merchant Application</div>
          <div style="font-size:13px;color:rgba(255,255,255,.5);margin-top:4px">{biz}</div>
        </td></tr>
        <tr><td style="padding:32px 40px">
          <table width="100%" cellpadding="0" cellspacing="0"
            style="border:1px solid #eee;border-radius:10px;overflow:hidden">
            {_row("Business Name", biz)}
            {_row("Business Type", btype)}
            {_row("City / State", city)}
            {_row("Applicant Name", name)}
            {_row("Email", f'<a href="mailto:{email}" style="color:#333">{email}</a>')}
            {_row("Phone", phone)}
            {_row("WhatsApp Number", wa)}
            {_row("Branches", branches)}
            {_row("Monthly Orders", volume)}
            {_row("Manual WhatsApp Orders?", uses_wa)}
            {_row("Uses Delivery Service?", uses_del)}
            {_row("Heard About Us", heard)}
            {_row("Comments", f'<span style="white-space:pre-wrap">{comments}</span>')}
          </table>
          <div style="margin-top:28px;text-align:center">
            <p style="font-size:13px;color:#888;margin:0 0 12px">
              To approve this applicant, call <code>POST /admin/approve-merchant</code>
              with their details, or use the admin dashboard.
            </p>
          </div>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS Internal · Do not forward</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""New Merchant Application — {biz_raw}

Business: {biz_raw}
Type:     {btype_raw}
City:     {city_raw}
Name:     {name_raw}
Email:    {email_raw}
Phone:    {phone_raw}
WhatsApp: {wa_raw}
Branches: {branches_raw}
Volume:   {volume_raw}
Manual WA orders: {uses_wa}
Delivery service: {uses_del}
Heard from:       {heard_raw}
Comments: {comments_raw}
"""
    return await send_email(team_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# APPROVED MERCHANT WELCOME — sent to the merchant when admin approves them
# Includes their login credentials.
# ─────────────────────────────────────────────────────────────────────────────
async def send_approved_merchant_welcome_email(
    to_email: str,
    merchant_name: str,
    merchant_id: str,
    set_password_url: str = "",
    initial_password: str = "",  # kept for backward compat; ignored
) -> bool:
    """
    Sent the moment admin approves an application.  Contains a single
    "Set your password" link (valid 72 h) — no auto-generated password in the email.
    Deliberately does NOT say "you're all set" — WhatsApp still needs connecting.
    """
    cfg        = _cfg()
    first_name = merchant_name.split()[0]
    support_wa = cfg["support_wa"]
    subject    = f"You're approved, {first_name}! Create your password to get started"

    support_line_html = (
        f"<strong>+{support_wa}</strong>" if support_wa
        else "our team"
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:32px 40px 28px;text-align:center">
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
          <div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:5px;
            letter-spacing:.08em;text-transform:uppercase">WhatsApp Commerce</div>
        </td></tr>
        <tr><td style="padding:40px 40px 32px">
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111">
            You're approved, {first_name}! 🎉
          </h1>
          <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6">
            Your HoBS account is ready. Click the button below to create your
            password and sign in. <strong>This link expires in 72 hours.</strong>
          </p>

          <a href="{set_password_url}"
            style="display:block;background:#111;color:#fff;text-align:center;
              padding:14px 24px;border-radius:10px;font-weight:600;font-size:15px;
              text-decoration:none;margin-bottom:28px">
            Set my password →
          </a>

          <p style="margin:0 0 6px;font-size:13px;color:#999;line-height:1.6">
            If the button doesn't work, copy and paste this link into your browser:
          </p>
          <p style="margin:0 0 28px;font-size:12px;color:#aaa;word-break:break-all">
            {set_password_url}
          </p>

          <p style="margin:0 0 10px;font-size:12px;font-weight:700;color:#999;
            text-transform:uppercase;letter-spacing:.06em">What happens next</p>
          <ol style="margin:0 0 24px;padding-left:20px;font-size:14px;color:#555;line-height:1.8">
            <li>Set your password using the link above.</li>
            <li>We'll message you personally on WhatsApp from {support_line_html} to get
              a quick verification code from Meta.</li>
            <li>We'll use that code to activate your number.</li>
            <li>You'll get a separate "you're live" email the moment it's connected.</li>
          </ol>

          <p style="margin:0;font-size:14px;color:#888;line-height:1.6">
            That WhatsApp message is how we'll reach you for the activation step —
            please reply when you see it.
          </p>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    support_line_text = f"+{support_wa}" if support_wa else "our team"
    text = f"""Hi {first_name},

Your HoBS account is ready. Create your password using the link below:

  {set_password_url}

This link expires in 72 hours.

What happens next:
  1. Set your password using the link above.
  2. We'll message you on WhatsApp from {support_line_text} for a quick Meta verification code.
  3. We'll use that code to activate your number.
  4. You'll get a separate "you're live" email once it's connected.

That WhatsApp message is how we'll reach you for the activation step — please reply when you see it.

— The HoBS Team
"""
    return await send_email(to_email, subject, html, text)


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION DECLINED — sent when admin rejects a pending application
# ─────────────────────────────────────────────────────────────────────────────
async def send_application_declined_email(
    to_email: str,
    applicant_name: str,
    business_name: str,
) -> bool:
    cfg        = _cfg()
    first_name = applicant_name.split()[0]
    subject    = "An update on your HoBS application"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F4F0;font-family:'DM Sans',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5F4F0;padding:40px 20px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
        style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
        <tr><td style="background:#111110;padding:32px 40px 28px;text-align:center">
          <div style="font-size:26px;font-weight:700;color:#fff;letter-spacing:-.02em">HoBS</div>
        </td></tr>
        <tr><td style="padding:40px 40px 32px">
          <h1 style="margin:0 0 12px;font-size:20px;font-weight:700;color:#111">
            Hi {first_name},
          </h1>
          <p style="margin:0 0 18px;font-size:15px;color:#555;line-height:1.6">
            Thanks for your interest in HoBS for <strong>{business_name}</strong>.
            After review, we're not able to move forward with your application at this time.
          </p>
          <p style="margin:0;font-size:15px;color:#555;line-height:1.6">
            You're welcome to apply again in the future if your circumstances change.
            Thanks for considering us.
          </p>
        </td></tr>
        <tr><td style="padding:16px 40px;border-top:1px solid #eee;text-align:center">
          <p style="margin:0;font-size:12px;color:#bbb">HoBS · WhatsApp Commerce · Nigeria</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""Hi {first_name},

Thanks for your interest in HoBS for {business_name}. After review, we're not able to move forward with your application at this time.

You're welcome to apply again in the future if your circumstances change. Thanks for considering us.

— The HoBS Team
"""
    return await send_email(to_email, subject, html, text)
