SUBJECT = "CancerBot weekly digest — week of {date}"

HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CancerBot weekly digest</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Weekly usage summary for the week of {date}.
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
            <td align="center" style="padding:12px 24px; background-color:#4A6184;">
              <div style="font-family:Arial, Helvetica, sans-serif; font-size:14px; font-weight:bold; color:#ffffff;">
                Weekly digest — week of {date}
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:32px 40px 32px 40px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0; font-weight:bold; color:#4A6184;">Last 7 days — usage</p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-family:Arial, Helvetica, sans-serif; font-size:14px; color:#333333;">
                <tr><td style="padding:4px 0;">New users</td><td align="right" style="padding:4px 0; font-weight:bold;">{new_users}</td></tr>
                <tr><td style="padding:4px 0;">New conversations</td><td align="right" style="padding:4px 0; font-weight:bold;">{new_conversations}</td></tr>
                <tr><td style="padding:4px 0;">Messages sent</td><td align="right" style="padding:4px 0; font-weight:bold;">{messages_sent}</td></tr>
                <tr><td style="padding:4px 0;">Fallback searches triggered</td><td align="right" style="padding:4px 0; font-weight:bold;">{fallback_triggered}</td></tr>
                <tr><td style="padding:4px 0;">New waitlist signups</td><td align="right" style="padding:4px 0; font-weight:bold;">{waitlist_joined}</td></tr>
                <tr><td style="padding:12px 0 4px 0; border-top:1px solid #e5e7eb;">Total registered users</td><td align="right" style="padding:12px 0 4px 0; border-top:1px solid #e5e7eb; font-weight:bold;">{total_users}</td></tr>
              </table>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                Automated weekly digest from CancerBot's monitoring job.
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
