"""
Photon binary protocol parser — Protocol18 (Albion Online / Photon Realtime).
"""
import struct
from typing import Any, Dict, List, Optional, Tuple

# Command types
CMD_ACK              = 1
CMD_CONNECT          = 2
CMD_VERIFY_CONNECT   = 3
CMD_DISCONNECT       = 4
CMD_PING             = 5
CMD_SEND_RELIABLE    = 6
CMD_SEND_UNRELIABLE  = 7
CMD_SEND_FRAGMENT    = 8

# Message types (outer Photon wrapper — old-style codes still used by Albion)
MSG_OP_REQUEST           = 2
MSG_OP_RESPONSE          = 3
MSG_EVENT                = 4
MSG_INTERNAL_OP_REQUEST  = 6
MSG_INTERNAL_OP_RESPONSE = 7

# Protocol18 type codes (parameter values)
P18_UNKNOWN          = 0
P18_BOOLEAN          = 2
P18_BYTE             = 3
P18_SHORT            = 4
P18_FLOAT            = 5
P18_DOUBLE           = 6
P18_STRING           = 7
P18_NULL             = 8
P18_COMPRESSED_INT   = 9
P18_COMPRESSED_LONG  = 10
P18_INT1             = 11   # 1-byte positive int
P18_INT1_NEG         = 12   # 1-byte negative int
P18_INT2             = 13   # 2-byte positive int
P18_INT2_NEG         = 14   # 2-byte negative int
P18_LONG1            = 15
P18_LONG1_NEG        = 16
P18_LONG2            = 17
P18_LONG2_NEG        = 18
P18_CUSTOM           = 19
P18_DICTIONARY       = 20
P18_HASHTABLE        = 21
P18_OBJECT_ARRAY     = 23
P18_BOOL_FALSE       = 27   # 0 bytes, value = False
P18_BOOL_TRUE        = 28   # 0 bytes, value = True
P18_SHORT_ZERO       = 29   # 0 bytes, value = 0
P18_INT_ZERO         = 30   # 0 bytes, value = 0
P18_LONG_ZERO        = 31   # 0 bytes, value = 0
P18_FLOAT_ZERO       = 32   # 0 bytes, value = 0.0
P18_DOUBLE_ZERO      = 33   # 0 bytes, value = 0.0
P18_BYTE_ZERO        = 34   # 0 bytes, value = 0
P18_ARRAY            = 64
P18_BOOL_ARRAY       = 66
P18_BYTE_ARRAY       = 67
P18_SHORT_ARRAY      = 68
P18_FLOAT_ARRAY      = 69
P18_DOUBLE_ARRAY     = 70
P18_STRING_ARRAY     = 71
P18_COMPRESSED_INT_ARRAY  = 73
P18_COMPRESSED_LONG_ARRAY = 74
P18_CUSTOM_ARRAY     = 83
P18_DICTIONARY_ARRAY = 84
P18_HASHTABLE_ARRAY  = 85
P18_CUSTOM_SLIM_MIN  = 128
P18_CUSTOM_SLIM_MAX  = 228


class PhotonParseError(Exception):
    pass


# ─── Protocol18 value readers ─────────────────────────────────────────────────

def _read_compressed_int(data: bytes, offset: int) -> Tuple[int, int]:
    b = data[offset]; offset += 1
    if b == 0:
        return 0, offset
    sign = (b & 1) == 1
    result = (b >> 1) & 0x3F
    shift = 6
    while b & 0x80:
        if offset >= len(data):
            raise PhotonParseError("EOF in compressed int")
        b = data[offset]; offset += 1
        result |= (b & 0x7F) << shift
        shift += 7
    return (-result if sign else result), offset


def _read_compressed_long(data: bytes, offset: int) -> Tuple[int, int]:
    b = data[offset]; offset += 1
    if b == 0:
        return 0, offset
    sign = (b & 1) == 1
    result = (b >> 1) & 0x3F
    shift = 6
    while b & 0x80:
        if offset >= len(data):
            raise PhotonParseError("EOF in compressed long")
        b = data[offset]; offset += 1
        result |= (b & 0x7F) << shift
        shift += 7
    return (-result if sign else result), offset


def _read_p18_string(data: bytes, offset: int) -> Tuple[str, int]:
    if offset + 2 > len(data):
        raise PhotonParseError("EOF reading P18 string length")
    length = struct.unpack_from('>H', data, offset)[0]
    offset += 2
    if offset + length > len(data):
        raise PhotonParseError("EOF reading P18 string data")
    return data[offset:offset + length].decode('utf-8', errors='replace'), offset + length


def _read_p18_value(data: bytes, offset: int, type_code: int) -> Tuple[Any, int]:
    """Decode a Protocol18-typed value. Returns (value, new_offset)."""

    # Zero-size constants
    if type_code == P18_NULL:        return None,  offset
    if type_code == P18_BOOL_FALSE:  return False, offset
    if type_code == P18_BOOL_TRUE:   return True,  offset
    if type_code in (P18_SHORT_ZERO, P18_INT_ZERO, P18_LONG_ZERO,
                     P18_FLOAT_ZERO, P18_DOUBLE_ZERO, P18_BYTE_ZERO):
        return 0, offset

    if type_code == P18_BOOLEAN:
        if offset >= len(data): raise PhotonParseError("EOF bool")
        return data[offset] != 0, offset + 1

    if type_code == P18_BYTE:
        if offset >= len(data): raise PhotonParseError("EOF byte")
        return data[offset], offset + 1

    if type_code == P18_SHORT:
        if offset + 2 > len(data): raise PhotonParseError("EOF short")
        return struct.unpack_from('<h', data, offset)[0], offset + 2

    if type_code == P18_FLOAT:
        if offset + 4 > len(data): raise PhotonParseError("EOF float")
        return struct.unpack_from('>f', data, offset)[0], offset + 4

    if type_code == P18_DOUBLE:
        if offset + 8 > len(data): raise PhotonParseError("EOF double")
        return struct.unpack_from('>d', data, offset)[0], offset + 8

    if type_code == P18_STRING:
        return _read_p18_string(data, offset)

    if type_code == P18_COMPRESSED_INT:
        return _read_compressed_int(data, offset)

    if type_code == P18_COMPRESSED_LONG:
        return _read_compressed_long(data, offset)

    if type_code == P18_INT1:
        if offset >= len(data): raise PhotonParseError("EOF int1")
        return data[offset], offset + 1

    if type_code == P18_INT1_NEG:
        if offset >= len(data): raise PhotonParseError("EOF int1neg")
        return -data[offset], offset + 1

    if type_code == P18_INT2:
        if offset + 2 > len(data): raise PhotonParseError("EOF int2")
        return struct.unpack_from('>H', data, offset)[0], offset + 2

    if type_code == P18_INT2_NEG:
        if offset + 2 > len(data): raise PhotonParseError("EOF int2neg")
        return -struct.unpack_from('>H', data, offset)[0], offset + 2

    if type_code == P18_LONG1:
        if offset >= len(data): raise PhotonParseError("EOF long1")
        return data[offset], offset + 1

    if type_code == P18_LONG1_NEG:
        if offset >= len(data): raise PhotonParseError("EOF long1neg")
        return -data[offset], offset + 1

    if type_code == P18_LONG2:
        if offset + 2 > len(data): raise PhotonParseError("EOF long2")
        return struct.unpack_from('>H', data, offset)[0], offset + 2

    if type_code == P18_LONG2_NEG:
        if offset + 2 > len(data): raise PhotonParseError("EOF long2neg")
        return -struct.unpack_from('>H', data, offset)[0], offset + 2

    if type_code == P18_BYTE_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF byte array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        if offset + count > len(data): raise PhotonParseError("EOF byte array data")
        return data[offset:offset + count], offset + count

    if type_code == P18_SHORT_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF short array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = []
        for _ in range(count):
            if offset + 2 > len(data): break
            result.append(struct.unpack_from('>h', data, offset)[0]); offset += 2
        return result, offset

    if type_code == P18_FLOAT_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF float array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = []
        for _ in range(count):
            if offset + 4 > len(data): break
            result.append(struct.unpack_from('>f', data, offset)[0]); offset += 4
        return result, offset

    if type_code == P18_DOUBLE_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF double array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = []
        for _ in range(count):
            if offset + 8 > len(data): break
            result.append(struct.unpack_from('>d', data, offset)[0]); offset += 8
        return result, offset

    if type_code == P18_STRING_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF string array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = []
        for _ in range(count):
            s, offset = _read_p18_string(data, offset)
            result.append(s)
        return result, offset

    if type_code == P18_COMPRESSED_INT_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF cint array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = []
        for _ in range(count):
            v, offset = _read_compressed_int(data, offset)
            result.append(v)
        return result, offset

    if type_code == P18_COMPRESSED_LONG_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF clong array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = []
        for _ in range(count):
            v, offset = _read_compressed_long(data, offset)
            result.append(v)
        return result, offset

    if type_code == P18_BOOL_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF bool array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = [bool(b) for b in data[offset:offset + count]]
        return result, offset + count

    if type_code == P18_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        if offset >= len(data): raise PhotonParseError("EOF array elem type")
        elem_type = data[offset]; offset += 1
        result = []
        for _ in range(count):
            v, offset = _read_p18_value(data, offset, elem_type)
            result.append(v)
        return result, offset

    if type_code == P18_OBJECT_ARRAY:
        if offset + 2 > len(data): raise PhotonParseError("EOF obj array len")
        count = struct.unpack_from('>H', data, offset)[0]; offset += 2
        result = []
        for _ in range(count):
            if offset >= len(data): break
            elem_type = data[offset]; offset += 1
            v, offset = _read_p18_value(data, offset, elem_type)
            result.append(v)
        return result, offset

    if type_code == P18_HASHTABLE:
        if offset >= len(data): raise PhotonParseError("EOF hashtable size")
        count = data[offset]; offset += 1
        result = {}
        for _ in range(count):
            if offset + 2 > len(data): break
            kt = data[offset]; offset += 1
            k, offset = _read_p18_value(data, offset, kt)
            if offset >= len(data): break
            vt = data[offset]; offset += 1
            v, offset = _read_p18_value(data, offset, vt)
            result[k] = v
        return result, offset

    if type_code == P18_DICTIONARY:
        if offset + 2 > len(data): raise PhotonParseError("EOF dict types")
        kt = data[offset]; offset += 1
        vt = data[offset]; offset += 1
        if offset >= len(data): raise PhotonParseError("EOF dict count")
        count = data[offset]; offset += 1
        result = {}
        for _ in range(count):
            if offset >= len(data): break
            act_kt = kt if kt != P18_NULL else data[offset]
            if kt == P18_NULL: offset += 1
            k, offset = _read_p18_value(data, offset, act_kt)
            if offset >= len(data): break
            act_vt = vt if vt != P18_NULL else data[offset]
            if vt == P18_NULL: offset += 1
            v, offset = _read_p18_value(data, offset, act_vt)
            result[k] = v
        return result, offset

    if type_code == P18_CUSTOM:
        if offset + 3 > len(data): raise PhotonParseError("EOF custom")
        _custom_type = data[offset]; offset += 1
        length = struct.unpack_from('>H', data, offset)[0]; offset += 2
        val = data[offset:offset + length]
        return val, offset + length

    # CustomTypeSlim (128–228): 1-byte type ID, then length+data
    if P18_CUSTOM_SLIM_MIN <= type_code <= P18_CUSTOM_SLIM_MAX:
        if offset >= len(data): raise PhotonParseError("EOF slim custom")
        length = data[offset]; offset += 1
        val = data[offset:offset + length]
        return val, offset + length

    return f"<type_{type_code}>", offset


def _parse_p18_parameters(data: bytes, offset: int) -> Dict[int, Any]:
    """Parse Protocol18 parameter table: 1-byte count, then key+type+value triples."""
    if offset >= len(data):
        return {}
    count = data[offset]; offset += 1

    params: Dict[int, Any] = {}
    for _ in range(count):
        if offset >= len(data):
            break
        key = data[offset]; offset += 1
        if offset >= len(data):
            break
        type_code = data[offset]; offset += 1
        try:
            val, offset = _read_p18_value(data, offset, type_code)
            params[key] = val
        except (PhotonParseError, IndexError, struct.error):
            break
    return params


# ─── Message parsing ──────────────────────────────────────────────────────────

# Protocol18 : préfixes de type sans magic byte
# 0xF3 est exclu — c'est le magic byte de l'ancien format Photon
_P18_TO_MSG = {
    0xF2: MSG_OP_REQUEST,
    0xF4: MSG_EVENT,            # UpdateFame et autres events Albion
    0xF6: MSG_INTERNAL_OP_REQUEST,
    0xF7: MSG_INTERNAL_OP_RESPONSE,
}


def parse_message(payload: bytes) -> Optional[Dict]:
    """
    Parse a Photon application message. Deux formats coexistent :
    - Ancien Photon : [0xF3 magic][type:2-4][code][params]
    - Protocol18   : [0xF4/0xF2/…][code][params]  (1er octet = type directement)
    """
    if len(payload) < 2:
        return None

    first = payload[0]

    if first in _P18_TO_MSG:
        # Protocol18 : premier octet = type, pas de magic prefix
        msg_type = _P18_TO_MSG[first]
        code = payload[1]
        base = 2
    elif first == 0xF3:
        # Ancien format : 0xF3 = magic byte, type dans le byte suivant
        msg_type = payload[1] & 0x7F
        if msg_type not in (MSG_OP_REQUEST, MSG_OP_RESPONSE, MSG_EVENT,
                            MSG_INTERNAL_OP_REQUEST, MSG_INTERNAL_OP_RESPONSE):
            return None
        if len(payload) < 3:
            return None
        code = payload[2]
        base = 3
    else:
        return None

    if msg_type == MSG_OP_RESPONSE:
        if base + 2 > len(payload):
            return None
        return_code = struct.unpack_from('>h', payload, base)[0]
        p = base + 2
        # Skip optional debug string (type byte + content)
        if p < len(payload):
            debug_type = payload[p]; p += 1
            if debug_type == P18_STRING:
                if p + 2 <= len(payload):
                    slen = struct.unpack_from('>H', payload, p)[0]
                    p += 2 + slen
            elif debug_type == P18_NULL:
                pass  # no bytes follow
        params = _parse_p18_parameters(payload, p)
        return {'type': msg_type, 'code': code, 'return_code': return_code, 'params': params}

    params = _parse_p18_parameters(payload, base)
    return {'type': msg_type, 'code': code, 'params': params}


# ─── Packet parsing ───────────────────────────────────────────────────────────

def parse_photon_packet(data: bytes) -> List[Dict]:
    """
    Parse a full Photon UDP packet.
    Returns list of parsed messages (EventData, OpResponse, etc.).
    """
    results = []

    if len(data) < 12:
        return results

    try:
        cmd_count = data[3]
        offset = 12  # skip Photon header

        for _ in range(cmd_count):
            if offset + 12 > len(data):
                break

            cmd_type = data[offset]
            cmd_len = struct.unpack_from('>I', data, offset + 4)[0]

            if cmd_len < 12 or offset + cmd_len > len(data):
                break

            payload_start = offset + 12
            payload_end = offset + cmd_len
            payload = data[payload_start:payload_end]

            if cmd_type in (CMD_SEND_RELIABLE, CMD_SEND_UNRELIABLE):
                # SendUnreliable prepends a 4-byte unreliable sequence number
                app_data = payload[4:] if cmd_type == CMD_SEND_UNRELIABLE else payload
                msg = parse_message(app_data)
                if msg is not None:
                    results.append(msg)

            offset += cmd_len

    except (struct.error, IndexError):
        pass

    return results
