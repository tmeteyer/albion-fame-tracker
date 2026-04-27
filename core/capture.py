"""
Packet capture thread using raw sockets (Windows built-in).
Gère le réassemblage des fragments Photon (CMD_SEND_FRAGMENT).
"""
import json
import os
import queue
import socket
import struct
import threading
import time
from typing import Dict, Optional, Tuple

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


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '0.0.0.0'


class FragmentBuffer:
    """Réassemble les messages Photon fragmentés."""

    def __init__(self):
        self._buffers: Dict[Tuple, dict] = {}

    def add(self, direction: str, payload: bytes) -> Optional[bytes]:
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
            result = bytearray(buf['total_len'])
            for _num, (offset, data) in buf['fragments'].items():
                result[offset:offset + len(data)] = data
            del self._buffers[key]
            return bytes(result)

        return None

    def cleanup(self, max_buffers: int = 64):
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
        self.cmd_type_counts: Dict[int, int] = {}
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

        local_ip = _get_local_ip()
        self.iface_name = local_ip

        if self.debug_mode:
            try:
                self._raw_file = open(EVENTS_LOG, 'w', encoding='utf-8')
            except IOError:
                pass

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
            sock.bind((local_ip, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            sock.settimeout(1.0)

            try:
                while not self._stop_event.is_set():
                    try:
                        data, _ = sock.recvfrom(65535)
                        self._on_raw_packet(data)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
            finally:
                try:
                    sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
                except OSError:
                    pass
                sock.close()

        except Exception as e:
            self.error = str(e)
        finally:
            if self._raw_file:
                self._raw_file.close()

    def _on_raw_packet(self, data: bytes):
        if len(data) < 20:
            return

        ihl = (data[0] & 0x0F) * 4
        if data[9] != 17:  # protocole UDP
            return
        if len(data) < ihl + 8:
            return

        sport = struct.unpack_from('>H', data, ihl)[0]
        dport = struct.unpack_from('>H', data, ihl + 2)[0]

        if sport != ALBION_PORT and dport != ALBION_PORT:
            return

        self.raw_count += 1
        direction = "S→C" if sport == ALBION_PORT else "C→S"
        udp_payload = data[ihl + 8:]

        if not udp_payload:
            return

        self._process_udp_payload(udp_payload, direction, time.time())

    def _process_udp_payload(self, data: bytes, direction: str, ts: float):
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

                self.cmd_type_counts[cmd_type] = self.cmd_type_counts.get(cmd_type, 0) + 1

                payload = data[offset + 12: offset + cmd_len]

                if cmd_type in (CMD_SEND_RELIABLE, CMD_SEND_UNRELIABLE, CMD_SEND_RELIABLE_EXT):
                    app_data = payload[4:] if cmd_type in (CMD_SEND_UNRELIABLE, CMD_SEND_RELIABLE_EXT) else payload
                    msg = parse_message(app_data)
                    if msg is not None:
                        self._dispatch(msg, direction, ts)
                    elif direction == "S→C" and self.debug_mode and self._raw_file:
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
