# The code stays out of the subject on purpose: email_brevo.py logs every
# subject (in production too, and those logs ship to Axiom), and a logged
# code is a working login. The preheader below still shows it in the inbox
# preview.
SUBJECT = "Your CancerBot sign-in code"

HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your CancerBot code</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Your code is {code}. It expires in {minutes} minutes.
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
            <td style="padding:24px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0;">Enter this code to sign in to CancerBot:</p>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:16px 40px 8px 40px;">
              <div style="display:inline-block; padding:16px 28px; background-color:#f4f5f7; border:1px solid #4A6184; border-radius:8px; font-family:'Courier New', Courier, monospace; font-size:34px; font-weight:bold; letter-spacing:10px; color:#032354;">
                {code}
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:16px 40px 32px 40px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#555555;">
              <p style="margin:0;">
                The code expires in {minutes} minutes and works once. Never share it &mdash;
                CancerBot will never ask you for it.
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because someone asked to sign in to CancerBot with this address.<br>
                If this wasn't you, you can safely ignore it.
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
