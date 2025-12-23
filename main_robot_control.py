import time
import logging
from waveshare_driver import STServoDriver

# --- CONFIGURATION ---
SERIAL_PORT = '/dev/ttyAMA0'  # Change to COM port if on Windows
MOTOR_ID = 1
MOVE_SPEED = 1000             # Rotation speed in Wheel Mode
STALL_THRESHOLD = 600         # Load value to trigger stall recording
RUN_DURATION = 10             # Seconds to run continuously
STEPS_PER_45_DEG = 512        # 4096 / 8 = 512

def calculate_45_degree_snap(start_pos, current_pos):
    """
    Calculates the closest previous multiple of 45 degrees 
    relative to where the motor first started.
    """
    diff_steps = current_pos - start_pos
    # Use floor division to find how many full 45-degree chunks were completed
    multiples = diff_steps // STEPS_PER_45_DEG
    target_rel_steps = multiples * STEPS_PER_45_DEG
    
    target_absolute_pos = start_pos + target_rel_steps
    return int(target_absolute_pos), multiples * 45.0

def main():
    # Setup logging to see what's happening under the hood
    logging.basicConfig(level=logging.INFO)
    
    try:
        # 1. Initialize Driver
        drv = STServoDriver(SERIAL_PORT, 1000000)
        print(f"Connected to {SERIAL_PORT}. Pinging Motor {MOTOR_ID}...")
        
        if not drv.ping(MOTOR_ID):
            print(f"Failed to ping Motor {MOTOR_ID}. Check wiring/ID.")
            return

        # 2. Reset to Initial Position (Position Mode)
        # We start at 1024 to give the motor room to rotate
        drv.set_mode(MOTOR_ID, 0) # 0 = Position Mode
        print("Resetting to starting position (1024)...")
        drv.write_position(MOTOR_ID, 1024, speed=500)
        time.sleep(2.0)
        
        start_pos = drv.read_position(MOTOR_ID)
        print(f"Initial Position Captured: {start_pos}")

        # 3. Start Continuous Rotation (Wheel Mode)
        # This prevents the motor from stopping at "3498"
        print(f"Switching to Wheel Mode. Running for {RUN_DURATION}s...")
        drv.set_mode(MOTOR_ID, 1) # 1 = Wheel Mode
        drv.write_speed(MOTOR_ID, MOVE_SPEED)
        
        start_time = time.time()
        stall_detected_pos = None
        
        # 4. Monitor Loop
        while time.time() - start_time < RUN_DURATION:
            curr_pos = drv.read_position(MOTOR_ID)
            curr_load = drv.read_load(MOTOR_ID)
            elapsed = time.time() - start_time
            
            if curr_pos is not None and curr_load is not None:
                print(f"[{elapsed:.1f}s] Pos: {curr_pos} | Load: {curr_load}")
                
                # If stall detected, record the position but keep running
                if abs(curr_load) > STALL_THRESHOLD and stall_detected_pos is None:
                    stall_detected_pos = curr_pos
                    print(f"!!! STALL DETECTED at Pos {stall_detected_pos} !!!")
            
            time.sleep(0.1)

        # 5. Stop and Snap back
        print("Time up! Stopping motor...")
        drv.write_speed(MOTOR_ID, 0)
        time.sleep(0.5)
        
        # Switch back to Position Mode to allow precise snapping
        drv.set_mode(MOTOR_ID, 0)
        
        # Determine which position to use for the math
        # If we stalled, snap to the 45° before the stall. 
        # Otherwise, snap to the 45° before the final stop.
        final_reference = stall_detected_pos if stall_detected_pos is not None else drv.read_position(MOTOR_ID)
        
        snap_target, degrees = calculate_45_degree_snap(start_pos, final_reference)
        
        print(f"Final Action: Snapping to {snap_target} ({degrees}° from start)")
        drv.write_position(MOTOR_ID, snap_target, speed=600)
        
        # Wait for movement to finish before closing
        time.sleep(2.0)
        print("Sequence complete.")

    except KeyboardInterrupt:
        print("\nManual stop triggered.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'drv' in locals():
            # Emergency stop: try to set speed to 0 before closing
            try:
                drv.write_speed(MOTOR_ID, 0)
            except:
                pass
            drv.close()
            print("Driver closed.")

if __name__ == "__main__":
    main()
