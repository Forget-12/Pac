#!/usr/bin/env python3
"""Local HTTP CONNECT proxy -> upstream SOCKS5 (with auth).
Chromium tidak mendukung SOCKS5 auth, jadi bridge ini yang menanganinya.
Pakai:
  python local_socks_bridge.py --port 8899 --upstream-host gate-eu.vaultproxies.com \
      --upstream-port 1080 --user USER --pass PASS
"""
import argparse
import asyncio
import struct
import sys


async def read_exact(reader, n):
    return await reader.readexactly(n)


async def socks5_connect(host, port, user, password):
    r, w = await asyncio.open_connection(host, port)
    # greeting: version 5, methods: no-auth + user/pass
    w.write(b"\x05\x02\x00\x02")
    await w.drain()
    ver, method = await read_exact(r, 2)
    if ver != 5:
        raise RuntimeError(f"bad socks version {ver}")
    if method == 0x02:
        u = user.encode()
        p = password.encode()
        w.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        await w.drain()
        _ver, status = await read_exact(r, 2)
        if status != 0:
            raise RuntimeError(f"socks auth failed {status}")
    elif method != 0x00:
        raise RuntimeError(f"socks method not supported {method}")
    # CONNECT with domain name
    h = host.encode()
    w.write(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + struct.pack("!H", port))
    await w.drain()
    ver, rep, rsv, atyp = await read_exact(r, 4)
    if ver != 5 or rep != 0:
        raise RuntimeError(f"socks connect failed rep={rep}")
    if atyp == 0x01:
        await read_exact(r, 4 + 2)
    elif atyp == 0x03:
        ln = (await read_exact(r, 1))[0]
        await read_exact(r, ln + 2)
    elif atyp == 0x04:
        await read_exact(r, 16 + 2)
    else:
        raise RuntimeError(f"bad atyp {atyp}")
    return r, w


async def pipe(src, dst, label=""):
    total = 0
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            total += len(data)
            dst.write(data)
            await dst.drain()
    except Exception as e:
        print(f"[bridge] pipe {label} err: {e}", file=sys.stderr, flush=True)
    finally:
        print(f"[bridge] pipe {label} done bytes={total}", file=sys.stderr, flush=True)
        try:
            dst.close()
        except Exception:
            pass


async def handle(client_r, client_w, args):
    try:
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = await client_r.read(4096)
            if not chunk:
                return
            header += chunk
            if len(header) > 65536:
                return
        first = header.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = first.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client_w.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            await client_w.drain()
            return
        target = parts[1]
        if ":" in target:
            host, p = target.rsplit(":", 1)
            port = int(p)
        else:
            host, port = target, 443
        # bytes after the CONNECT header (biasanya kosong)
        rest = header.split(b"\r\n\r\n", 1)[1]
        print(f"[bridge] CONNECT {host}:{port} rest={len(rest)}", file=sys.stderr, flush=True)
        up_r, up_w = await socks5_connect(
            args.upstream_host, args.upstream_port, args.user, args.password)
        print(f"[bridge] socks ok {host}:{port}", file=sys.stderr, flush=True)
        client_w.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await client_w.drain()
        if rest:
            up_w.write(rest)
            await up_w.drain()
        await asyncio.gather(
            pipe(client_r, up_w, "c->u"),
            pipe(up_r, client_w, "u->c"),
        )
    except Exception as e:
        print(f"[bridge] {e}", file=sys.stderr, flush=True)
        try:
            client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await client_w.drain()
        except Exception:
            pass
    finally:
        try:
            client_w.close()
        except Exception:
            pass


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--upstream-host", default="gate-eu.vaultproxies.com")
    ap.add_argument("--upstream-port", type=int, default=1080)
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass", dest="password", required=True)
    args = ap.parse_args()

    async def cb(r, w):
        await handle(r, w, args)

    server = await asyncio.start_server(cb, "127.0.0.1", args.port)
    print(f"[bridge] listening 127.0.0.1:{args.port} -> "
          f"socks5://{args.upstream_host}:{args.upstream_port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
