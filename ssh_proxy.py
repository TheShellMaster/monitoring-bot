#!/usr/bin/env python3
"""
SSH Payload Proxy - Port 2053 (HTTP Injection) + Port 8443 (SSL Passthrough)

Gère deux types de payloads :
  - CONNECT  : Lit tous les headers, répond HTTP/1.0 200, puis tunnel SSH
  - GET/POST : Lit tous les headers, les ignore silencieusement, puis tunnel SSH
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

HTTP_200 = b"HTTP/1.0 200 Connection established\r\n\r\n"
# Méthodes HTTP reconnues comme payload (à consommer avant le tunnel)
HTTP_METHODS = (b"CONNECT", b"GET", b"POST", b"HEAD", b"PUT", b"DELETE", b"OPTIONS")


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


async def _consume_http_payload(reader):
    """
    Lit et consomme TOUT le payload HTTP (peut contenir plusieurs blocs CONNECT/GET).
    Retourne (is_connect, leftover_bytes)
    """
    is_connect = False
    buf = b""
    try:
        # Timeout court : si dans 8s le payload n'est pas terminé, on passe
        buf = await asyncio.wait_for(reader.read(4096), timeout=8)
        if not buf:
            return is_connect, buf

        # Détecter le type de méthode
        if buf.startswith(b"CONNECT"):
            is_connect = True

        # Consommer les blocks HTTP complets (\r\n\r\n)
        while True:
            if b"\r\n\r\n" in buf:
                idx = buf.index(b"\r\n\r\n") + 4
                remaining = buf[idx:]
                # Si ce qui reste commence encore par une méthode HTTP → autre bloc payload
                if any(remaining.startswith(m) for m in HTTP_METHODS):
                    buf = remaining
                    continue
                else:
                    # Ce n'est plus du HTTP, c'est le début du vrai trafic SSH !
                    buf = remaining
                    break
            else:
                # Lire la suite du bloc HTTP incomplet
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=3)
                    if not chunk:
                        break
                    buf += chunk
                except asyncio.TimeoutError:
                    break

        log.debug(f"Payload HTTP consommé (is_connect={is_connect}), reste {len(buf)} octets SSH.")
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
        log.debug("Fin ou timeout lors de la lecture du payload HTTP")

    return is_connect, buf


async def handle_client(reader, writer, mode="http"):
    """
    Gère une connexion cliente entrante.
    mode='http' : lit et consomme le payload HTTP avant de tunneler
    mode='ssl'  : tunnel direct (TLS passthrough côté client)
    """
    peer = writer.get_extra_info("peername")
    log.info(f"[{mode.upper()}] Connexion de {peer}")

    leftover = b""
    if mode == "http":
        is_connect, leftover = await _consume_http_payload(reader)

        # Si payload CONNECT → répondre 200 pour débloquer le client SSH Custom
        if is_connect:
            try:
                writer.write(HTTP_200)
                await writer.drain()
                log.debug(f"Réponse HTTP 200 envoyée à {peer}")
            except Exception:
                writer.close()
                return

    # Connexion vers OpenSSH local
    try:
        ssh_reader, ssh_writer = await asyncio.open_connection(SSH_HOST, SSH_PORT)
    except ConnectionRefusedError:
        log.error(f"Impossible de se connecter à OpenSSH sur {SSH_HOST}:{SSH_PORT}")
        try:
            writer.close()
        except Exception:
            pass
        return

    # Si on a "trop" lu (début de la connexion SSH collé au header HTTP), on l'envoie à SSH
    if leftover:
        try:
            ssh_writer.write(leftover)
            await ssh_writer.drain()
        except Exception:
            pass

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
