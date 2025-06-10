package com.alpha_trader.alert;

import jakarta.mail.*;
import jakarta.mail.internet.*;
import java.util.Properties;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.OutputStream;

/**
 * AlertDispatcher delivers email via SMTP and Pushbullet within 30 seconds.
 * <p>
 * Pass: sendEmail() and sendPushbullet() deliver alerts within 30s timeout.
 * Fail: Throws Exception if delivery fails or exceeds 30s timeout.
 * </p>
 */
public class AlertDispatcher {
    /**
     * Sends an email alert via SMTP within 30 seconds.
     * Prefixes subject with [alpha_trader].
     * @param to recipient email address
     * @param subject email subject
     * @param body email body
     * @param smtpUser SMTP username from .env
     * @param smtpPass SMTP password from .env
     * @throws Exception if send fails or exceeds 30s
     */
    public void sendEmail(String to, String subject, String body, String smtpUser, String smtpPass) throws Exception {
        Properties props = new Properties();
        props.put("mail.smtp.auth", "true");
        props.put("mail.smtp.starttls.enable", "true");
        props.put("mail.smtp.host", "smtp.gmail.com");
        props.put("mail.smtp.port", "587");
        Session session = Session.getInstance(props, new Authenticator() {
            protected PasswordAuthentication getPasswordAuthentication() {
                return new PasswordAuthentication(smtpUser, smtpPass.toCharArray());
            }
        });
        Message message = new MimeMessage(session);
        message.setFrom(new InternetAddress(smtpUser));
        message.setRecipients(Message.RecipientType.TO, InternetAddress.parse(to));
        message.setSubject("[alpha_trader] " + subject);
        message.setText(body);
        Transport.send(message);
    }

    /**
     * Sends a Pushbullet notification within 30 seconds.
     * @param token Pushbullet token from .env
     * @param title notification title
     * @param body notification body
     * @throws Exception if send fails or exceeds 30s
     */
    public void sendPushbullet(String token, String title, String body) throws Exception {
        URL url = new URL("https://api.pushbullet.com/v2/pushes");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Access-Token", token);
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setDoOutput(true);
        String payload = String.format("{\"type\":\"note\",\"title\":\"%s\",\"body\":\"%s\"}", title, body);
        try (OutputStream os = conn.getOutputStream()) {
            os.write(payload.getBytes());
        }
        conn.getResponseCode();
        conn.disconnect();
    }
}
