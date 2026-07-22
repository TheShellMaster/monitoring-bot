#!/usr/bin/env python3
"""
SSH Payload Proxy - Port 2053 (HTTP Injection) + Port 8443 (SSL Passthrough)

Version optimisée sans deadlock :
1. Lit le premier paquet réseau du client.
2. Si c'est un payload HTTP (CONNECT, GET, etc.), il répond 200 OK (si CONNECT) et nettoie le header.
3. Il conserve la partie SSH s'il l'a déjà reçue, sinon il lance le pont SSH directement.
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

HTTP_200 = b"HTTP/1.1 200 Connection Established\r\n\r\n"
HTTP_METHODS = (b"CONNECT", b"GET", b"POST", b"HEAD", b"PUT", b"DELETE", b"OPTIONS")


async def _pipe(src_reader, dst_writer):
    """Relaye les données d'un flux vers l'autre."""
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
    peer = writer.get_extra_info("peername")
    log.info(f"[{mode.upper()}] Connexion entrante de {peer}")

    leftover = b""
    if mode == "http":
        try:
            # On lit uniquement le premier paquet envoyé par l'application
            data = await asyncio.wait_for(reader.read(4096), timeout=3.0)
            if not data:
                writer.close()
                return

            # Vérifie si le paquet commence par une méthode HTTP connue
            first_word = data.split(None, 1)[0] if data.split(None, 1) else b""
            
            if first_word in HTTP_METHODS:
                log.info(f"[{mode.upper()}] Payload HTTP détecté de {peer}")
                
                # Si c'est un CONNECT, on renvoie immédiatement le 200 Connection Established
                if first_word == b"CONNECT" or b"CONNECT" in data:
                    writer.write(HTTP_200)
                    await writer.drain()
                    log.info(f"[{mode.upper()}] Réponse 200 OK envoyée à {peer}")
                
                # Extraction des données SSH si elles étaient déjà dans ce premier paquet
                if b"SSH-" in data:
                    idx = data.index(b"SSH-")
                    leftover = data[idx:]
                    log.info(f"[{mode.upper()}] Bannière SSH extraite du premier paquet pour {peer}")
                else:
                    leftover = b""
            else:
                # Si ce n'est pas du HTTP, on considère que c'est une connexion SSH directe
                leftover = data

        except Exception as e:
            log.warning(f"[{mode.upper()}] Erreur ou timeout lors de la lecture initiale de {peer}: {e}")
            writer.close()
            return

    # Connexion au serveur SSH local
    try:
        ssh_reader, ssh_writer = await asyncio.open_connection(SSH_HOST, SSH_PORT)
    except Exception as e:
        log.error(f"[{mode.upper()}] Impossible de se connecter à OpenSSH local : {e}")
        writer.close()
        return

    # Si on a extrait des octets SSH du premier paquet, on les envoie à SSH
    if leftover:
        try:
            ssh_writer.write(leftover)
            await ssh_writer.drain()
        except Exception as e:
            log.error(f"[{mode.upper()}] Impossible d'envoyer le reste SSH à OpenSSH : {e}")
            writer.close()
            ssh_writer.close()
            return

    # Pont bidirectionnel
    await asyncio.gather(
        _pipe(reader, ssh_writer),
        _pipe(ssh_reader, writer),
        return_exceptions=True,
    )
    log.info(f"[{mode.upper()}] Connexion terminée pour {peer}")


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
