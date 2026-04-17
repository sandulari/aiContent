"""Professional HTML email templates for Shadow Pages."""


def _base_layout(content: str) -> str:
    """Wrap content in the shared email layout shell."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Shadow Pages</title>
</head>
<body style="margin:0;padding:0;background-color:#111111;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#111111;">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#1a1a1a;border-radius:12px;overflow:hidden;">
          <!-- Logo -->
          <tr>
            <td align="center" style="padding:32px 40px 16px 40px;">
              <span style="font-size:28px;font-weight:700;color:#22c55e;letter-spacing:-0.5px;">SP</span>
              <span style="font-size:20px;font-weight:600;color:#e5e5e5;margin-left:8px;letter-spacing:-0.3px;">Shadow Pages</span>
            </td>
          </tr>
          <!-- Content -->
          <tr>
            <td style="padding:8px 40px 32px 40px;">
              {content}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 40px;border-top:1px solid #2a2a2a;">
              <p style="margin:0;font-size:12px;color:#666666;line-height:1.5;text-align:center;">
                Shadow Pages &mdash; Your content, amplified.<br />
                You received this email because you have an account with Shadow Pages.<br />
                If you didn't request this email, you can safely ignore it.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def welcome_email(display_name: str) -> tuple[str, str]:
    """Return (subject, html) for the welcome email sent after registration."""
    subject = "Welcome to Shadow Pages"
    content = f"""\
<h1 style="margin:0 0 16px 0;font-size:24px;font-weight:700;color:#f5f5f5;">Welcome, {display_name}!</h1>
<p style="margin:0 0 16px 0;font-size:16px;color:#cccccc;line-height:1.6;">
  Your Shadow Pages account is ready. You now have access to powerful tools for
  discovering, curating, and exporting viral content for your brand.
</p>
<p style="margin:0 0 24px 0;font-size:16px;color:#cccccc;line-height:1.6;">
  Get started by connecting your Instagram page and exploring your personalized dashboard.
</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
  <tr>
    <td align="center" style="background-color:#22c55e;border-radius:8px;">
      <a href="{_get_app_url()}/dashboard"
         style="display:inline-block;padding:14px 32px;font-size:16px;font-weight:600;color:#111111;text-decoration:none;">
        Go to Dashboard
      </a>
    </td>
  </tr>
</table>"""
    return subject, _base_layout(content)


def password_reset_email(display_name: str, reset_url: str) -> tuple[str, str]:
    """Return (subject, html) for the password-reset email."""
    subject = "Reset your Shadow Pages password"
    content = f"""\
<h1 style="margin:0 0 16px 0;font-size:24px;font-weight:700;color:#f5f5f5;">Password Reset</h1>
<p style="margin:0 0 16px 0;font-size:16px;color:#cccccc;line-height:1.6;">
  Hi {display_name}, we received a request to reset your password.
  Click the button below to choose a new one. This link expires in 1 hour.
</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto 24px auto;">
  <tr>
    <td align="center" style="background-color:#22c55e;border-radius:8px;">
      <a href="{reset_url}"
         style="display:inline-block;padding:14px 32px;font-size:16px;font-weight:600;color:#111111;text-decoration:none;">
        Reset Password
      </a>
    </td>
  </tr>
</table>
<p style="margin:0 0 8px 0;font-size:13px;color:#888888;line-height:1.5;">
  If the button doesn't work, copy and paste this URL into your browser:
</p>
<p style="margin:0;font-size:13px;color:#22c55e;line-height:1.5;word-break:break-all;">
  {reset_url}
</p>
<p style="margin:24px 0 0 0;font-size:13px;color:#888888;line-height:1.5;">
  If you didn't request a password reset, you can safely ignore this email.
  Your password will remain unchanged.
</p>"""
    return subject, _base_layout(content)


def _get_app_url() -> str:
    import os

    return os.getenv("APP_URL", "http://localhost:8080")
