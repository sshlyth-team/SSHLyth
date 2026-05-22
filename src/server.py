import sys
import os
import select
import threading
import datetime
import urllib.request
import urllib.parse
import json
import ssl
import re
import secrets

# Local lib/ dir where dependencies are installed by postinst
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit
import paramiko

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)

# threading mode + simple-websocket enables WebSocket without eventlet/gevent
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# DSM internal webapi — try HTTP first, fall back to HTTPS if HTTP is disabled
_DSM_WEBAPI_CANDIDATES = [
    'https://localhost:5001/webapi',
]

# SSL context that skips verification for localhost DSM self-signed cert
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
_https_opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_ctx))


def _check_dsm_session(cookie_header, syno_token=''):
    """Validate a DSM web session via SYNO.Core.System API.

    Always connects to localhost:5001 (same machine as Flask).
    Requires the SynoToken (CSRF token) from DSM's JS context.
    """
    if not syno_token:
        app.logger.debug('AUTH no SynoToken provided')
        return False

    url = 'https://localhost:5001/webapi/entry.cgi?api=SYNO.Core.System&version=3&method=info'
    try:
        req = urllib.request.Request(url)
        req.add_header('Cookie', cookie_header)
        req.add_header('X-SYNO-TOKEN', syno_token)
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; SSHlyth)')
        with _https_opener.open(req, timeout=3) as resp:
            result = json.loads(resp.read())
        success = result.get('success', False)
        app.logger.debug('AUTH localhost:5001 -> success=%s code=%s',
                         success, result.get('error', {}).get('code'))
        return success
    except Exception as e:
        app.logger.debug('AUTH localhost:5001 exception: %s', e)
        return False

_sessions: dict = {}
_lock = threading.Lock()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/validate-dsm')
def validate_dsm():
    if session.get('authenticated'):
        return jsonify({'valid': True})
    cookie_header = '; '.join(f'{k}={v}' for k, v in request.cookies.items())
    syno_token = request.headers.get('X-SYNO-TOKEN', '')
    app.logger.debug('VALIDATE token_present=%s', bool(syno_token))
    valid = _check_dsm_session(cookie_header, syno_token)
    if valid:
        session['authenticated'] = True
    return jsonify({'valid': valid})


@app.route('/login-dsm', methods=['POST'])
def login_dsm():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'valid': False, 'error': 'Username and password required'})

    params = urllib.parse.urlencode({
        'api': 'SYNO.API.Auth', 'version': '7', 'method': 'login',
        'account': username, 'passwd': password, 'format': 'sid',
    }).encode()
    try:
        req = urllib.request.Request(
            'https://localhost:5001/webapi/entry.cgi',
            data=params,
            headers={'Content-Type': 'application/x-www-form-urlencoded',
                     'User-Agent': 'Mozilla/5.0 (compatible; SSHlyth)'},
        )
        with _https_opener.open(req, timeout=10) as resp:
            result = json.loads(resp.read())
        app.logger.debug('LOGIN -> success=%s', result.get('success'))
        if result.get('success'):
            session['authenticated'] = True
            return jsonify({'valid': True})
        code = result.get('error', {}).get('code', 0)
        errors = {400: 'Invalid credentials', 401: 'Account disabled', 403: 'Permission denied'}
        return jsonify({'valid': False, 'error': errors.get(code, f'Login failed (code {code})')})
    except Exception as e:
        app.logger.debug('LOGIN exception: %s', e)
        return jsonify({'valid': False, 'error': 'Cannot connect to DSM'})


@socketio.on('ssh_connect')
def on_ssh_connect(data):
    if not session.get('authenticated'):
        emit('ssh_error', {'message': 'Not authorized. Please log in to DSM first.'})
        return

    sid      = request.sid
    host     = data.get('host', '127.0.0.1')
    port     = int(data.get('port', 22))
    username = data.get('username', '')
    password = data.get('password', '')
    cols     = int(data.get('cols', 220))
    rows     = int(data.get('rows', 50))

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, port=port, username=username, password=password, timeout=10)

        # Allocate a PTY so interactive programs (vi, nano, htop…) work correctly
        channel = client.invoke_shell(term='xterm-256color', width=cols, height=rows)
        channel.setblocking(False)

        with _lock:
            _sessions[sid] = {'client': client, 'channel': channel}

        emit('ssh_connected', {'message': f'Connected to {username}@{host}:{port}'})
        threading.Thread(target=_read_loop, args=(sid,), daemon=True).start()

    except Exception as exc:
        emit('ssh_error', {'message': str(exc)})


def _read_loop(sid):
    """Forward SSH channel output to the browser via SocketIO."""
    while True:
        with _lock:
            sess = _sessions.get(sid)
        if not sess:
            break
        ch = sess['channel']
        try:
            ready, _, _ = select.select([ch], [], [], 0.05)
            if ready:
                data = ch.recv(4096)
                if not data:
                    break
                socketio.emit('ssh_output',
                              {'data': data.decode('utf-8', errors='replace')},
                              to=sid)
            if ch.closed or ch.exit_status_ready():
                break
        except Exception:
            break

    socketio.emit('ssh_disconnected', {}, to=sid)
    with _lock:
        sess = _sessions.pop(sid, None)
    if sess:
        try:
            sess['client'].close()
        except Exception:
            pass


@socketio.on('ssh_input')
def on_ssh_input(data):
    with _lock:
        sess = _sessions.get(request.sid)
    if sess:
        try:
            sess['channel'].send(data.get('data', ''))
        except Exception:
            pass


@socketio.on('ssh_resize')
def on_ssh_resize(data):
    with _lock:
        sess = _sessions.get(request.sid)
    if sess:
        try:
            sess['channel'].resize_pty(
                width=int(data.get('cols', 80)),
                height=int(data.get('rows', 24))
            )
        except Exception:
            pass


@socketio.on('ssh_disconnect_req')
def on_ssh_disconnect_req():
    sid = request.sid
    with _lock:
        sess = _sessions.pop(sid, None)
    if sess:
        try:
            sess['client'].close()
        except Exception:
            pass
    emit('ssh_disconnected', {})


@socketio.on('disconnect')
def on_ws_disconnect():
    with _lock:
        sess = _sessions.pop(request.sid, None)
    if sess:
        try:
            sess['client'].close()
        except Exception:
            pass


def _ensure_ssl_cert(pkg_dir):
    """Generate a self-signed cert in the package dir if it doesn't exist yet."""
    cert_path = os.path.join(pkg_dir, 'ssl_cert.pem')
    key_path  = os.path.join(pkg_dir, 'ssl_key.pem')
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SSHlyth')])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .sign(key, hashes.SHA256())
        )
        with open(cert_path, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(key_path, 'wb') as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()
            ))
        return cert_path, key_path
    except Exception:
        return None, None


if __name__ == '__main__':
    _pkg_dir = os.path.dirname(os.path.abspath(__file__))

    import logging
    logging.basicConfig(
        filename=os.path.join(_pkg_dir, 'sshlyth.log'),
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    app.logger.setLevel(logging.DEBUG)

    _cert, _key = _ensure_ssl_cert(_pkg_dir)
    _ssl = (_cert, _key) if _cert else None

    socketio.run(app, host='0.0.0.0', port=7722, debug=False,
                 allow_unsafe_werkzeug=True, ssl_context=_ssl)
