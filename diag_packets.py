"""
Affiche les premiers paquets S->C du fichier raw_packets.jsonl
pour analyser le format Photon réel.
"""
import json, struct, os

LOG = os.path.join(os.path.dirname(__file__), 'raw_packets.jsonl')

if not os.path.exists(LOG):
    print("Fichier raw_packets.jsonl introuvable.")
    print("Lance le tracker, active la capture, joue quelques secondes, puis relance ce script.")
    exit(1)

print(f"Lecture de {LOG}\n")
shown = 0
with open(LOG, encoding='utf-8') as f:
    for line in f:
        entry = json.loads(line)
        if entry.get('dir') != 'S→C':
            continue
        raw = bytes.fromhex(entry['hex'])
        length = entry['len']

        print(f"=== Paquet S→C, {length} octets ===")
        print(f"Hex brut : {raw.hex()}")

        if len(raw) >= 12:
            peer_id  = struct.unpack_from('>H', raw, 0)[0]
            flags    = raw[2]
            cmd_count = raw[3]
            ts       = struct.unpack_from('>I', raw, 4)[0]
            challenge = struct.unpack_from('>I', raw, 8)[0]
            print(f"  Header: PeerID={peer_id:#06x}  flags={flags:#04x}  "
                  f"cmd_count={cmd_count}  ts={ts}  challenge={challenge:#010x}")

            offset = 12
            for i in range(min(cmd_count, 8)):
                if offset + 12 > len(raw):
                    print(f"  [Cmd {i+1}] trop court pour lire le header")
                    break
                ctype  = raw[offset]
                chan   = raw[offset+1]
                cflags = raw[offset+2]
                cres   = raw[offset+3]
                clen   = struct.unpack_from('>I', raw, offset+4)[0]
                cseq   = struct.unpack_from('>I', raw, offset+8)[0]
                payload = raw[offset+12 : offset+clen] if clen >= 12 and offset+clen <= len(raw) else b''
                print(f"  [Cmd {i+1}] type={ctype} ({ctype:#04x})  chan={chan}  "
                      f"flags={cflags}  len={clen}  seq={cseq}")
                if payload:
                    print(f"           payload ({len(payload)} oct): {payload[:32].hex()}")
                advance = clen if clen >= 12 else 12
                offset += advance
        print()

        shown += 1
        if shown >= 8:
            break

print(f"Terminé ({shown} paquets S→C affichés).")
