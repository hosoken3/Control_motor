@ waveshare_driver.py

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

    を下の通りに作って。
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

        ---

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

も同様に。