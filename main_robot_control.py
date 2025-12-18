from waveshare_driver import STServoDriver
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
                
                
                # --- LOGIC UPDATE BASED ON DIAGRAM ---
                # "Rotate back to the nearest 45 degrees"
                # We assume 4096 steps = 360 degrees
                STEPS_PER_DEGREE = 4096 / 360.0
                
                # 1. Calculate current angle in degrees
                current_deg = current_pos / STEPS_PER_DEGREE
                
                # 2. Find the "previous" 45-degree increment (CCW direction / rotate back)
                # Using floor division to get the nearest lower multiple of 45
                target_deg = (current_deg // 45) * 45
                
                # 3. Convert back to steps
                target_back_pos = int(target_deg * STEPS_PER_DEGREE)
                
                print(f"*** ROTATING BACK TO {target_deg:.1f} degrees ({target_back_pos}) ***")
                
                # 4. Execute the move (Rotate back means we move to a smaller position value if we were increasing)
                # Note: We use a slightly lower speed for the back-off to be safe
                motor.write_position(MOTOR_ID, target_back_pos, 500)
                
                # Wait a bit for the move to complete (simple open-loop wait for demo)
                time.sleep(1.0)
                
                break # Exit the loop immediately
            
        time.sleep(0.05) # Loop quickly for fast stall detection

    return STALL_POSITION

import platform

if __name__ == "__main__":
    motor = None
    try:
        # Detect available ports
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        print(f"DEBUG: Found ports: {ports}")
        
        selected_port = None
        
        # Heuristic for Windows: Try COM4, then anything not COM1/COM2, then whatever is left
        if platform.system() == "Windows":
            if 'COM4' in ports:
                selected_port = 'COM4'
            elif 'COM3' in ports:
                 # Check if we should try COM3
                 selected_port = 'COM3'
            
            # If we haven't picked one, just take the last strictly numeric COM port (often USB)
            if not selected_port and ports:
                selected_port = ports[-1]
                
        else:
            selected_port = '/dev/ttyS0' # Default for Pi
        
        if not selected_port:
             print("No suitable serial port found! Please connect the device.")
             exit(1)
             
        print(f"Attempting to connect to: {selected_port}")
        SERIAL_PORT = selected_port

        motor = STServoDriver(SERIAL_PORT, BAUD_RATE)
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
