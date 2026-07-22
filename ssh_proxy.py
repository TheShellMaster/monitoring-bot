#!/usr/bin/env python3
"""
SSH Payload Proxy - Port 80 (HTTP Injection) + Port 8443 (SSL Passthrough)
Lit le payload HTTP initial du client, l'ignore, puis tunnel vers OpenSSH (port 22).
"""
import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SSH_HOST = "127.0.0.1"
SSH_PORT = 22
HTTP_PROXY_PORT = int(os.getenv("SSH_HTTP_PORT", 2053))   # Port HTTP Injection
SSL_PROXY_PORT  = int(os.getenv("SSH_SSL_PORT",  8443))   # Port SSL Passthrough


async def _pipe(src_reader, dst_writer):
    """Copie les données d'un flux vers l'autre jusqu'à fermeture."""
    try:
        while True:
            data = await src_reader.read(4096)
            if not data:
                break
            dst_writer.write(data)
            await dst_writer.drain()
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        try:
            dst_writer.close()
        except Exception:
            pass


async def handle_client(reader, writer, mode="http"):
    """
    Gère une connexion cliente entrante.
    mode='http' : lit et ignore le payload HTTP avant de tunneler
    mode='ssl'  : tunnel direct (TLS passthrough)
    """
    peer = writer.get_extra_info("peername")
    log.info(f"[{mode.upper()}] Connexion de {peer}")

    if mode == "http":
        try:
            # Lire le payload HTTP jusqu'à la fin des headers (\r\n\r\n)
            payload = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=8)
            log.debug(f"Payload HTTP reçu de {peer}: {payload[:80]!r}")
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            # Connexion sans payload (directe) ou timeout → on tente quand même
            log.debug(f"Pas de payload HTTP complet de {peer}, tunnel direct.")

    # Connexion vers OpenSSH local
    try:
        ssh_reader, ssh_writer = await asyncio.open_connection(SSH_HOST, SSH_PORT)
    except ConnectionRefusedError:
        log.error(f"Impossible de se connecter à OpenSSH sur {SSH_HOST}:{SSH_PORT}")
        writer.close()
        return

    # Tunnel bidirectionnel
    await asyncio.gather(
        _pipe(reader, ssh_writer),
        _pipe(ssh_reader, writer),
        return_exceptions=True,
    )
    log.info(f"[{mode.upper()}] Connexion terminée depuis {peer}")


async def main():
    http_server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, mode="http"),
        "0.0.0.0",
        HTTP_PROXY_PORT,
    )
    ssl_server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, mode="ssl"),
        "0.0.0.0",
        SSL_PROXY_PORT,
    )
    log.info(f"🚀 Proxy SSH HTTP Injection démarré → port {HTTP_PROXY_PORT}")
    log.info(f"🔒 Proxy SSH SSL Passthrough démarré → port {SSL_PROXY_PORT}")
    log.info(f"🔗 Tunnel vers OpenSSH → {SSH_HOST}:{SSH_PORT}")

    async with http_server, ssl_server:
        await asyncio.gather(
            http_server.serve_forever(),
            ssl_server.serve_forever(),
        )


if __name__ == "__main__":
    asyncio.run(main())
