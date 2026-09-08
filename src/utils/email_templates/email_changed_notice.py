SUBJECT = "Your email address was changed 🔄"

HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your email address was changed</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Your CancerBot email was changed. Wasn't you? Revert it here.
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
                🔄 Your email address was changed
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                Just a heads up: the email on your CancerBot account was changed from this
                address to <strong>{new_email}</strong>. The crab updated his napkin
                accordingly. He is very proud of his cross-referencing system.
              </p>
              <p style="margin:0 0 16px 0;">
                If that was you &mdash; great, nothing else to do. This is the last email
                you'll get at this address.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 28px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#fef9ec; border-left:4px solid #f59e0b; border-radius:6px;">
                <tr>
                  <td style="padding:20px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#78716c;">
                    <strong style="color:#92400e; display:block; margin-bottom:8px;">Wasn't you?</strong>
                    If you didn't request this change, someone else may have access to your
                    account. Click below to revert your email back to this address &mdash;
                    the crab treats account security very seriously, right after napkins.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 40px 28px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="border-radius:8px; background-color:#f4f5f7; border:1px solid #4A6184;">
                    <a href="{link}" target="_blank"
                       style="display:inline-block; padding:14px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; font-weight:bold; color:#4A6184; text-decoration:none; border-radius:8px;">
                      Revert to This Email
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
            <td style="padding:0 40px 32px 40px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#555555;">
              <p style="margin:0;">
                After reverting, we'd also recommend changing your password &mdash; just in
                case. The crab suggests something harder to guess than &ldquo;crab123.&rdquo;
                He would know.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Take care,<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person, and one watchful crab)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because it was previously the email address on a CancerBot account.<br>
                This is the last email you'll receive here unless you revert the change.
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
