#!/usr/bin/env python3
"""
SSH Payload Proxy - Port 2053 (HTTP Injection) + Port 8443 (SSL/TLS)
Supporte toutes les méthodes TCP : CONNECT, GET, POST, HEAD, PUT, DELETE, OPTIONS
Terminaison TLS/SSL avec SNI sur le port 8443
"""
import asyncio
import logging
import os
import ssl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SSH_HOST = "127.0.0.1"
SSH_PORT = 22
HTTP_PROXY_PORT = int(os.getenv("SSH_HTTP_PORT", 2053))
SSL_PROXY_PORT  = int(os.getenv("SSH_SSL_PORT",  8443))

_DIR = os.path.dirname(os.path.abspath(__file__))
SSL_CERT = os.getenv("SSL_CERT", os.path.join(_DIR, "ssl_proxy.crt"))
SSL_KEY  = os.getenv("SSL_KEY",  os.path.join(_DIR, "ssl_proxy.key"))

HTTP_200 = b"HTTP/1.1 200 Connection Established\r\n\r\n"
HTTP_METHODS = (b"CONNECT", b"GET", b"POST", b"HEAD", b"PUT", b"DELETE", b"OPTIONS")


async def _pipe(src_reader, dst_writer):
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

    if mode in ("http", "ssl"):
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if not data:
                writer.close()
                return

            first_word = data.split(None, 1)[0] if data.split(None, 1) else b""

            if first_word in HTTP_METHODS:
                log.info(f"[{mode.upper()}] Payload HTTP detecte de {peer}")
                writer.write(HTTP_200)
                await writer.drain()
                log.info(f"[{mode.upper()}] Reponse 200 OK envoyee a {peer} pour {first_word.decode(errors='ignore')}")

                if b"SSH-" in data:
                    idx = data.index(b"SSH-")
                    leftover = data[idx:]
                    log.info(f"[{mode.upper()}] Banniere SSH extraite du premier paquet pour {peer}")
                else:
                    leftover = b""
            else:
                leftover = data

        except asyncio.TimeoutError:
            log.warning(f"[{mode.upper()}] Timeout lecture initiale de {peer} - envoi direct a SSH")
            leftover = b""
        except Exception as e:
            log.warning(f"[{mode.upper()}] Erreur lecture initiale de {peer}: {e}")
            writer.close()
            return
    else:
        leftover = b""

    try:
        ssh_reader, ssh_writer = await asyncio.open_connection(SSH_HOST, SSH_PORT)
    except Exception as e:
        log.error(f"[{mode.upper()}] Impossible de se connecter a OpenSSH local : {e}")
        writer.close()
        return

    if leftover:
        try:
            ssh_writer.write(leftover)
            await ssh_writer.drain()
        except Exception as e:
            log.error(f"[{mode.upper()}] Impossible d'envoyer le reste SSH a OpenSSH : {e}")
            writer.close()
            ssh_writer.close()
            return

    await asyncio.gather(
        _pipe(reader, ssh_writer),
        _pipe(ssh_reader, writer),
        return_exceptions=True,
    )
    log.info(f"[{mode.upper()}] Connexion terminee pour {peer}")


async def main():
    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain(SSL_CERT, SSL_KEY)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    http_server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, mode="http"),
        "0.0.0.0",
        HTTP_PROXY_PORT,
    )
    ssl_server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, mode="ssl"),
        "0.0.0.0",
        SSL_PROXY_PORT,
        ssl=ssl_ctx,
    )
    log.info(f"Proxy SSH HTTP Injection demarre -> port {HTTP_PROXY_PORT}")
    log.info(f"Proxy SSH SSL/TLS demarre -> port {SSL_PROXY_PORT}")
    log.info(f"Tunnel vers OpenSSH -> {SSH_HOST}:{SSH_PORT}")

    async with http_server, ssl_server:
        await asyncio.gather(
            http_server.serve_forever(),
            ssl_server.serve_forever(),
        )


if __name__ == "__main__":
    asyncio.run(main())
