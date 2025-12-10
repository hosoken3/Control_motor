from waveshare_driver import STServo
import time

# CONFIGURATION
SERIAL_PORT = '/dev/ttyS0' # Pi's internal serial port
MOTOR_ID = 1               # Servo ID
STALL_THRESHOLD = 600      # Arbitrary value: Load magnitude over this indicates a stall
TARGET_POSITION = 3500     # The position we command the motor to move towards
MOVE_SPEED = 1000          # Speed setting (affects how quickly the load builds)
BAUD_RATE = 1000000        # Default baud rate

def execute_move_and_monitor(motor, target_pos, speed):
    """
    Commands the motor to move and continuously monitors load and position.
    Returns the stall position if detected, otherwise None.
    """
    print(f"--- Starting Move to Position {target_pos} ---")
    motor.write_position(MOTOR_ID, target_pos, speed)
    
    start_time = time.time()
    STALL_POSITION = None
    
    # Run the loop for a maximum of 10 seconds or until a stall
    while time.time() - start_time < 10: 
        
        # 1. READ FEEDBACK
        current_load = motor.read_load(MOTOR_ID)
        current_pos = motor.read_position(MOTOR_ID)

        if current_load is not None and current_pos is not None:
            # Print status update
            print(f"Time: {time.time() - start_time:.1f}s | Pos: {current_pos:04d} | Load: {current_load:04d}")
            
            # 2. CHECK FOR STALL (Torque Feedback)
            if abs(current_load) > STALL_THRESHOLD:
                STALL_POSITION = current_pos
                print("\n" + "="*40)
                print(f"*** ⚠️ STALL DETECTED! ***")
                print(f"*** FINAL ROTATIONAL POSITION: {STALL_POSITION} ***")
                print("="*40 + "\n")
                
                # OPTIONAL: Command the motor to stop moving to prevent damage
                motor.write_position(MOTOR_ID, current_pos, 0) 
                
                break # Exit the loop immediately
            
        time.sleep(0.05) # Loop quickly for fast stall detection

    return STALL_POSITION

import platform

if __name__ == "__main__":
    motor = None
    try:
        # Auto-detect defaults for easier debugging based on OS
        if platform.system() == "Windows":
            print("Detected Windows OS. Attempting to use default COM port 'COM3'.")
            print("If this fails, please change SERIAL_PORT in the code to your actual port (e.g., COM4, COM5).")
            SERIAL_PORT = 'COM3' 
        else:
            SERIAL_PORT = '/dev/ttyS0' # Default for Pi

        motor = STServo(SERIAL_PORT, BAUD_RATE)
        print("Motor Driver initialized successfully.")
        
        # Set to an initial safe position before starting the test
        motor.write_position(MOTOR_ID, 1024, 500)
        time.sleep(2) 
        
        # Execute the main test routine
        final_position = execute_move_and_monitor(motor, TARGET_POSITION, MOVE_SPEED)

        if not final_position:
             print("Move finished successfully without a stall.")
             
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        print("Check Pi Serial Config (sudo raspi-config) and wiring (TX/RX/12V).")
        
    finally:
        if motor:
            motor.close()
            print("Script finished. Serial port closed.")
        else:
            print("Script finished. Motor driver was not initialized.")
