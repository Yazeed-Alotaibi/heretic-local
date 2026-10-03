"""Run the real built UI against isolated data and the already-running local engine."""
import argparse
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

from heretic_gateway.app import ORIGINS, create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-url', default='http://127.0.0.1:8081')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='heretic-ui-smoke-') as directory, socket.socket() as listener:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        ORIGINS.add(origin)
        app = create_app(Path(directory), model_url=args.model_url, ui_root=root.parent / 'ui/dist')
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
                                               access_log=False, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]})
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                if not thread.is_alive():
                    raise RuntimeError('Owned test server failed to start')
                time.sleep(.1)
            if not server.started:
                raise RuntimeError('Owned test server startup timed out')
            result = subprocess.run(['node', str(root.parent / 'scripts/browser-smoke.mjs')],
                                    cwd=root.parent, timeout=180, check=False,
                                    env={**os.environ, 'HERETIC_TEST_URL': origin})
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            if thread.is_alive():
                raise RuntimeError('Test server did not stop')
            ORIGINS.remove(origin)


if __name__ == '__main__':
    main()
