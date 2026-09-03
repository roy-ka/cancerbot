SUBJECT = "Your CancerBot spot is ready 🎉 (expires in 48 hours)"

HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your CancerBot invitation is ready</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Your spot is ready. This invitation expires in 48 hours.
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
                🎉 Your spot is ready
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                The napkin has been found. Your name was on it the whole time. The crab is
                thrilled, mostly with himself.
              </p>
              <p style="margin:0 0 16px 0;">
                A spot on CancerBot just opened up, and it's yours. Click below to claim it:
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:8px 40px 12px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="border-radius:8px; background-color:#f4f5f7; border:1px solid #4A6184;">
                    <a href="{link}" target="_blank"
                       style="display:inline-block; padding:14px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; font-weight:bold; color:#4A6184; text-decoration:none; border-radius:8px;">
                      Claim My Spot
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
            <td align="center" style="padding:20px 40px 28px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#fef9ec; border-left:4px solid #f59e0b; border-radius:6px;">
                <tr>
                  <td style="padding:16px 20px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#78716c; text-align:left;">
                    <strong style="color:#92400e;">This invitation expires in 48 hours.</strong>
                    After that, the crab puts your spot back in the pile and shuffles it in
                    with everyone else's napkins. Not out of spite &mdash; he just really only
                    has room for so many napkins.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 32px 40px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#555555;">
              <p style="margin:0;">
                If this link has already expired by the time you read it &mdash; no worries at
                all. Just rejoin the waitlist and you'll get another invitation next time
                a spot opens up. The crab keeps no grudges. He barely keeps napkins.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Welcome in (almost),<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person, and one very proud crab)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because you were on the CancerBot waitlist.<br>
                This invitation link expires 48 hours after it was sent.
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
