"""Interactive deployment helper; credentials are prompted, never stored locally."""
import argparse
import getpass
import difflib
import json
import shlex
import time
from pathlib import Path

import paramiko


def run(client, command):
    _, out, err = client.exec_command(command, timeout=90)
    output, errors = out.read().decode(), err.read().decode()
    if output:
        print(output)
    if errors:
        print(errors)
    if out.channel.recv_exit_status():
        raise RuntimeError("Remote command failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--finish", action="store_true", help="Finish using existing uploaded files and secrets")
    parser.add_argument("--start-only", action="store_true", help="Start installed service when Telegram is temporarily unavailable")
    args = parser.parse_args()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username="root", password=getpass.getpass("VPS password: "),
                   timeout=20, look_for_keys=False, allow_agent=False)
    try:
        if args.start_only:
            run(client, 'systemd-analyze verify /etc/systemd/system/shivxroot-admin-bot.service && '
                'systemctl daemon-reload && systemctl enable --now shivxroot-admin-bot && '
                'systemctl is-active shivxroot-login shivxroot-admin-bot && '
                'systemctl show shivxroot-admin-bot --property=SubState,NRestarts,ExecMainStatus')
            run(client, 'curl --max-time 15 --fail --silent https://shivmodsstore.shop/healthz')
            return
        if args.finish:
            run(client, "systemd-analyze verify /etc/systemd/system/shivxroot-admin-bot.service")
            probe = '''import json, urllib.request, urllib.error, time
from pathlib import Path
token = dict(line.split('=', 1) for line in Path('/etc/shivxroot-admin-bot.env').read_text().splitlines())['ADMIN_BOT_TOKEN']
def call(method, payload):
    for attempt in range(3):
        try:
            request = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=15) as response: result=json.load(response)
            return result['result']
        except urllib.error.HTTPError as error:
            if error.code >= 500 and attempt < 2:
                time.sleep(2); continue
            data=json.loads(error.read()); print('Telegram error:', error.code, data.get('description', '').replace(token, '[hidden]')); raise SystemExit(1)
        except Exception as error:
            if attempt < 2:
                time.sleep(2); continue
            print('Telegram connection error:', type(error).__name__); raise SystemExit(1)
print('Bot username: @' + call('getMe', {})['username'])
if call('getWebhookInfo', {}).get('url'):
    raise SystemExit('Existing webhook detected; left unchanged')
commands = [('genkey','Generate random key'), ('custom','Create exact custom key'), ('list','List licenses'), ('status','Check key status'), ('revoke','Block future logins'), ('reset','Reset device binding'), ('help','Show help'), ('cancel','Cancel custom key entry')]
call('setMyCommands', {'commands':[{'command':c, 'description':d} for c,d in commands]})
print('New bot command menu configured')
'''
            run(client, '/opt/shivxroot-login/.venv/bin/python -c ' + shlex.quote(probe))
            run(client, 'systemctl daemon-reload && systemctl enable --now shivxroot-admin-bot && '
                'systemctl is-active shivxroot-login shivxroot-admin-bot && '
                'systemctl show shivxroot-admin-bot --property=SubState,NRestarts,ExecMainStatus')
            run(client, 'curl --fail --silent https://shivmodsstore.shop/healthz')
            return
        if not args.deploy:
            run(client, "systemctl show shivxroot-login --property=ActiveState,User,ExecStart,WorkingDirectory; "
                "ls -ld /opt/shivxroot-login /opt/shivxroot-login/* /var/lib/shivxroot-login; "
                "sed -n 's/=.*//p' /etc/shivxroot-login.env")
            with client.open_sftp() as sftp:
                with sftp.open('/opt/shivxroot-login/server.py') as source:
                    remote = source.read().decode()
            local = Path(__file__).with_name('server.py').read_text(encoding='utf-8')
            print('\n'.join(difflib.unified_diff(remote.splitlines(), local.splitlines(),
                                               fromfile='remote/server.py', tofile='local/server.py')))
            return
        token = getpass.getpass("New admin bot token: ").strip()
        if not token or any(char.isspace() for char in token):
            raise ValueError("Invalid token")
        root = Path(__file__).resolve().parent
        stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
        backup = '/opt/shivxroot-login/backup-admin-bot-' + stamp
        run(client, 'install -d -m 700 ' + backup + '; cp -p /opt/shivxroot-login/server.py ' + backup + '/server.py')
        with client.open_sftp() as sftp:
            with sftp.open('/etc/shivxroot-login.env') as source:
                existing = source.read().decode()
            values = {}
            for line in existing.splitlines():
                if line.strip() and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    pieces = shlex.split(value)
                    values[key] = ' '.join(pieces)
            database = values['DATABASE_PATH']
            code = ('import sqlite3; src=sqlite3.connect(' + repr(database) + '); '
                    'dst=sqlite3.connect(' + repr(backup + '/licenses.sqlite3') + '); '
                    'src.backup(dst); dst.close(); src.close()')
            run(client, '/opt/shivxroot-login/.venv/bin/python -c ' + shlex.quote(code))
            for name in ('server.py', 'admin_bot.py', 'test_server.py', 'test_admin_bot.py'):
                target = '/opt/shivxroot-login/' + name
                with sftp.open(target + '.new', 'w') as output:
                    output.write((root / name).read_text(encoding='utf-8'))
                sftp.chmod(target + '.new', 0o644)
                sftp.posix_rename(target + '.new', target)
            target = '/etc/shivxroot-admin-bot.env'
            with sftp.open(target + '.new', 'w') as output:
                sftp.chmod(target + '.new', 0o600)
                output.write('ADMIN_BOT_TOKEN=' + token + '\nTELEGRAM_ADMIN_ID=7614397503\n'
                             + 'DATABASE_PATH=' + database + '\n')
            sftp.posix_rename(target + '.new', target)
            sftp.put(str(root / 'shivxroot-admin-bot.service'), '/etc/systemd/system/shivxroot-admin-bot.service')
        run(client, 'cd /opt/shivxroot-login && .venv/bin/python -m unittest -v test_server test_admin_bot')
        probe = '''import json, urllib.request
from pathlib import Path
token = dict(line.split('=', 1) for line in Path('/etc/shivxroot-admin-bot.env').read_text().splitlines())['ADMIN_BOT_TOKEN']
def call(method, payload):
    request = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if not result.get('ok'): raise ValueError()
        return result['result']
    except Exception:
        raise SystemExit('Telegram setup failed (secret URL hidden)')
print('Bot username: @' + call('getMe', {})['username'])
if call('getWebhookInfo', {}).get('url'):
    raise SystemExit('An existing webhook is configured; polling not started')
commands = [('genkey', 'Generate a random license key'), ('custom', 'Create your own exact key'), ('list', 'List license statuses'), ('status', 'Check a key'), ('revoke', 'Revoke future logins'), ('reset', 'Reset device binding'), ('help', 'Show help'), ('cancel', 'Cancel custom key entry')]
call('setMyCommands', {'commands': [{'command': c, 'description': d} for c, d in commands], 'scope': {'type': 'chat', 'chat_id': 7614397503}})
print('Telegram owner menu configured')
'''
        run(client, '/opt/shivxroot-login/.venv/bin/python -c ' + shlex.quote(probe))
        run(client, 'systemctl daemon-reload && systemctl enable --now shivxroot-admin-bot && '
            'systemctl is-active shivxroot-login shivxroot-admin-bot && '
            'systemctl show shivxroot-admin-bot --property=SubState,NRestarts,ExecMainStatus')
        run(client, "curl --fail --silent https://shivmodsstore.shop/healthz")
        print('Backup saved at ' + backup)
    finally:
        client.close()


if __name__ == "__main__":
    main()
