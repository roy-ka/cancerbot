SUBJECT = "Your CancerBot account deletion is scheduled ⏳"

HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your account deletion is scheduled</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Your account will be deleted on {date}. Log in before then to cancel.
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
                ⏳ Deletion scheduled — the crab has started a countdown
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                It's confirmed. Password checked out, paperwork filed, and your account is now
                officially scheduled for deletion. The crab watched the whole thing from behind
                his umbrella, whispering &ldquo;they'll be back.&rdquo;
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 40px 28px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:16px 36px; border-radius:8px; background-color:#f4f5f7; border:1px solid #4A6184; font-family:Arial, Helvetica, sans-serif;">
                    <div style="font-size:13px; text-transform:uppercase; letter-spacing:0.5px; color:#888888; padding-bottom:4px;">
                      Everything will be permanently deleted on
                    </div>
                    <div style="font-size:22px; font-weight:bold; color:#4A6184;">
                      {date}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 24px 40px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#555555;">
              <p style="margin:0 0 16px 0;">
                <strong>Changed your mind?</strong> Just log in before {date} and the whole
                thing is cancelled &mdash; no questions asked, no awkward &ldquo;so... you're
                back&rdquo; conversation. The crab has been instructed to play it cool.
                He will not play it cool.
              </p>
              <p style="margin:0;">
                And if you haven't changed your mind &mdash; that's okay too. On {date} your
                data disappears for good, and you'll get one last goodbye email from us.
                The crab is already drafting it. It's mostly tears.
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 40px 32px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="border-radius:8px; background-color:#f4f5f7; border:1px solid #4A6184;">
                    <a href="{link}" target="_blank"
                       style="display:inline-block; padding:14px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; font-weight:bold; color:#4A6184; text-decoration:none; border-radius:8px;">
                      Log In &amp; Cancel Deletion
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
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Counting down (against our will),<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person, and one crab in the bargaining stage)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because your CancerBot account deletion was confirmed.<br>
                Logging in before {date} will cancel the deletion.
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
