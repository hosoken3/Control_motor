import serial
import struct
import time

# PROTOCOL CONSTANTS for ST3215/STS Servos
BAUD_RATE = 1000000      # Default speed
READ_INST = 0x02         # Instruction to read data
WRITE_INST = 0x03        # Instruction to write data

# Memory Map Addresses (Crucial for feedback)
ADDR_LOAD = 0x3C         # Current Load (Torque Feedback)
ADDR_POSITION = 0x38     # Current Position (Positional Feedback)
ADDR_POS_TARGET = 0x2A   # Target Position

class STServo:
    def __init__(self, port, baud):
        # Configuration for Raspberry Pi's GPIO serial port
        self.ser = serial.Serial(port, baud, timeout=0.1)
        
    def close(self):
        self.ser.close()

    def _calc_checksum(self, data):
        # Checksum is the bitwise NOT of the sum of all bytes starting from ID, masked by 0xFF
        return (~sum(data)) & 0xFF

    def _send_packet(self, servo_id, instruction, params):
        length = len(params) + 2
        packet = [0xFF, 0xFF, servo_id, length, instruction] + params
        checksum = self._calc_checksum(packet[2:])
        packet.append(checksum)
        self.ser.write(bytearray(packet))
    
    def _read_data(self, servo_id, address, data_len):
        """Generic function to request and read data from a memory address."""
        # Params: [Start Address, Length to Read]
        params = [address, data_len] 
        self._send_packet(servo_id, READ_INST, params)
        
        # Expected response length: Header(2) + ID(1) + Len(1) + Error(1) + Data(data_len) + Checksum(1)
        response_len = 6 + data_len
        response = self.ser.read(response_len)
        
        if len(response) == response_len and response[0] == 0xFF:
            # Data is the payload after the error byte (index 5 onwards)
            data_bytes = response[5 : 5 + data_len]
            
            # Use struct.unpack to convert 2 bytes (Little Endian 'H') to a 16-bit integer
            # If reading only 1 byte, adjust this. Position/Load are 2 bytes.
            if data_len == 2:
                # '<H' means Little-Endian Unsigned Short (2 bytes)
                return struct.unpack('<H', data_bytes)[0]
        return None

    def write_position(self, servo_id, position, speed):
        """Sends a command to move the servo."""
        # Write position (2 bytes) and speed (2 bytes) starting at ADDR_POS_TARGET (0x2A)
        pos_L = position & 0xFF
        pos_H = (position >> 8) & 0xFF
        spd_L = speed & 0xFF
        spd_H = (speed >> 8) & 0xFF
        
        # Params: [Address, Pos_L, Pos_H, Time_L(0), Time_H(0), Spd_L, Spd_H]
        params = [ADDR_POS_TARGET, pos_L, pos_H, 0x00, 0x00, spd_L, spd_H] 
        self._send_packet(servo_id, WRITE_INST, params)

    def read_position(self, servo_id):
        """Reads the servo's current angular position (0-4095)."""
        # Read 2 bytes starting at ADDR_POSITION (0x38)
        raw_position = self._read_data(servo_id, ADDR_POSITION, 2)
        return raw_position

    def read_load(self, servo_id):
        """Reads the servo's current load/torque magnitude."""
        # Read 2 bytes starting at ADDR_LOAD (0x3C)
        raw_load = self._read_data(servo_id, ADDR_LOAD, 2)
        
        if raw_load is not None:
            # Load is a signed value. Bit 10 determines direction.
            magnitude = raw_load & 0x03FF 
            direction = -1 if (raw_load & 0x0400) else 1
            return magnitude * direction
        return None
