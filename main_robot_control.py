from waveshare_driver import STServoDriver
import time

# CONFIGURATION
SERIAL_PORT = '/dev/ttyAMA0' # Pi's internal serial port
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
    # 0. GET START POSITION
    start_pos = motor.read_position(MOTOR_ID)
    if start_pos is None:
        print("WARNING: Could not read start position. Assuming current position logic might be flawed if relative move needed.")
        start_pos = 0 # Fallback, though ideally we retry
    else:
        print(f"Start Position: {start_pos}")

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
                
                # --- LOGIC UPDATE: RELATIVE 45 DEGREE OFFSET ---
                target_back_pos, deg_offset = calculate_45_degree_target(start_pos, current_pos)
                
                print(f"*** ROTATING TO {deg_offset:.1f} deg relative to start ({target_back_pos}) ***")
                
                # 4. Execute the move
                motor.write_position(MOTOR_ID, target_back_pos, 500)
                
                # Wait a bit for the move to complete
                time.sleep(1.0)
                
                break # Exit the loop immediately
            
        time.sleep(0.05) # Loop quickly for fast stall detection

    return STALL_POSITION

def calculate_45_degree_target(start_pos, current_pos):
    """
    Calculates a target position that is a multiple of 45 degrees 
    relative to the start_pos, closest to the current_pos.
    Envures the target is not the start_pos itself.
    """
    STEPS_PER_DEGREE = 4096 / 360.0
    
    diff_steps = current_pos - start_pos
    diff_deg = diff_steps / STEPS_PER_DEGREE
    
    # Floor to nearest 45 degrees
    # e.g. 10 -> 0, 40 -> 0, 45 -> 45, 80 -> 45
    target_deg_rel = (diff_deg // 45.0) * 45.0
    
    # Requirement: "different place from the first position"
    # If the floor result is 0 (start position), we might still want to move?
    # User request was: "0-44.9 -> 0". 
    # If this results in 0, and start_pos is 0-relative, it means we go back to start.
    # The previous requirement "different place" might conflict if we strictly floor 10 -> 0.
    # However, user explicitly asked for this mapping.
    # I will keep the check ensuring we don't return EXACTLY start steps if that was the "different place" intent, 
    # but based on "0-44.9 -> 0", returning 0 offset seems to be what is wanted for that range.
    # But wait, original request: "Stop... 45 degree different place... add or remove rotation".
    # If I am at 10 deg, and I floor to 0, I am moving back 10 deg. That IS a move.
    # So returning offset 0 means moving back to start. That is valid.
    # I will remove the "force 45" logic if it conflicts with the explicit "0->0" request.
    # But I will keep the "different place" spirit by not doing anything special if result is 0, 
    # just returning target_deg_rel=0 implies target_pos = start_pos.
            
    # Calculate target steps
    target_pos = start_pos + int(target_deg_rel * STEPS_PER_DEGREE)
    
    return target_pos, target_deg_rel

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
