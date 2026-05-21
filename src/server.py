import sys
import os
import select
import threading
import datetime

# Local lib/ dir where dependencies are installed by postinst
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import paramiko

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sshlyth'

# threading mode + simple-websocket enables WebSocket without eventlet/gevent
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

_sessions: dict = {}
_lock = threading.Lock()


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('ssh_connect')
def on_ssh_connect(data):
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
    _cert, _key = _ensure_ssl_cert(_pkg_dir)
    _ssl = (_cert, _key) if _cert else None

    socketio.run(app, host='0.0.0.0', port=7722, debug=False,
                 allow_unsafe_werkzeug=True, ssl_context=_ssl)
