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

# Default memory addresses (as in user's original file)
ADDR_POSITION = 0x38
ADDR_LOAD = 0x3C
ADDR_POS_TARGET = 0x2A

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
        """
        Args:
            port: Serial port path (e.g. "/dev/ttyAMA0").
            baudrate: Baud rate (default 1,000,000).
            timeout: Serial timeout (seconds) for read() operations.
            retries: How many attempts to retry a read after failure.
            inter_byte_delay: small sleep after sending packet to allow servo to respond.
            load_sign_bit: bit index used for load direction (default bit 10).
            logger: optional logger (defaults to module logger).
        """
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.inter_byte_delay = inter_byte_delay
        self.lock = threading.RLock()
        self.load_sign_bit = load_sign_bit
        self.logger = logger or logging.getLogger(__name__)

    # ---------- Utility / Checksums ----------
    @staticmethod
    def _calc_checksum_outgoing(parts: Union[bytes, bytearray, list]) -> int:
        """
        Checksum for outgoing packets:
            checksum = (~sum(bytes_from_id_onwards)) & 0xFF
        parts should contain bytes from ID onwards (ID, LENGTH, INSTRUCTION, PARAMS...)
        """
        s = sum(parts) & 0xFF
        return (~s) & 0xFF

    @staticmethod
    def _format_packet(servo_id: int, instruction: int, params: Optional[list]) -> bytes:
        params = params or []
        length = 1 + len(params)  # instruction + params ; LENGTH field = number of bytes after LENGTH itself (ERROR in responses / INSTRUCTION + PARAMS here)
        # For outgoing packet LENGTH is len(params) + 2 per your original code: ID,LEN,INS,PARAMS,CHECKSUM
        # With AX-like protocol LENGTH = number of bytes after LENGTH (INSTRUCTION + PARAMS + CHECKSUM)
        # The historical approach in your earlier code used length = len(params)+2 -> that's (INSTRUCTION + PARAMS + CHECKSUM)
        # We'll follow the conventional AX style: LENGTH = len(params) + 2 (instruction + params + checksum)
        length_field = len(params) + 2
        header = bytearray([0xFF, 0xFF, servo_id & 0xFF, length_field & 0xFF, instruction & 0xFF])
        header.extend([p & 0xFF for p in params])
        # checksum computed from ID onwards (ID, LENGTH, INSTRUCTION, PARAMS...)
        checksum = (~sum(header[2:])) & 0xFF
        header.append(checksum)
        return bytes(header)

    def _verify_response_checksum(self, packet: bytes) -> bool:
        """
        packet is the full response including header bytes (0xFF,0xFF,...,checksum)
        Response format: 0xFF 0xFF ID LENGTH ERROR DATA... CHECKSUM
        To verify:
            checksum == (~(ID + LENGTH + ERROR + DATA...)) & 0xFF
        """
        if len(packet) < 6:
            return False
        # strip first two header bytes
        id_byte = packet[2]
        length_byte = packet[3]
        # The payload we sum is ID + LENGTH + rest_without_checksum
        rest_without_header = packet[2:-1]  # ID, LENGTH, ERROR, DATA...
        calc = (~(sum(rest_without_header) & 0xFF)) & 0xFF
        recv_checksum = packet[-1]
        return calc == recv_checksum

    # ---------- Low-level IO ----------
    def close(self):
        with self.lock:
            if self.ser and self.ser.is_open:
                self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.close()
        except Exception:
            pass

    def _send_packet_raw(self, servo_id: int, instruction: int, params: Optional[list] = None):
        """
        Builds and sends a packet. Does not wait for or parse response.
        """
        packet = self._format_packet(servo_id, instruction, params)
        with self.lock:
            # clear input buffer to avoid stale bytes
            try:
                self.ser.reset_input_buffer()
            except Exception:
                # some pyserial versions use flushInput
                try:
                    self.ser.flushInput()
                except Exception:
                    pass
            self.ser.write(packet)
            self.ser.flush()
            if self.inter_byte_delay:
                time.sleep(self.inter_byte_delay)
        self.logger.debug("Sent packet: %s", packet.hex())
        return packet

    def _read_response_raw(self, expected_id: int, expected_data_len: Optional[int] = None, timeout: Optional[float] = None) -> bytes:
        """
        Read and return the raw response packet bytes or raise PacketTimeoutError.
        If expected_data_len is given, we expect data_len bytes of DATA in the packet (not counting header, id, len, error, checksum).
        """
        timeout = self.timeout if timeout is None else timeout
        start = time.time()
        buf = bytearray()

        # read header first (2 bytes 0xFF 0xFF)
        while len(buf) < 2:
            if (time.time() - start) > timeout:
                raise PacketTimeoutError("Timeout waiting for header")
            b = self.ser.read(1)
            if not b:
                continue
            buf.extend(b)

            # keep only last two bytes if more are read
            if len(buf) > 2:
                buf = buf[-2:]

        if bytes(buf[:2]) != HEADER:
            # try to resync by reading until correct header is seen
            self.logger.debug("Header mismatch: %s", buf.hex())
            # attempt to find the header in stream
            # read up to timeout to find header
            found = False
            # we'll fetch up to timeout to find header sequence
            start_find = time.time()
            tail = bytearray()
            while (time.time() - start_find) <= timeout:
                b = self.ser.read(1)
                if not b:
                    continue
                tail.extend(b)
                if len(tail) > 2:
                    tail = tail[-2:]
                if bytes(tail) == HEADER:
                    found = True
                    break
            if not found:
                raise PacketTimeoutError("Timeout finding packet header")
            # header found; start with header
            buf = bytearray(HEADER)

        # read ID and LENGTH (2 bytes)
        id_and_len = self.ser.read(2)
        if len(id_and_len) < 2:
            raise PacketTimeoutError("Timeout reading ID+LENGTH")
        buf.extend(id_and_len)
        servo_id = id_and_len[0]
        length = id_and_len[1]  # LENGTH = error(1) + data_len + checksum(1)
        # now read 'length' bytes (ERROR + DATA... + CHECKSUM)
        rest = self.ser.read(length)
        if len(rest) < length:
            raise PacketTimeoutError("Timeout reading packet payload")
        buf.extend(rest)

        packet = bytes(buf)
        self.logger.debug("Received raw packet: %s", packet.hex())

        # Basic validation: ID should match
        if servo_id != (expected_id & 0xFF):
            # some systems allow broadcast id 0xFE; still validate user expectation
            self.logger.warning("Received packet for ID %d but expected %d", servo_id, expected_id)
            # continue to checksum validation, but caller should be aware
        # verify checksum
        if not self._verify_response_checksum(packet):
            raise PacketChecksumError("Response checksum mismatch: %s" % packet.hex())

        # optional: check that length matches expected_data_len
        if expected_data_len is not None:
            # length includes: ERROR + DATA + CHECKSUM
            data_len_in_packet = length - 2  # subtract ERROR(1) and CHECKSUM(1)
            if data_len_in_packet != expected_data_len:
                # not necessarily fatal; warn
                self.logger.warning("Expected data length %s but packet contains %s", expected_data_len, data_len_in_packet)

        return packet

    # ---------- High-level command helpers ----------
    def ping(self, servo_id: int) -> bool:
        """Send ping and return True if servo responded (no exception)."""
        for attempt in range(self.retries):
            try:
                self._send_packet_raw(servo_id, PING_INST, [])
                pkt = self._read_response_raw(expected_id=servo_id, expected_data_len=0)
                # A successful response with no data has error byte present (we ignore it for now)
                return True
            except (PacketTimeoutError, PacketChecksumError) as e:
                self.logger.debug("Ping attempt %d failed: %s", attempt + 1, e)
                continue
        return False

    def _read_data(self, servo_id: int, address: int, data_len: int) -> Optional[bytes]:
        """
        Generic read of memory from servo. Returns raw data bytes (length = data_len) or None.
        Uses retries and returns None on repeated failure.
        """
        params = [address & 0xFF, data_len & 0xFF]
        for attempt in range(self.retries):
            try:
                with self.lock:
                    self._send_packet_raw(servo_id, READ_INST, params)
                    # response data_len means packet LENGTH field should be error(1)+data_len+checksum(1)
                    pkt = self._read_response_raw(expected_id=servo_id, expected_data_len=data_len)
                # parse pkt: 0xFF 0xFF ID LENGTH ERROR DATA... CHECKSUM
                # Data begins at offset 5 (0-based): [0,1]=header, 2=ID,3=LENGTH,4=ERROR,5...=DATA
                data_start = 5
                data_end = data_start + data_len
                data_bytes = pkt[data_start:data_end]
                if len(data_bytes) != data_len:
                    raise STServoError(f"Unexpected data length: got {len(data_bytes)} expected {data_len}")
                return data_bytes
            except (PacketTimeoutError, PacketChecksumError, STServoError) as e:
                self.logger.debug("Read data attempt %d failed: %s", attempt + 1, e)
                time.sleep(0.005 * (attempt + 1))
                continue
        return None

    def read_position(self, servo_id: int) -> Optional[int]:
        """
        Reads the current angular position (2 bytes, little-endian).
        Returns integer or None on failure.
        """
        raw = self._read_data(servo_id, ADDR_POSITION, 2)
        if raw is None:
            return None
        # little-endian unsigned short
        try:
            (val,) = struct.unpack('<H', raw)
            return int(val)
        except struct.error:
            self.logger.exception("Failed to unpack position")
            return None

    def read_load(self, servo_id: int) -> Optional[int]:
        """
        Reads 2-byte load register and returns signed magnitude depending on sign bit.
        Default sign bit = 10 (bits 0-9 magnitude, bit 10 direction).
        If you have a servo that uses two's complement or a different bit, set load_sign_bit accordingly.
        """
        raw = self._read_data(servo_id, ADDR_LOAD, 2)
        if raw is None:
            return None
        try:
            (raw_val,) = struct.unpack('<H', raw)
        except struct.error:
            self.logger.exception("Failed to unpack load")
            return None

        sign_bit = self.load_sign_bit
        magnitude_mask = (1 << sign_bit) - 1
        direction_mask = 1 << sign_bit

        magnitude = raw_val & magnitude_mask
        direction = -1 if (raw_val & direction_mask) else 1
        return magnitude * direction

    def write_position(self, servo_id: int, position: int, speed: int = 0, time_ms: int = 0):
        """
        Writes target position (2 bytes) and speed (2 bytes) to ADDR_POS_TARGET.
        time_ms: optional move time in milliseconds. If 0, uses servo's default/time-as-zero semantics.
        Speed and position must be within servo-supported ranges (caller responsibility).
        """
        # clamp to 16-bit
        position = int(position) & 0xFFFF
        speed = int(speed) & 0xFFFF
        time_val = int(time_ms) & 0xFFFF

        pos_L = position & 0xFF
        pos_H = (position >> 8) & 0xFF
        time_L = time_val & 0xFF
        time_H = (time_val >> 8) & 0xFF
        spd_L = speed & 0xFF
        spd_H = (speed >> 8) & 0xFF

        params = [ADDR_POS_TARGET, pos_L, pos_H, time_L, time_H, spd_L, spd_H]

        for attempt in range(self.retries):
            try:
                with self.lock:
                    self._send_packet_raw(servo_id, WRITE_INST, params)
                    # optionally read a status packet (most servos reply to write). We'll attempt to read but tolerate timeouts.
                    try:
                        pkt = self._read_response_raw(expected_id=servo_id, expected_data_len=0)
                    except PacketTimeoutError:
                        # Some setups (broadcast writes) don't return a response; we consider write successful if serial write succeeded.
                        self.logger.debug("No status packet after write (timeout). Accepting as success for attempt %d", attempt + 1)
                return True
            except PacketChecksumError as e:
                self.logger.debug("Write attempt %d checksum error: %s", attempt + 1, e)
                continue
            except PacketTimeoutError as e:
                self.logger.debug("Write attempt %d timeout: %s", attempt + 1, e)
                continue
        raise STServoError("write_position failed after retries")

    # Convenience: read multiple registers and return as tuple
    def read_position_and_load(self, servo_id: int) -> Tuple[Optional[int], Optional[int]]:
        pos = self.read_position(servo_id)
        load = self.read_load(servo_id)
        return pos, load


# Example / test usage (only run when module executed directly)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    drv = STServoDriver("/dev/ttyAMA0", 1000000, timeout=0.25, retries=3)
    try:
        servo_id = 1
        print("Ping:", drv.ping(servo_id))
        print("Write pos -> 2048 speed 100")
        drv.write_position(servo_id, 2048, speed=100, time_ms=0)
        time.sleep(0.1)
        pos = drv.read_position(servo_id)
        load = drv.read_load(servo_id)
        print("Position:", pos)
        print("Load:", load)
    finally:
        drv.close()
