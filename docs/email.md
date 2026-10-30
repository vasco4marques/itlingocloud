# Email

Production sends email through the Brevo SMTP relay. An administrator configured the relay manually in the Odoo database. Git does not contain the SMTP credentials or the mail server record.

Do not send a test email, click Test Connection, or process the mail queue on production before you read [Queue and scheduler](#queue-and-scheduler). The queue contains old messages that can reach real recipients.

## Where the configuration is

- The outgoing mail server record is in the database (`ir_mail_server`). Open it at Settings > Technical > Email > Outgoing Mail Servers. This menu requires the developer mode. Settings > General Settings > Emails > Outgoing Email Servers opens the same list.
- The default sender and the public URL are system parameters in the database. Open them at Settings > Technical > System Parameters.
- The company email is in Settings > Companies.
- The `email_from` option is in the production `/opt/odoo/odoo.docker.conf`. Git contains the same value in `odoo.docker.conf.example`.

A database backup contains all of these database items. Odoo keeps the SMTP password as clear text in `ir_mail_server.smtp_pass`. Thus, protect each database backup as a secret.

## Current production values

These values were read from production on 2026-10-30 with read-only queries:

- Outgoing mail server: one active record.
- SMTP Server: `smtp-relay.brevo.com`.
- SMTP Port: `2525`.
- Connection Encryption: None.
- Authenticate with: Username. The username is a Brevo SMTP login in the `smtp-brevo.com` domain. A password is set.
- FROM Filtering: `no-reply@itlingo.pt`.
- System parameter `mail.default.from_filter`: `no-reply@itlingo.pt`.
- System parameters `mail.default.from` (`no-reply@itlingo.pt`) and `mail.catchall.domain` (`itlingo.pt`). Odoo 19 reads these old parameters only when it creates an Alias Domain record. No Alias Domain record exists, so Odoo does not receive replies or bounces.
- Company email: `no-reply@itlingo.pt`.
- System parameter `web.base.url`: `https://cloud.itlingo.pt`. The parameter `web.base.url.freeze` is not set.
- `odoo.docker.conf`: `email_from = no-reply@itlingo.pt` and `max_cron_threads = 0`.

Risk: with Connection Encryption None, Odoo does not request TLS. Thus, Odoo can send the SMTP key and the messages in clear text. This statement comes from the configuration only. Nobody examined the network traffic. The Brevo instructions for port 2525 say "leave this field empty unless you're using port 465" ([Brevo SMTP setup](https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP)). They recommend port 587 with TLS, and 2525 when 587 is blocked ([Brevo SMTP ports](https://help.brevo.com/hc/en-us/articles/10905415650322-Which-SMTP-port-should-I-use-Port-587-465-or-2525)). The public Brevo documents do not state if port 2525 accepts STARTTLS. Do not change this value on production without the owner. A change needs one real test connection.

## Required credentials

The owner of the Brevo account supplies these values. The current owner of the Brevo account is not recorded in this repository. Before the handover, the owner must give the next administrator access to the Brevo account or to new SMTP credentials.

- `<BREVO_SMTP_LOGIN>`: the SMTP login from the Brevo account.
- `<BREVO_SMTP_KEY>`: an SMTP key from the Brevo account. It is the SMTP password. It is not the Brevo account password.

Do not put these values in Git, in documents, in chat, or in email. Give them to the next administrator through a password manager. Do not copy the value from `ir_mail_server.smtp_pass` to transfer it. Create a new SMTP key in the Brevo account, enter it in Odoo, and then delete the old key in Brevo.

## Configure a new database

Do these steps only on a database without old queued mail. On a restored copy of production, the record and the queue already exist. Refer to [Queue and scheduler](#queue-and-scheduler).

1. Set `max_cron_threads = 0` in the Odoo configuration file. Restart Odoo.
2. Enable the developer mode.
3. Open Settings > Technical > System Parameters.
4. Set `web.base.url` to the public URL, for example `https://cloud.itlingo.pt`. Odoo writes this value when an administrator signs in. Behind the reverse proxy, the value is correct only if `proxy_mode = True` and the proxy sends the public host and scheme. If the value is wrong, add `web.base.url.freeze` with the value `True`.
5. Make sure that the Odoo configuration file contains `email_from = no-reply@itlingo.pt`. Without an Alias Domain, Odoo uses this option as the default sender.
6. Open Settings > Companies. Set the company email to `no-reply@itlingo.pt`.
7. Open Settings > Technical > Email > Outgoing Mail Servers. Click New.
8. Set Name to a descriptive name, for example `Brevo`.
9. Set SMTP Server to `smtp-relay.brevo.com` and SMTP Port to `2525`.
10. Set Connection Encryption. Refer to the risk in [Current production values](#current-production-values).
11. Set Authenticate with to Username.
12. Set Username to `<BREVO_SMTP_LOGIN>` and Password to `<BREVO_SMTP_KEY>`.
13. Set FROM Filtering to `no-reply@itlingo.pt`.
14. Save the record.

Odoo selects the mail server whose FROM Filtering matches the sender. If a message has another sender, for example the email of a user, Odoo replaces the sender with the default sender (`email_from`). If the sender domain is not authorized in Brevo, Brevo can refuse the message.

The current SMTP port is `2525`. Do not change the port before you confirm that the host can open outgoing connections to the new port.

## Verify without sending

Do not use Test Connection. It opens a real SMTP connection.

1. Open the outgoing mail server record. Make sure that the values agree with [Current production values](#current-production-values).
2. Open Settings > Technical > System Parameters. Make sure that `web.base.url` is the public HTTPS URL.
3. On the host, read the configuration file without the secret lines:

   ```sh
   docker exec itlingo-odoo grep -v -i -E 'passw|secret|key|token' /etc/odoo/odoo.conf
   ```

   The output must contain `email_from = no-reply@itlingo.pt` and `max_cron_threads = 0`.
4. To read the server record without the password, run a read-only query. Do not select `smtp_pass` or `smtp_user`.

   ```sql
   BEGIN READ ONLY;
   SELECT id, active, smtp_host, smtp_port, smtp_encryption,
          smtp_authentication, from_filter,
          smtp_pass IS NOT NULL AND smtp_pass <> '' AS has_password
     FROM ir_mail_server;
   ROLLBACK;
   ```

## Queue and scheduler

Production runs without the Odoo scheduler. Refer to [deployment.md](deployment.md#scheduler-and-outgoing-mail).

- Odoo sends invitation and password reset emails immediately. These emails do not wait for the scheduler. They can reach real recipients.
- Other messages wait in the mail queue (`mail_mail`, state `outgoing`). The queue contains old messages that were not sent.
- The cron job "Mail: Email Queue Manager" is active in the database, and its next run date is in the past. If the scheduler starts, this job runs immediately and tries to send the old queue. Delivery is not guaranteed, because Brevo or the recipient servers can refuse messages. Other active mail jobs, for example "Digest Emails", also run.

Do not do these actions until the owner reviews the old queue:

- Do not set `max_cron_threads` above 0.
- Do not click Run Manually on a mail cron job.
- Do not click Send Now or Retry in Settings > Technical > Email > Emails.
- Do not click Test Connection on the outgoing mail server.

Do not copy production data or the production mail server into a local database. A local Odoo with the scheduler sends the copied queue through Brevo.

## DNS

Public DNS records for `itlingo.pt` on 2026-10-30:

- MX: `mail-pt.securemail.pro`. The receiving mailbox provider is not Brevo.
- SPF: `v=spf1 include:spf.webapps.net ~all`. This record does not include Brevo. This is not necessarily a defect. The SPF requirements of providers are different, and DKIM alone can satisfy DMARC.
- Brevo domain verification: a `brevo-code` TXT record exists.
- DKIM: `brevo1._domainkey` and `brevo2._domainkey` are CNAME records to hosts in `dkim.brevo.com`.
- DMARC: `v=DMARC1; p=none`, with reports to Brevo.

The DNS records do not show if Brevo marks the domain or the sender as authenticated. Examine the domain and sender status in the Brevo account. If you change the DNS records, keep the Brevo DKIM records.
