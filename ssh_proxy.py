#!/usr/bin/env python3
"""
SSH Payload Proxy - Port 2053 (HTTP Injection) + Port 8443 (SSL Passthrough)

Gère intelligemment tous les types de payloads (CONNECT, GET, POST, etc.)
sans bloquer ni corrompre le protocole SSH sous-jacent.
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
    Analise le premier paquet envoyé par le client.
    Si c'est du HTTP :
      - Identifie si c'est une méthode CONNECT (nécessite une réponse HTTP 200).
      - Recherche le début de la bannière SSH ("SSH-") dans le paquet.
      - Extrait et retourne la partie SSH (leftover), en jetant le payload HTTP.
    Si ce n'est pas du HTTP :
      - Laisse tout passer intact pour le serveur SSH.
    """
    is_connect = False
    try:
        # Lecture du premier paquet (timeout de 5 secondes pour éviter de bloquer)
        buf = await asyncio.wait_for(reader.read(4096), timeout=5)
        if not buf:
            return False, b""

        # Récupération du premier mot pour tester si c'est du HTTP
        parts = buf.split(None, 1)
        first_word = parts[0] if parts else b""

        if first_word in HTTP_METHODS:
            log.info(f"[HTTP Proxy] Payload détecté avec la méthode : {first_word.decode('utf-8', errors='ignore')}")
            
            # C'est un tunnel CONNECT si la méthode est CONNECT ou s'il y a du CONNECT dans le payload
            if first_word == b"CONNECT" or b"CONNECT" in buf:
                is_connect = True

            # Recherche de la bannière SSH
            if b"SSH-" in buf:
                idx = buf.index(b"SSH-")
                leftover = buf[idx:]
                log.info(f"[HTTP Proxy] Bannière SSH trouvée dans le premier paquet. Transmission immédiate.")
            else:
                leftover = b""
                log.info(f"[HTTP Proxy] En attente de la bannière SSH après réponse HTTP.")

            return is_connect, leftover
        else:
            # Ce n'est pas du HTTP (connexion SSH directe sans payload)
            return False, buf

    except Exception as e:
        log.warning(f"[HTTP Proxy] Erreur ou timeout lors de l'analyse du payload : {e}")
        return False, b""


async def handle_client(reader, writer, mode="http"):
    """
    Gère une connexion cliente entrante.
    mode='http' : filtre le payload HTTP avant de rediriger vers OpenSSH
    mode='ssl'  : tunnel direct (SSL Passthrough)
    """
    peer = writer.get_extra_info("peername")
    log.info(f"[{mode.upper()}] Connexion reçue de {peer}")

    leftover = b""
    if mode == "http":
        is_connect, leftover = await _consume_http_payload(reader)

        # Si c'est un payload de type CONNECT, on doit renvoyer la réponse de connexion établie
        if is_connect:
            try:
                writer.write(HTTP_200)
                await writer.drain()
                log.info(f"[{mode.upper()}] Réponse HTTP 200 renvoyée à {peer}")
            except Exception as e:
                log.error(f"[{mode.upper()}] Impossible de renvoyer le HTTP 200 à {peer} : {e}")
                writer.close()
                return

    # Connexion vers le serveur OpenSSH local
    try:
        ssh_reader, ssh_writer = await asyncio.open_connection(SSH_HOST, SSH_PORT)
    except Exception as e:
        log.error(f"[{mode.upper()}] Impossible de joindre le serveur SSH local ({SSH_HOST}:{SSH_PORT}) : {e}")
        try:
            writer.close()
        except Exception:
            pass
        return

    # Si on a extrait des octets SSH du premier paquet, on les envoie à SSH
    if leftover:
        try:
            ssh_writer.write(leftover)
            await ssh_writer.drain()
        except Exception as e:
            log.error(f"[{mode.upper()}] Erreur lors de l'envoi du leftover SSH : {e}")
            writer.close()
            ssh_writer.close()
            return

    # Lancement du tunnel bidirectionnel
    await asyncio.gather(
        _pipe(reader, ssh_writer),
        _pipe(ssh_reader, writer),
        return_exceptions=True,
    )
    log.info(f"[{mode.upper()}] Connexion fermée pour {peer}")


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
