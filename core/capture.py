"""
Packet capture thread using scapy (requires npcap on Windows).
Gère le réassemblage des fragments Photon (CMD_SEND_FRAGMENT).
"""
import json
import os
import queue
import socket
import struct
import threading
import time
from typing import Dict, List, Optional, Tuple

ALBION_PORT = 5056
EVENTS_LOG = os.path.join(os.path.dirname(__file__), '..', 'events_log.jsonl')

CMD_SEND_FRAGMENT        = 8
CMD_SEND_RELIABLE_EXT    = 11  # variante Photon Albion, même structure que SEND_RELIABLE


def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _detect_iface() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        from scapy.all import conf
        for iface_name, iface in conf.ifaces.items():
            if hasattr(iface, 'ip') and iface.ip == local_ip:
                return iface_name
    except Exception:
        pass
    return None


class FragmentBuffer:
    """Réassemble les messages Photon fragmentés."""

    def __init__(self):
        # clé: (direction, start_seq) → {total_len, count, fragments: {frag_num: data}}
        self._buffers: Dict[Tuple, dict] = {}

    def add(self, direction: str, payload: bytes) -> Optional[bytes]:
        """
        Ajoute un fragment. Retourne le message complet si tous les fragments
        sont arrivés, sinon None.
        """
        if len(payload) < 20:
            return None
        try:
            start_seq    = struct.unpack_from('>I', payload, 0)[0]
            frag_count   = struct.unpack_from('>I', payload, 4)[0]
            frag_num     = struct.unpack_from('>I', payload, 8)[0]
            total_len    = struct.unpack_from('>I', payload, 12)[0]
            frag_offset  = struct.unpack_from('>I', payload, 16)[0]
            frag_data    = payload[20:]
        except struct.error:
            return None

        key = (direction, start_seq)
        if key not in self._buffers:
            self._buffers[key] = {
                'total_len': total_len,
                'count': frag_count,
                'fragments': {},
            }

        buf = self._buffers[key]
        buf['fragments'][frag_num] = (frag_offset, frag_data)

        if len(buf['fragments']) == buf['count']:
            # Tous les fragments reçus → réassembler
            result = bytearray(buf['total_len'])
            for _num, (offset, data) in buf['fragments'].items():
                result[offset:offset + len(data)] = data
            del self._buffers[key]
            return bytes(result)

        return None

    def cleanup(self, max_buffers: int = 64):
        """Évite les fuites mémoire si des fragments arrivent incomplets."""
        if len(self._buffers) > max_buffers:
            oldest = list(self._buffers.keys())[:len(self._buffers) - max_buffers]
            for k in oldest:
                del self._buffers[k]


class CaptureThread(threading.Thread):

    def __init__(self, packet_queue: queue.Queue, debug_mode: bool = False):
        super().__init__(daemon=True, name="AlbionCapture")
        self.packet_queue = packet_queue
        self.debug_mode = debug_mode
        self._stop_event = threading.Event()
        self._raw_file = None
        self.error: Optional[str] = None
        self.iface_name: Optional[str] = None
        self.raw_count: int = 0
        self.parsed_count: int = 0
        self.frag_count: int = 0
        self.frag_done: int = 0
        self.cmd_type_counts: Dict[int, int] = {}   # cmd_type → nb reçus
        self._frag_buf = FragmentBuffer()

    def stop(self):
        self._stop_event.set()

    def run(self):
        if not is_admin():
            self.error = (
                "Droits administrateur requis pour capturer les paquets réseau.\n"
                "Fermez le tracker et relancez lancer.bat avec\n"
                "clic droit → 'Exécuter en tant qu'administrateur'."
            )
            return

        try:
            from scapy.all import sniff, conf
            conf.verb = 0
        except ImportError:
            self.error = "scapy non installé. Lancez install.bat."
            return

        detected = _detect_iface()
        self.iface_name = detected or "toutes les interfaces"

        from scapy.all import get_if_list
        iface_arg = detected if detected else get_if_list()

        if self.debug_mode:
            try:
                self._raw_file = open(EVENTS_LOG, 'w', encoding='utf-8')
            except IOError:
                pass

        try:
            sniff(
                iface=iface_arg,
                prn=self._on_packet,
                store=False,
                stop_filter=lambda _: self._stop_event.is_set(),
            )
        except Exception as e:
            self.error = str(e)
        finally:
            if self._raw_file:
                self._raw_file.close()

    def _on_packet(self, packet):
        from scapy.all import UDP
        if UDP not in packet:
            return

        udp = packet[UDP]
        if udp.sport != ALBION_PORT and udp.dport != ALBION_PORT:
            return

        self.raw_count += 1
        direction = "S→C" if udp.sport == ALBION_PORT else "C→S"
        raw_data: bytes = bytes(udp.payload)

        if not raw_data:
            return

        ts = time.time()
        self._process_udp_payload(raw_data, direction, ts)

    def _process_udp_payload(self, data: bytes, direction: str, ts: float):
        """Parse le paquet Photon, gère les fragments."""
        if len(data) < 12:
            return

        from .photon import parse_message, CMD_SEND_RELIABLE, CMD_SEND_UNRELIABLE

        try:
            cmd_count = data[3]
            offset = 12

            for _ in range(cmd_count):
                if offset + 12 > len(data):
                    break

                cmd_type = data[offset]
                cmd_len = struct.unpack_from('>I', data, offset + 4)[0]

                if cmd_len < 12 or offset + cmd_len > len(data):
                    break

                # Compter tous les types de commandes reçus
                self.cmd_type_counts[cmd_type] = self.cmd_type_counts.get(cmd_type, 0) + 1

                payload = data[offset + 12: offset + cmd_len]

                if cmd_type in (CMD_SEND_RELIABLE, CMD_SEND_UNRELIABLE, CMD_SEND_RELIABLE_EXT):
                    app_data = payload[4:] if cmd_type in (CMD_SEND_UNRELIABLE, CMD_SEND_RELIABLE_EXT) else payload
                    msg = parse_message(app_data)
                    if msg is not None:
                        self._dispatch(msg, direction, ts)
                    elif direction == "S→C" and self.debug_mode and self._raw_file:
                        # Logger les payloads S->C non parsés pour trouver les events manquants
                        try:
                            self._raw_file.write(json.dumps({
                                'debug': 'unparsed',
                                'cmd': cmd_type,
                                'hex': app_data[:48].hex(),
                            }) + '\n')
                            self._raw_file.flush()
                        except IOError:
                            pass

                elif cmd_type == CMD_SEND_FRAGMENT:
                    self.frag_count += 1
                    reassembled = self._frag_buf.add(direction, payload)
                    if reassembled is not None:
                        self.frag_done += 1
                        msg = parse_message(reassembled)
                        if msg is not None:
                            self._dispatch(msg, direction, ts)

                offset += cmd_len

        except (struct.error, IndexError):
            pass

        self._frag_buf.cleanup()

    def _dispatch(self, msg: dict, direction: str, ts: float):
        """Envoie un message parsé dans la queue et l'écrit dans le log."""
        self.parsed_count += 1
        entry = {
            'mode': 'photon',
            'ts': ts,
            'dir': direction,
            'type': msg['type'],
            'code': msg['code'],
            'params': self._serialize_params(msg.get('params', {})),
        }
        if 'return_code' in msg:
            entry['return_code'] = msg['return_code']
        self.packet_queue.put(entry)

        if self.debug_mode and self._raw_file:
            try:
                log_entry = {
                    'time': time.strftime('%H:%M:%S', time.localtime(ts)),
                    'dir': direction,
                    'type': msg['type'],
                    'code': msg['code'],
                    'params': entry['params'],
                }
                if 'return_code' in msg:
                    log_entry['return_code'] = msg['return_code']
                self._raw_file.write(json.dumps(log_entry) + '\n')
                self._raw_file.flush()
            except IOError:
                pass

    @staticmethod
    def _serialize_params(params: dict) -> dict:
        result = {}
        for k, v in params.items():
            if isinstance(v, bytes):
                result[k] = v.hex()
            elif isinstance(v, dict):
                result[k] = CaptureThread._serialize_params(v)
            elif isinstance(v, (list, tuple)):
                result[k] = [x.hex() if isinstance(x, bytes) else x for x in v]
            else:
                result[k] = v
        return result
