"""Email bodies sent via Brevo (src/utils/email_brevo.py).

Content lives here in the repo rather than in a provider dashboard (unlike the
dormant SendGrid path in email.py, whose EMAIL_TEMPLATES are opaque IDs
pointing at templates stored in SendGrid) — fully version-controlled and
testable, and portable to any future provider.

Placeholders are plain str.format() fields (`{name}`, `{link}`, `{date}`,
`{model}`), ported from the original SendGrid Handlebars source
(`{{name}}` -> `{name}`, `{{{link}}}` -> `{link}`, double vs. triple brace
distinguishing "HTML-escape this" from "this is a URL, don't"). `name` is the
only field that ever carries user-supplied text (a registrant's own name), so
it's the only one HTML-escaped in `render()` below — SendGrid's `{{name}}`
did this automatically; now that we render the HTML ourselves, that has to
happen on our side.
"""
import html as _html

_VERIFICATION_HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome to CancerBot</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Welcome aboard! Here's your link to get started with CancerBot.
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
                🎗️ Making a stressful process a little less stressful
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                Welcome to CancerBot, and thank you for signing up!
              </p>
              <p style="margin:0 0 16px 0;">
                We built CancerBot to help make a confusing, stressful process a little less
                confusing and stressful. We truly hope it helps you &mdash; that's the whole point.
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
                      Get Started
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
                A quick behind-the-scenes fact: CancerBot is a <strong>one-person project</strong>.
                No big company, no army of developers &mdash; just one human who cares (and drinks
                way too much coffee). So if something looks a bit wonky, be patient &mdash; the
                entire engineering, support, and snack-procurement department is on it.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 32px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#fef9ec; border-left:4px solid #f59e0b; border-radius:6px;">
                <tr>
                  <td style="padding:16px 20px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#78716c;">
                    <strong style="color:#92400e;">Important disclaimer:</strong>
                    CancerBot is not a doctor. It never went to medical school, it doesn't own a
                    stethoscope, and it can't tell you to say &ldquo;ahh.&rdquo; Its results are
                    informational only and may be incomplete or inaccurate.
                    <strong>Always consult a qualified physician</strong> about your health, your
                    results, and any medical decisions. Seriously &mdash; always.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Wishing you the very best,<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because you signed up for CancerBot.<br>
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

_PASSWORD_RESET_HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset your CancerBot password</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Here's your link to reset your CancerBot password. It expires in 24 hours.
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
                🔑 Password reset request
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                Forgot your password? No worries &mdash; it happens to everyone. Chemo-brain,
                treatment fatigue, or just being a regular human with 74 passwords to remember:
                whatever the reason, we're not judging. Frankly, we're impressed you remembered
                you had an account.
              </p>
              <p style="margin:0 0 16px 0;">
                Click below to set a new one:
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
                      Reset My Password
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
              <p style="margin:0 0 16px 0;">
                This link expires in <strong>24 hours</strong> &mdash; so unlike most things on
                your to-do list, this one actually has a deadline.
              </p>
              <p style="margin:0;">
                A friendly reminder from your one-person team: if anything acts up, be patient
                &mdash; the entire security department (also me) is on it.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 32px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#fef9ec; border-left:4px solid #f59e0b; border-radius:6px;">
                <tr>
                  <td style="padding:16px 20px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#78716c;">
                    <strong style="color:#92400e;">Didn't request this?</strong>
                    You can safely ignore this email and your password will stay exactly as it is
                    (wherever you left it).
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Take care,<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because a password reset was requested for your CancerBot account.<br>
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

_ACCOUNT_DELETED_HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your CancerBot account is deleted</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Your account has been deleted. The crab is taking it hard.
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
                💔 Account deleted — the crab is taking it hard
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                So... it's really happening. Your account has been deleted, as requested.
              </p>
              <p style="margin:0 0 16px 0;">
                We want you to know we're handling it very maturely. The crab has folded up the
                beach umbrella, closed his little book, and is now sitting alone in the corner
                of the beach. In the dark. It's not even nighttime &mdash; he brought his own dark.
              </p>
              <p style="margin:0 0 16px 0;">
                The entire staff (one person) held an emergency farewell meeting (stared at the
                wall) and voted unanimously (1&ndash;0) to miss you.
              </p>
              <p style="margin:0 0 16px 0;">
                But truly &mdash; if you're leaving because you're done with all of this and
                moving on with your life: <strong>that is the best possible reason</strong>, and
                we're genuinely happy for you. That was the whole point.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 28px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#f4f5f7; border-left:4px solid #4A6184; border-radius:6px;">
                <tr>
                  <td style="padding:16px 20px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#555555;">
                    <strong style="color:#333333;">The boring-but-important part:</strong>
                    your account and personal data have been permanently deleted from our systems,
                    as requested. Gone. The crab couldn't keep them even if he wanted to
                    (and he wanted to).
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding:0 40px 28px 40px;">
              <div style="padding-bottom:14px; font-family:Arial, Helvetica, sans-serif; font-size:15px; color:#555555;">
                If you ever need us again &mdash; for any reason, hopefully none &mdash; the door is always open:
              </div>
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="border-radius:8px; background-color:#f4f5f7; border:1px solid #4A6184;">
                    <a href="{link}" target="_blank"
                       style="display:inline-block; padding:14px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; font-weight:bold; color:#4A6184; text-decoration:none; border-radius:8px;">
                      Come Back Anytime
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">
                Take care of yourself. That's an order from the crab.
              </p>
              <p style="margin:0;">
                With a single dramatic tear,<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person, now alone with a crab)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                This email confirms the deletion of your CancerBot account. Since your account no
                longer exists, this is the last email you'll receive from us.<br>
                The crab asked us to add that he's fine. He is not fine.
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

_DELETE_ACCOUNT_REQUEST_HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Confirm your account deletion</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Confirm your CancerBot account deletion. The crab demands you read this first.
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
                🗑️ Account deletion request — the crab is in denial
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                We received a request to delete your CancerBot account. The crab read it three
                times, put down his little book, and asked us to check: <em>are you sure?</em>
              </p>
              <p style="margin:0 0 16px 0;">
                If you are, click below. The link opens a page where you'll confirm with your
                password &mdash; just to make sure it's really you and not someone who dislikes crabs.
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
                      Confirm Account Deletion
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
              <p style="margin:0 0 16px 0;">
                <strong>What happens next:</strong> after you confirm, your account enters a
                <strong>7-day waiting period</strong>, then everything is permanently deleted.
                Think of it as a one-week window to change your mind &mdash; the crab calls it
                &ldquo;the bargaining stage&rdquo; and will spend it looking hopefully at the door.
                Log back in any time during those 7 days to cancel the deletion.
              </p>
              <p style="margin:0;">
                No hard feelings either way. If you're leaving because you're done with all of
                this and moving on with your life &mdash; that's the best possible reason.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 32px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background-color:#fef9ec; border-left:4px solid #f59e0b; border-radius:6px;">
                <tr>
                  <td style="padding:16px 20px; font-family:Arial, Helvetica, sans-serif; font-size:14px; line-height:1.6; color:#78716c;">
                    <strong style="color:#92400e;">Didn't request this?</strong>
                    Ignore this email and nothing will happen &mdash; your account stays put.
                    But since someone asked to delete it, we'd also recommend changing your
                    password, just to be safe. The crab suggests something with more than
                    one claw... character.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Hoping you misclicked,<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person, and one very anxious crab)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because an account deletion was requested for your CancerBot account.<br>
                If this wasn't you, no action is needed &mdash; your account will not be deleted.
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

_DELETE_ACCOUNT_SCHEDULED_HTML = """<!DOCTYPE html>
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

_DELETE_ACCOUNT_CANCELLED_HTML = """<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your account deletion is cancelled</title>
</head>
<body style="margin:0; padding:0; background-color:#0F1827; -webkit-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all;">
    Deletion cancelled. Your account stays. The crab is beside himself.
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
                🎉 Deletion cancelled — the crab is beside himself
              </div>
            </td>
          </tr>

          <tr>
            <td style="padding:36px 40px 8px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0 0 16px 0;">Hi {name},</p>
              <p style="margin:0 0 16px 0;">
                You logged in, and just like that &mdash; <strong>your account deletion is
                cancelled.</strong> Everything stays exactly where you left it.
              </p>
              <p style="margin:0 0 16px 0;">
                We'd love to tell you the crab handled the news with dignity. He did not.
                There was scuttling. There was a little dance. The umbrella is back up,
                the little book is open again, and he's pretending this whole thing never
                happened &mdash; exactly as instructed.
              </p>
              <p style="margin:0 0 16px 0;">
                Welcome back. No questions asked. (He had questions. We confiscated them.)
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
                      Back to CancerBot
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
                Changed your mind about changing your mind? No drama &mdash; you can start the
                deletion process again anytime from your account settings. The crab will simply
                begin the entire grieving cycle from the top. He's getting quite good at it.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px 36px 40px; font-family:Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#333333;">
              <p style="margin:0;">
                Delighted (professionally restrained),<br>
                <strong>The CancerBot Team</strong> <span style="color:#888888;">(a.k.a. that one person, and one visibly relieved crab)</span>
              </p>
            </td>
          </tr>

          <tr>
            <td align="center" style="background-color:#f9fafb; padding:20px 40px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-family:Arial, Helvetica, sans-serif; font-size:12px; line-height:1.5; color:#9ca3af;">
                You received this email because the scheduled deletion of your CancerBot account was cancelled.<br>
                If this wasn't you, we recommend changing your password from your account settings.
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

_FALLBACK_ALERT_HTML = """<!DOCTYPE html>
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

TEMPLATES = {
  "verification": {
    "subject": "Welcome to CancerBot — let's get started 🎗️",
    "html": _VERIFICATION_HTML,
  },
  "password_reset": {
    "subject": "Reset your CancerBot password 🔑",
    "html": _PASSWORD_RESET_HTML,
  },
  "account_deleted": {
    "subject": "Your CancerBot account is deleted 💔 (the crab is taking it hard)",
    "html": _ACCOUNT_DELETED_HTML,
  },
  "delete_account_request": {
    "subject": "Account deletion request — the crab is in denial 🗑️",
    "html": _DELETE_ACCOUNT_REQUEST_HTML,
  },
  "delete_account_scheduled": {
    "subject": "Your CancerBot account deletion is scheduled ⏳",
    "html": _DELETE_ACCOUNT_SCHEDULED_HTML,
  },
  "delete_account_cancelled": {
    "subject": "Deletion cancelled — the crab is beside himself 🎉",
    "html": _DELETE_ACCOUNT_CANCELLED_HTML,
  },
  "fallback_alert": {
    "subject": "⚠️ Token limit reached: {model}",
    "html": _FALLBACK_ALERT_HTML,
  },
}


def render(template_key: str, **fields) -> tuple[str, str]:
  """Return (subject, rendered_html) for a template key.

  `name` is HTML-escaped if present (the only field ever carrying user
  text); `link`/`date`/`model` are substituted as-is, matching the original
  SendGrid Handlebars source's double-vs-triple-brace distinction.
  """
  entry = TEMPLATES[template_key]
  safe_fields = dict(fields)
  if isinstance(safe_fields.get("name"), str):
    safe_fields["name"] = _html.escape(safe_fields["name"])
  return entry["subject"].format(**fields), entry["html"].format(**safe_fields)
