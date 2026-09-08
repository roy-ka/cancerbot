SUBJECT = "Confirm your new email address ✉️"

HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Confirm your new email address</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Confirm this is your new email address. Link expires in 24 hours.
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0F1827;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%; background-color:#ffffff; border-radius:12px; overflow:hidden;">

          <tr>
            <td align="center" style="padding:32px 24px 20px 24px; background-color:#ffffff;">
              <img src="https://cancer-bot.com/cancerbot_light.png" alt="cancer-bot" width="150"
                   style="display:block; width:150px; height:auto; border:0;">
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:12px 24px; background-color:#4A6184; background-color:rgba(3,35,84,0.72);">
              <div style="font-family:Arial, Helvetica, sans-serif; font-size:14px; color:#ffffff;">
                ✉️ Confirm your new email address
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                Someone asked to change the email on your CancerBot account from
                <strong>{old_email}</strong> to this one. The crab double-checked the spelling.
                Twice. He's very particular about typos in important documents.
              </p>
              <p style="margin:0 0 16px 0;">
                Click below to confirm this is really your new email &mdash; nothing changes on
                your account until you do:
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:8px 40px 28px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="border-radius:8px; background-color:#f4f5f7; border:1px solid #4A6184;">
                    <a href="{link}" target="_blank"
                       style="display:inline-block; padding:14px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; font-weight:bold; color:#4A6184; text-decoration:none; border-radius:8px;">
                      Confirm New Email
                    </a>
                  </td>
                </tr>
              </table>
              <div style="padding-top:14px; font-family:Arial, Helvetica, sans-serif; font-size:13px; color:#888888;">
                Button not working? <a href="{link}" target="_blank" style="color:#4A6184; background-color:#f4f5f7; text-decoration:underline; padding:2px 6px; border-radius:4px;">Click here instead</a>.
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 24px 40px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#555555;">
              <p style="margin:0;">
                This link expires in <strong>24 hours</strong>. Until you confirm, your account
                keeps using {old_email}.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 32px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#fef9ec; border-left:4px solid #f59e0b; border-radius:6px;">
                <tr>
                  <td style="padding:16px 20px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#78716c;">
                    <strong style="color:#92400e;">This isn't your email address?</strong>
                    Someone may have mistyped, or someone else is trying to take over an
                    account. Just ignore this email &mdash; nothing happens unless the link above
                    is clicked, and we'll let {old_email} know once it's confirmed too.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Take care,<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person, and one very meticulous crab)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because it was entered as a new email address for a CancerBot account.<br>
                If this wasn't you, no action is needed.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
