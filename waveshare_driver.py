"""
st_servo_driver.py
Robust driver for ST3215/STS-like servos using the 0xFF 0xFF protocol.

Usage:
    from st_servo_driver import STServoDriver
    with STServoDriver("/dev/ttyAMA0", 1000000) as drv:
        drv.ping(1)
        drv.write_position(1, position=2048, speed=100)
        pos = drv.read_position(1)
        load = drv.read_load(1)
"""

import serial
import struct
import time
import threading
import logging
from typing import Optional, Union, Tuple

# Instruction opcodes
READ_INST = 0x02
WRITE_INST = 0x03
PING_INST = 0x01

# Memory addresses
ADDR_MODE = 0x21          # 0: Position Mode, 1: Wheel Mode
ADDR_POS_TARGET = 0x2A    # Target Position (4 bytes: Pos + Time + Speed)
ADDR_SPEED_RUN = 0x2E     # Speed in Wheel Mode (2 bytes)
ADDR_POSITION = 0x38      # Current Position (2 bytes)
ADDR_LOAD = 0x3C          # Current Load (2 bytes)

# Packet header bytes
HEADER = b'\xFF\xFF'

class STServoError(Exception):
    """Base exception for servo driver errors."""
    pass

class PacketChecksumError(STServoError):
    pass

class PacketTimeoutError(STServoError):
    pass

class STServoDriver:
    def __init__(
        self,
        port: str,
        baudrate: int = 1000000,
        timeout: float = 0.2,
        retries: int = 3,
        inter_byte_delay: float = 0.00005,
        load_sign_bit: int = 10,
        logger: Optional[logging.Logger] = None,
    ):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.inter_byte_delay = inter_byte_delay
        self.lock = threading.RLock()
        self.load_sign_bit = load_sign_bit
        self.logger = logger or logging.getLogger(__name__)

    # ---------- Utility / Checksums ----------
    @staticmethod
    def _format_packet(servo_id: int, instruction: int, params: Optional[list]) -> bytes:
        params = params or []
        length_field = len(params) + 2
        header = bytearray([0xFF, 0xFF, servo_id & 0xFF, length_field & 0xFF, instruction & 0xFF])
        header.extend([p & 0xFF for p in params])
        checksum = (~sum(header[2:])) & 0xFF
        header.append(checksum)
        return bytes(header)

    def _verify_response_checksum(self, packet: bytes) -> bool:
        if len(packet) < 6:
            return False
        rest_without_header = packet[2:-1]
        calc = (~(sum(rest_without_header) & 0xFF)) & 0xFF
        return calc == packet[-1]

    # ---------- Low-level IO ----------
    def close(self):
        with self.lock:
            if self.ser and self.ser.is_open:
                self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _send_packet_raw(self, servo_id: int, instruction: int, params: Optional[list] = None):
        packet = self._format_packet(servo_id, instruction, params)
        with self.lock:
            self.ser.reset_input_buffer()
            self.ser.write(packet)
            self.ser.flush()
            if self.inter_byte_delay:
                time.sleep(self.inter_byte_delay)
        return packet

    def _read_response_raw(self, expected_id: int, expected_data_len: Optional[int] = None) -> bytes:
        start = time.time()
        buf = bytearray()
        while len(buf) < 2:
            if (time.time() - start) > self.timeout:
                raise PacketTimeoutError("Timeout waiting for header")
            b = self.ser.read(1)
            if b: buf.extend(b)
            if len(buf) > 2: buf = buf[-2:]

        if bytes(buf[:2]) != HEADER:
            raise PacketTimeoutError("Invalid Header")

        id_and_len = self.ser.read(2)
        if len(id_and_len) < 2:
            raise PacketTimeoutError("Timeout reading ID+LEN")
        
        servo_id = id_and_len[0]
        length = id_and_len[1]
        rest = self.ser.read(length)
        packet = bytes(buf) + id_and_len + rest
        
        if not self._verify_response_checksum(packet):
            raise PacketChecksumError("Checksum mismatch")
        return packet
    
    def set_mode(self, servo_id: int, mode: int):
        """
        Sets Mode. 0 for Position Mode, 1 for Wheel (Continuous) Mode.
        """
        # Address 0x21 is a 1-byte register
        params = [ADDR_MODE, mode & 0xFF]
        self._send_packet_raw(servo_id, WRITE_INST, params)
        time.sleep(0.05) # Delay to allow mode switch
        return True

    def write_speed(self, servo_id: int, speed: int):
        """
        Sets rotation speed for Wheel Mode. 
        Supports signed values (negative for reverse).
        """
        # Convert to 16-bit signed (Little Endian)
        if speed < 0:
            speed = (abs(speed) & 0x7FFF) | 0x8000
        else:
            speed = speed & 0x7FFF

        params = [ADDR_SPEED_RUN, speed & 0xFF, (speed >> 8) & 0xFF]
        self._send_packet_raw(servo_id, WRITE_INST, params)
        return True

    def write_position(self, servo_id: int, position: int, speed: int = 0, time_ms: int = 0):
        pos_bytes = struct.pack('<H', position & 0xFFFF)
        time_bytes = struct.pack('<H', time_ms & 0xFFFF)
        spd_bytes = struct.pack('<H', speed & 0xFFFF)
        
        params = [ADDR_POS_TARGET] + list(pos_bytes) + list(time_bytes) + list(spd_bytes)
        self._send_packet_raw(servo_id, WRITE_INST, params)
        return True

    def read_position(self, servo_id: int) -> Optional[int]:
        raw = self._read_data(servo_id, ADDR_POSITION, 2)
        return struct.unpack('<H', raw)[0] if raw else None

    def read_load(self, servo_id: int) -> Optional[int]:
        raw = self._read_data(servo_id, ADDR_LOAD, 2)
        if not raw: return None
        raw_val = struct.unpack('<H', raw)[0]
        magnitude = raw_val & ((1 << self.load_sign_bit) - 1)
        direction = -1 if (raw_val & (1 << self.load_sign_bit)) else 1
        return magnitude * direction

    def _read_data(self, servo_id: int, address: int, data_len: int) -> Optional[bytes]:
        params = [address & 0xFF, data_len & 0xFF]
        try:
            self._send_packet_raw(servo_id, READ_INST, params)
            pkt = self._read_response_raw(servo_id, data_len)
            return pkt[5:5+data_len]
        except:
            return None

    def ping(self, servo_id: int) -> bool:
        try:
            self._send_packet_raw(servo_id, PING_INST)
            self._read_response_raw(servo_id, 0)
            return True
        except:
            return False
