import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _format_price(yen: int) -> str:
    man = yen // 10_000
    if man >= 10_000:
        oku = man // 10_000
        remainder = man % 10_000
        if remainder:
            return f"{oku}億{remainder:,}万円"
        return f"{oku}億円"
    return f"{man:,}万円"


def _build_html(alerts: list[dict]) -> str:
    rows = ""
    for a in alerts:
        kind_label = {
            "price_drop": "🔻 値下げ",
            "new_listing": "🆕 新着",
        }.get(a["kind"], a["kind"])

        if a["kind"] == "price_drop":
            diff = a["prev_price"] - a["price"]
            price_html = (
                f"<s style='color:#999'>{_format_price(a['prev_price'])}</s> → "
                f"<strong style='color:#c0392b'>{_format_price(a['price'])}</strong> "
                f"<span style='color:#c0392b'>(-{_format_price(diff)})</span>"
            )
        else:
            price_html = f"<strong style='color:#27ae60'>{_format_price(a['price'])}</strong>"

        rows += f"""
        <tr>
          <td style='padding:12px;border-bottom:1px solid #eee'>{kind_label}</td>
          <td style='padding:12px;border-bottom:1px solid #eee'>
            <a href='{a["url"]}' style='color:#2980b9;text-decoration:none'>{a["name"] or "（名称不明）"}</a><br>
            <small style='color:#666'>{a.get("address","")}</small>
          </td>
          <td style='padding:12px;border-bottom:1px solid #eee'>{price_html}</td>
          <td style='padding:12px;border-bottom:1px solid #eee;color:#666'>{a["alert_name"]}</td>
        </tr>
        """

    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    return f"""
    <html><body style='font-family:sans-serif;color:#333;max-width:800px;margin:0 auto'>
      <h2 style='background:#2980b9;color:#fff;padding:16px;border-radius:4px'>
        🏠 不動産アラート通知
      </h2>
      <p style='color:#666'>{now} 時点の情報です</p>
      <table style='width:100%;border-collapse:collapse;margin-top:16px'>
        <thead>
          <tr style='background:#f5f5f5'>
            <th style='padding:12px;text-align:left'>種別</th>
            <th style='padding:12px;text-align:left'>物件</th>
            <th style='padding:12px;text-align:left'>価格</th>
            <th style='padding:12px;text-align:left'>アラート名</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style='color:#aaa;font-size:12px;margin-top:24px'>
        このメールは自動送信されています。配信停止は config.yaml の email.to を変更してください。
      </p>
    </body></html>
    """


def send(email_config: dict, alerts: list[dict]) -> None:
    smtp_user = os.environ.get("GMAIL_ADDRESS")
    smtp_pass = os.environ.get("GMAIL_APP_PASSWORD")
    if not smtp_user or not smtp_pass:
        raise EnvironmentError(
            "GMAIL_ADDRESS または GMAIL_APP_PASSWORD が環境変数に設定されていません"
        )

    recipients = email_config.get("to", [])
    if not recipients:
        logger.warning("送信先メールアドレスが config.yaml に設定されていません")
        return

    subject = f"【不動産アラート】{len(alerts)}件の通知 - {datetime.now().strftime('%Y/%m/%d')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)

    html_body = _build_html(alerts)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())
        logger.info(f"メール送信完了: {len(alerts)}件のアラートを {recipients} へ送信")
    except smtplib.SMTPException as e:
        logger.error(f"メール送信失敗: {e}")
        raise
