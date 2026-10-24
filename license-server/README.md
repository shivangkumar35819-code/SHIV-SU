# shivxroot license login service

Production API: `https://shivmodsstore.shop`. The VPS deployment uses an isolated `shivxroot-login` system user and systemd service, a virtual environment under `/opt/shivxroot-login`, and a database under `/var/lib/shivxroot-login`. Its Nginx virtual host is separate from existing domains. Secrets are in root-only `/etc/shivxroot-login.env` on the server and are not included in this repository.

On the VPS, `/opt/shivxroot-login/admin create-license` creates a license. Use the same command with `revoke --license KEY` or `reset-device --license KEY` for administration. The initial unbound license is stored in root-only `/root/shivxroot-first-license.txt`. No license keys are published in release assets.

The production server uses the October 2026 DB-IP City Lite database for approximate IP locations. IP Geolocation by DB-IP: https://db-ip.com (CC BY 4.0). Telegram messages include this attribution. The database is downloaded separately; it is not included in the APK or source repository. Cloudflare real-IP trust is restricted to official Cloudflare proxy networks, inside this virtual host only.

The Docker instructions below are an alternative deployment method, not the running VPS layout.

## Deploy on a Linux VPS

1. Point a domain's A record at the VPS. Install Docker with Compose and open TCP 80/443.
2. Copy this directory to the VPS. Copy `.env.example` to `.env`, restrict it with `chmod 600 .env`, and configure the domain and rotated Telegram bot token. Generate `SERVER_SECRET` with `python3 -c 'import secrets; print(secrets.token_hex(32))'`.
3. The owner of chat `7614397503` must first open `@licensemanagebot` and send `/start`. The server fixes this recipient; the Android client cannot choose a recipient. No messages have been sent as part of development/testing.
4. Run `docker compose up -d --build`. Caddy obtains HTTPS certificates automatically. Do not expose port 8080 or enable proxy trust on a public API listener.
5. Create a license: `docker compose exec api python server.py create-license`. Give the printed key to the intended user privately. The database stores its hash.
6. Configure Android Gradle property `LICENSE_SERVER_URL=https://your-domain.example` before a future build. With no URL, login fails closed and the UI says the service is not configured. There is no test bypass.

The bot token and server secret belong only in `.env` or your hosting secret manager. Never configure them as Android build properties. The token shared in chat should be replaced through BotFather before deployment.

## Login behavior

- User enters a license key and requests a six-digit code. The server sends the requested message format, in plain text, only to chat `7614397503`; no code or chat ID is returned to the app.
- IP comes from the HTTPS proxy. Device model comes from Android. Time is Asia/Kolkata. Approximate IP location is optional for other installations: provide a licensed GeoLite2 City or DB-IP City Lite database, mount it read-only into the API container and set `GEOIP_DATABASE` to its container path. Without it, the message honestly says location is unavailable; no GPS permission or external geolocation lookup is used.
- Server expiry is exactly 30 seconds after Telegram accepts the message. Admin must relay the code within that interval. The UI countdown starts earlier, before the request round trip, so it cannot extend server expiry.
- New requests replace the old challenge, are limited to one per 30 seconds per IP and license, and allow five incorrect code attempts. Codes are hashed with a server-side secret and used once.
- Successful verification atomically binds the license to an Android Keystore RSA key. Session validation requires proof of that key, including a fresh nonce, so copying the session token alone is insufficient. Another device is refused. Reinstall/reset can lose this key and requires an administrator reset.
- Backend sessions last 24 hours. The current Android app keeps successful login in local app storage and does not revalidate on foreground entry or periodically. Reopening the app and returning from file pickers do not show login loading. Clearing app data or reinstalling requires login again. Server revocation/reset blocks future verification; it cannot sign out an already activated offline app. Key duration is not enforced in that app flow.
- This gates the normal app UI and backend sessions. A modified APK or a device owner with root can patch local UI checks; it does not enforce access to kernel root outside this app.

## Administration

Revoke a license and sessions:

```sh
docker compose exec api python server.py revoke --license YOUR_LICENSE_KEY
```

Allow a replacement device (invalidates sessions and pending codes):

```sh
docker compose exec api python server.py reset-device --license YOUR_LICENSE_KEY
```

Back up the `licenses` volume and `.env` securely. Token/key storage, access logs, and Telegram retention should follow your privacy policy. The login page discloses IP/location/device sharing without identifying the destination chat.

## Tests

```sh
python -m pip install -r requirements.txt
python -m unittest -v test_server
```

Tests mock Telegram delivery; they never contact the bot or send user information. API integration uses Telegram's official `sendMessage` endpoint: https://core.telegram.org/bots/api#sendmessage.

Custom keys: `/opt/shivxroot-login/admin create-license --key 'Rahul123'` creates exactly `Rahul123`, with no suffix. `--name` is an alias for `--key`. Keys are case-sensitive; duplicates are rejected without modifying the existing license or its binding. Omitting the option still generates a random key. Use the complete key to log in, revoke, or reset a device.

## Telegram administration bot

`admin_bot.py` manages the same license database using a separate bot token. Only private messages whose sender and chat both match `TELEGRAM_ADMIN_ID` are accepted. The existing OTP delivery bot is unchanged.

- `/genkey` creates a random key; `/genkey ExactKey` also accepts a custom key.
- `/custom ExactKey` creates exactly that key; `/custom` opens a next-message prompt, cancelled by `/cancel`.
- `/list` or `/list 2` shows 20 hashed license IDs per page. Raw keys are not recoverable from the license table.
- `/status ExactKey`, `/revoke ExactKey`, `/reset ExactKey` inspect, revoke future verification, or reset device binding. Each accepts `id:FULL_HASH` from the list instead of the original key.
- Duplicate keys are rejected. Resetting a revoked key does not reactivate it.

Replies awaiting delivery are encrypted with a key derived from `SERVER_SECRET`. Database changes and encrypted replies commit in one transaction, so retrying an update after a delivery failure does not create another key. Restart the service after rotating the admin token or environment configuration. Only one poller should run for a token; an existing webhook must be removed before using polling.

For the existing systemd layout, place `admin_bot.py` and the updated `server.py` under `/opt/shivxroot-login`. Install `shivxroot-admin-bot.service` in `/etc/systemd/system`. Create root-only `/etc/shivxroot-admin-bot.env` with `ADMIN_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, and the same absolute `DATABASE_PATH` as the login API. The unit also reads `/etc/shivxroot-login.env` for `SERVER_SECRET`. Enable with `systemctl enable --now shivxroot-admin-bot`. Open the new bot in Telegram and press Start. `deploy_admin_bot.py HOST --deploy` performs backup, upload, mocked tests, Telegram menu configuration, and service setup using interactive secret prompts; it requires local Paramiko and root SSH access.

Docker Compose includes an `admin-bot` service sharing the `licenses` volume. Set `ADMIN_BOT_TOKEN` and `TELEGRAM_ADMIN_ID` in `.env`. No inbound bot port is needed.

Run all backend/bot tests with `python -m unittest -v test_server test_admin_bot`. Telegram calls are mocked in tests.
