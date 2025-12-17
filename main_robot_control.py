import platform
import time
import threading
import tkinter as tk
from tkinter import ttk
import serial.tools.list_ports
from waveshare_driver import STServoDriver as STServo

# CONFIGURATION
SERIAL_PORT = '/dev/ttyS0' # Pi's internal serial port
MOTOR_ID = 1               # Servo ID
STALL_THRESHOLD = 600      # Arbitrary value: Load magnitude over this indicates a stall
TARGET_POSITION = 3500     # The position we command the motor to move towards
MOVE_SPEED = 1000          # Speed setting (affects how quickly the load builds)
BAUD_RATE = 1000000        # Default baud rate

class RobotController:
    """
    Handles motor control logic in a separate thread.
    """
    def __init__(self, port, baud_rate, log_callback=None):
        self.port = port
        self.baud_rate = baud_rate
        self.motor = None
        self.running = False
        self.thread = None
        self.log_callback = log_callback
        
        # Shared state for GUI
        self.status_message = "待機中"
        self.current_pos = 0
        self.current_load = 0
        self.start_time = 0
        self.elapsed_time = 0.0

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)
        print(message)

    def connect(self):
        try:
            self.motor = STServo(self.port, self.baud_rate)
            self.status_message = "接続完了"
            self.log("コントローラーに接続しました。")
            # Move to safe start pos
            self.motor.write_position(MOTOR_ID, 1024, 500)
            time.sleep(1)
            return True
        except Exception as e:
            self.status_message = f"エラー: {e}"
            self.log(f"接続エラー: {e}")
            return False

    def start_move(self):
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_logic, daemon=True)
        self.thread.start()

    def stop_move(self):
        self.running = False
        self.status_message = "停止中..."
        self.log("停止コマンドを受信しました。")

    def _run_logic(self):
        """
        The main control loop (formerly execute_move_and_monitor).
        """
        if not self.motor:
            self.status_message = "モーター未接続"
            self.running = False
            return

        self.status_message = "動作中..."
        self.log(f"--- 移動開始: 目標位置 {TARGET_POSITION} ---")
        self.motor.write_position(MOTOR_ID, TARGET_POSITION, MOVE_SPEED)
        
        self.start_time = time.time()
        stall_detected = False
        
        while self.running:
            # Check timeout (e.g. 10 seconds max run)
            now = time.time()
            self.elapsed_time = now - self.start_time
            if self.elapsed_time > 10:
                self.status_message = "タイムアウト (10秒)"
                self.log("タイムアウトしました (10秒)。")
                break
            
            # 1. READ FEEDBACK
            current_load = self.motor.read_load(MOTOR_ID)
            current_pos = self.motor.read_position(MOTOR_ID)
            
            if current_load is not None and current_pos is not None:
                self.current_load = current_load
                self.current_pos = current_pos
                
                # 2. CHECK FOR STALL
                if abs(current_load) > STALL_THRESHOLD:
                    self.status_message = "衝突検知 (Stall)!"
                    stall_position = current_pos
                    stall_detected = True
                    
                    self.log(f"*** ⚠️ 衝突を検知しました (位置: {stall_position}, 負荷: {current_load}) ***")
                    
                    # --- LOGIC UPDATE: Back off 45 degrees ---
                    # 4096 steps = 360 degrees
                    STEPS_PER_DEGREE = 4096 / 360.0
                    current_deg = current_pos / STEPS_PER_DEGREE
                    target_deg = (current_deg // 45) * 45
                    target_back_pos = int(target_deg * STEPS_PER_DEGREE)
                    
                    self.log(f"退避動作: {target_deg:.1f}度 ({target_back_pos}) へ戻ります。")
                    self.motor.write_position(MOTOR_ID, target_back_pos, 500)
                    time.sleep(1.0) # Wait for move
                    break
            
            time.sleep(0.05)
        
        if not stall_detected and self.running:
            self.status_message = "完了 (衝突なし)"
            self.log("動作が正常に完了しました。")
        
        self.running = False

    def close(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.motor:
            self.motor.close()

class RobotGUI:
    def __init__(self, root, controller):
        self.root = root
        self.controller = controller
        
        # Set callback
        self.controller.log_callback = self.append_log
        
        self.root.title("ロボット制御パネル")
        self.root.geometry("500x500")
        
        # Styles
        style = ttk.Style()
        style.configure("TLabel", font=("Meiryo", 12))
        style.configure("TButton", font=("Meiryo", 12))
        
        # Main Frame
        frame = ttk.Frame(root, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Status Label
        self.lbl_status = ttk.Label(frame, text="ステータス: 待機中", font=("Meiryo", 14, "bold"))
        self.lbl_status.pack(pady=10)
        
        # Monitor Frame
        monitor_frame = ttk.LabelFrame(frame, text="モニター", padding="10")
        monitor_frame.pack(fill=tk.X, pady=10)
        
        self.lbl_time = ttk.Label(monitor_frame, text="経過時間: 0.0s")
        self.lbl_time.pack(anchor=tk.W)
        
        self.lbl_pos = ttk.Label(monitor_frame, text="現在位置: ----")
        self.lbl_pos.pack(anchor=tk.W)
        
        self.lbl_load = ttk.Label(monitor_frame, text="負荷: ----")
        self.lbl_load.pack(anchor=tk.W)
        
        # Control Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=20)
        
        self.btn_start = ttk.Button(btn_frame, text="開始 (START)", command=self.on_start)
        self.btn_start.pack(side=tk.LEFT, padx=10)
        
        self.btn_stop = ttk.Button(btn_frame, text="停止 (STOP)", command=self.on_stop)
        self.btn_stop.pack(side=tk.LEFT, padx=10)

        # Log Area
        log_frame = ttk.LabelFrame(frame, text="実行ログ", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        from tkinter.scrolledtext import ScrolledText
        self.txt_log = ScrolledText(log_frame, height=10, state='disabled', font=("Consolas", 10))
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        
        # Start update loop
        self.update_gui()

    def append_log(self, message):
        """Append a message to the scrolled text widget safely."""
        def _update():
            self.txt_log.configure(state='normal')
            self.txt_log.insert(tk.END, message + "\n")
            self.txt_log.see(tk.END)
            self.txt_log.configure(state='disabled')
        
        # Ensure thread safety for GUI updates
        self.root.after(0, _update)

    def on_start(self):
        self.controller.start_move()

    def on_stop(self):
        self.controller.stop_move()

    def update_gui(self):
        # Update labels from controller state
        self.lbl_status.config(text=f"ステータス: {self.controller.status_message}")
        self.lbl_time.config(text=f"経過時間: {self.controller.elapsed_time:.1f}s")
        self.lbl_pos.config(text=f"現在位置: {self.controller.current_pos}")
        self.lbl_load.config(text=f"負荷: {self.controller.current_load}")
        
        # Check if we should disable start button (if already running)
        if self.controller.running:
             self.btn_start.state(['disabled'])
        else:
             self.btn_start.state(['!disabled'])
             
        # Schedule next update
        self.root.after(100, self.update_gui)

def find_serial_port():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    print(f"DEBUG: Found ports: {ports}")
    
    selected_port = None
    if platform.system() == "Windows":
        if 'COM4' in ports: selected_port = 'COM4'
        elif 'COM3' in ports: selected_port = 'COM3'
        if not selected_port and ports: selected_port = ports[-1]
    else:
        selected_port = '/dev/ttyS0'
        
    return selected_port

if __name__ == "__main__":
    port_name = find_serial_port()
    if not port_name:
        print("シリアルポートが見つかりませんでした。")
        # We can still show GUI but it won't work well
        port_name = "COM_DUMMY" 
    
    print(f"{port_name} に接続中...")
    
    # Pass None for controller init, then set callback in GUI if needed,
    # or reorganize. Here we create controller first.
    controller = RobotController(port_name, BAUD_RATE)
    
    if controller.connect():
        print("コントローラー接続成功")
    else:
        print("コントローラー接続失敗")

    root = tk.Tk()
    app = RobotGUI(root, controller)
    
    try:
        root.mainloop()
    finally:
        controller.close()
