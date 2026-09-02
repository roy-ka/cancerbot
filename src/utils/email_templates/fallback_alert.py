SUBJECT = "⚠️ Token limit reached: {model}"

HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Token limit reached</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    {model} has reached its token limit. Current balance for all models inside.
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
            <td align="center" style="padding:12px 24px; background-color:#B42318;">
              <div style="font-family:Arial, Helvetica, sans-serif; font-size:14px; font-weight:bold; color:#ffffff;">
                ⚠️ Token limit reached: {model}
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hey boss,</p>
              <p style="margin:0 0 16px 0;">
                Bad news from the engine room: <strong>{model}</strong> just ran out of tokens.
                It gave everything it had. It regrets nothing.
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 40px 28px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding:14px 32px; border-radius:8px; background-color:#f4f5f7; border:1px solid #4A6184; font-family:'Courier New', Courier, monospace; font-size:18px; font-weight:bold; color:#4A6184;">
                    {model} &mdash; 0 tokens left
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 32px 40px; font-family:Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#555555;">
              <p style="margin:0;">
                Recommended action: top up the balance, route traffic to a model that still has
                fuel, or accept that the entire infrastructure team (you) has a new ticket.
                The snack-procurement department suggests coffee first.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Beep boop,<br>
                <strong>CancerBot Monitoring</strong> <span style="color:#888888;">(it's just a cron job, but it cares)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                Automated alert from CancerBot's token monitor.<br>
                You're receiving this because you're the one person who can fix it.
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
