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
- Sessions last 24 hours, validate on foreground entry and every 30 seconds while foregrounded. No network means protected UI is unavailable. Revocation takes effect on the next validation.
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
