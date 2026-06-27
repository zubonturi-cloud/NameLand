"""
    CASIO Label Printer
    PC Link QR code Print

    Python 3, Thonny on Windows
    
    This software emulates the communication between a CASIO genue PC Link application FA-775
    and the Label Printer a.k.a. "Name Land" in Japan, printing QR code of text strings onto
    24mm-wide tape with Model KL-A45.
    As not testing on other models, appropriate modifications are likely required.

    27-JUN-2026 M.Negishi

"""
import sys
import time
import serial
import numpy as np
import qrcode
import FreeSimpleGUI as sg

# Machine, Tape and Code
PRINTER_DATA = {
    "KL-A40": {"24mm": "Z576C", "18mm": "Z576D", "12mm": "Z576E",  "9mm": "Z576G",  "6mm": "Z576H"},
    "KL-A45": {"24mm": "Z576C", "18mm": "Z576D", "12mm": "Z576E",  "9mm": "Z576G",  "6mm": "Z576H"},
    "KL-A70": {"46mm": "Z576A", "36mm": "Z576A", "24mm": "Z576C", "18mm": "Z576D", "12mm": "Z576E", "9mm": "Z576G", "6mm": "Z576H"},
    "KL-9000":{"24mm": "Z576A", "18mm": "Z576D", "12mm": "Z576E",  "9mm": "Z576G",  "6mm": "Z576H"},
    "KL-C100":{"46mm": "ZX561", "24mm": "LX240"},
    }

# Settings
class MachineType:
    machine = "KL-A45"
    tape = "24mm"
    code = "Z576C"

class AnyString:
    string = "https://google.com"

# CASIO NAME LAND Protocol
class SerialProtocol:
    EOT = b'\x04'
    ENQ = b'\x05'
    ACK = b'\x06'
        
    def __init__(self, port):
        # Set a short timeout to allow the retry loop to run quickly
        self.ser = serial.Serial(port, baudrate=19200, stopbits=2, timeout=0.01)
        time.sleep(0.3)

    def ensure_connection(self, max_retries=10, interval=0.03):
        """
        Send ENQ (0x05) and retry until an ACK (0x06) is returned.
        """
        print(f"Connecting to printer (max {max_retries} retries)...")
        
        for i in range(max_retries):
            # Clear the receive buffer before sending (discard old, junk data)
            self.ser.reset_input_buffer()
            
            # Send ENQ
            self.ser.write(self.ENQ)
            print(f"Sent: 05 (ENQ)")
            
            # Wait a moment
            time.sleep(interval)
            
            # and see the response
            res = self.ser.read(1)
            if res == self.ACK:
                print(f"Received: 06 (ACK)");
                print(f"Connection established on attempt {i+1}")
                time.sleep(0.01)
                return True
            
            # Logging
            if res:
                print(f"Attempt {i+1}: Received {res.hex().upper()} (not ACK)")
            else:
                print(f"Attempt {i+1}: No response")
                
        print("Error: Could not establish connection (Max retries reached)")
        return False
    
    def close_connection(self, max_retries=3, interval=0.03):
        """
        Send EOT (0x04) and retry until ACK (0x06) is returned.
        """
        print(f"Disconnecting (max {max_retries} retries)...")
        
        for i in range(max_retries):
            # Clear the receive buffer before sending (discard old, junk data)
            self.ser.reset_input_buffer()
            
            # Send EOT
            self.ser.write(self.EOT)
            
            # Wait a moment
            time.sleep(interval)
            
            # and see the response
            res = self.ser.read(1)
            if res == self.ACK:
                print(f"Disconnected on attempt {i+1}")
                return True
            
            # Logging
            if res:
                print(f"Attempt {i+1}: Received {res.hex().upper()} (not ACK)")
            else:
                print(f"Attempt {i+1}: No response")
                
        print("Error: Could not disconnect connection (Max retries reached)")
        return False

    def _calculate_checksum(self, data_list):
        """Calculate the two's complement of the sum of the data"""
        total = sum(data_list) & 0xFF
        return (0x100 - total) & 0xFF

    def _wait_for_ack(self, max_retries=10, interval=0.3):
        """Wait for an ACK with a timeout"""
        print(f"Waiting for ACK(max {max_retries} retries)...")
        
        for i in range(max_retries):
            # Wait a moment
            time.sleep(interval)
            
            # and see the response
            res = self.ser.read(1)
            if res == self.ACK:
                print(f"ACK received on attempt {i+1}")
                return True
 
            # Logging
            if res:
                print(f"Attempt {i+1}: Received {res.hex().upper()} (not ACK)")
            else:
                print(f"Attempt {i+1}: No response")
                
        print("Error: Could not receive ACK (Max retries reached)")
        return False

    def send_single_byte(self, code):
        """Send a 1-byte command and wait for an ACK"""
        self.ser.reset_input_buffer()   # Clear the receive buffer before sending
        self.ser.write(bytes([code]))
        print(f"Sent Signal: {code:02X}")
        return self._wait_for_ack()    

    def send_block(self, command, payload):
        """Construct and send a data block, then wait for an ACK"""
        length = len(payload)
        len_h = (length >> 8) & 0xFF
        len_l = length & 0xFF
        
        data_body = [command] + [len_l, len_h] + list(payload)
        checksum = self._calculate_checksum(data_body)
        
        packet = bytes([0x02] + data_body + [checksum])
        
        self.ser.reset_input_buffer()    # Clear the receive buffer before sending
        self.ser.write(packet)
        print(f"Sent Block: {packet.hex(' ').upper()} (Size: {length})")
        
        return self._wait_for_ack()

    def close(self):
        self.ser.close()
        
class LinkError(Exception):
    """Printer connection error"""
    pass

class CommError(Exception):
    """Communication error"""
    pass

#------------------------------------------------------------------------------------

def generate_qr_bitmap(text, scale=4):
    """
    Generates a QR code and returns a NumPy array in printer format (256xW)
    scale: The number of pixels used to render a single QR code dot (adjusted to fit within 256 dots)
    """
    # QR Code Generation
    qr = qrcode.QRCode(border=1) # Set borders to the minimum
    qr.add_data(text)
    qr.make(fit=True)
    
    # Retrieve as a 2D array (True/False)
    matrix = qr.get_matrix()
    qr_np = np.array(matrix).astype(np.uint8)
    
    # Scale up (enlarge a single dot)
    qr_np = np.repeat(np.repeat(qr_np, scale, axis=0), scale, axis=1)
    
    qr_h, qr_w = qr_np.shape
    
    # Create a canvas matching the printer height of 256 dots (0: White)
    if qr_h > 256:
        raise ValueError("The QR code is too large to fit within 256 dots. Please reduce the scale.")
        
    canvas = np.zeros((256, qr_w), dtype=np.uint8)
    
    # Positioned near the center ([0:qr_h, :] for top-alignment)
    start_y = (256 - qr_h) // 2
    canvas[start_y:start_y+qr_h, :] = qr_np
    
    return canvas

def convert_to_printer_bytes(canvas):
    """
    Convert a NumPy array (256xW) into a byte sequence conforming to printer specifications.
    Specifications: 32 bytes in the Y-direction (LSB at the top), arranged along the X-direction.
    """
    h, w = canvas.shape # h is fixed at 256
    payload = []
    
    for x in range(w):
        column = canvas[:, x]
        # Convert 256 dots to 32 bytes
        for b in range(32):
            byte_val = 0
            for bit in range(8):
                # The LSB (bit 0) corresponds to the lower dot number (top).
                dot_idx = b * 8 + bit
                if column[dot_idx] > 0:
                    byte_val |= (1 << bit)
            payload.append(byte_val)
            
    return payload

# --------- Functions for communication elements --------- 

def setconfig():
    # Check Model and Tape Width
    if not proto.send_block(0x00, list(MachineType.code.encode())):
        raise CommError("Communication Error.")            
    print("Configuration acknowledged.")
       
def fd80():
    # Unknown (FD-80)
    if not proto.send_block(0xFD, [0x80]):
        raise CommError("Communication Error.")            
    print("FD-80 command acknowledged.")

def nofeed():
    # Feed length 0 mm (0D-01)
    if not proto.send_block(0x0D, [0x01]):
        raise CommError("Communication Error.")            
    print("0D-01 command acknowledged.")
    
def feed17mm():
    # Feed length 17mm (0D-02)
    if not proto.send_block(0x0D, [0x02]):
        raise CommError("Communication Error.")            
    print("0D-02 command acknowledged.")
   
def feed3mm():
    # Feed length 3mm (0D-40)
    if not proto.send_block(0x0D, [0x40]):
        raise CommError("Communication Error.")            
    print("0D-40 command acknowledged.")

def header():
    # Unknown (01)
    if not proto.send_block(0x01, []):
        raise CommError("Communication Error.")            
    print("01 command acknowledged.")
    
    # Unknown (09)
    if not proto.send_block(0x09, [0x00, 0x00]):
        raise CommError("Communication Error.")            
    print("09 command acknowledged.")    
    
def picture():
    #Bitmap Data Transmission
    if not proto.send_block(0xFE, bitmap_payload):
        raise CommError("Communication Error.")
    print("bitmap block sent and acknowledged.")
   # Transfer complete? (04)
    if not proto.send_block(0x04, []):
        raise CommError("Communication Error.")            
    print("04 command acknowledged.")

def gofeed():
    # Execute tape feed (0A)
    if not proto.send_single_byte(0x0A):
        raise CommError("Communication Error.")            
    print("Tape Feed command acknowledged.")
    # After sending an immediate execution command, wait during the BUSY period
    if not proto.ensure_connection(max_retries=20, interval=0.03):
        raise LinkError("Failed to ensuring communication.")    

def goprint():
    # Beep (0D) - Execute print?
    if not proto.send_single_byte(0x0D):
        raise CommError("Communication Error.")            
    print("Print command acknowledged.")   
    # After sending an immediate execution command, wait during the BUSY period
    if not proto.ensure_connection(max_retries=30, interval=0.5):
        raise LinkError("Failed to ensuring communication.")

def gocut():   
    # Tape-cutting (08)
    if not proto.send_single_byte(0x08):
        raise CommError("Communication Error.")            
    print("Tape cut command acknowledged.")
    # After sending an immediate execution command, wait during the BUSY period
    if not proto.ensure_connection(max_retries=20, interval=0.1):
        raise LinkError("Failed to ensuring communication.")          

def finish():
    if proto.close_connection(max_retries=3, interval=0.03):
        print("Connection closed.")
    else:
        print("Failed to disconnect.")

# Printer Model and Tape Width Selection Dialog
def selectmachine():
    layout = [
        [sg.Text("Printer model:"), 
         sg.Combo(list(PRINTER_DATA.keys()), key="-MODEL-", enable_events=True, readonly=True, size=(15, 1))],
    
        [sg.Text("Tape width:   "), 
         sg.Combo([], key="-WIDTH-", enable_events=True, readonly=True, size=(15, 1))],
    
        [sg.Button("OK")]
    ]

    window = sg.Window("Select Printer Model", layout)
    #window["-MODEL-"].update(values=MachineType.machine)
    #window["-WIDTH-"].update(values=MachineType.tape)

    while True:
        event, values = window.read()

        if event in (sg.WIN_CLOSED, "OK"):
            break

        # Update the tape width list when a model is selected
        if event == "-MODEL-":
            selected_model = values["-MODEL-"]
            widths = list(PRINTER_DATA[selected_model].keys())
            MachineType.machine = selected_model
        
            # Update the tape width list and reset the selection state
            window["-WIDTH-"].update(values=widths, value="")

        # Identify the internal code once the tape width is selected
        if event == "-WIDTH-":
            selected_model = values["-MODEL-"]
            selected_width = values["-WIDTH-"]
            MachineType.machine = selected_model
            MachineType.tape = selected_width
            if selected_model and selected_width:
                # Retrieve a unique 5-character code from the dictionary
                internal_code = PRINTER_DATA[selected_model][selected_width]
                MachineType.code = internal_code
    window.close()

# --------- Input dialog for QR code content --------- 
def inputplain():
    sg.theme('DarkAmber')   # Add a touch of color
    # All the stuff inside your window.
    layout = [  [sg.Text(MachineType.tape + " Tape")],
            [sg.Text('QR code:'), sg.InputText()],
            [sg.Button('OK'), sg.Button('Cancel')] ]

    # Create the Window
    window = sg.Window("CASIO NAME LAND "+MachineType.machine, layout)
    # Event Loop to process "events" and get the "values" of the inputs
    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED or event == 'Cancel': # if user closes window or clicks cancel
            sys.exit() # It will finish without doing anything
        elif event == 'OK':
            if values[0] != "":
                AnyString.string = values[0]
            break

    window.close()
    
# === When executed directly ===
if __name__ == "__main__":
    proto = SerialProtocol('COM3')

    selectmachine()
    print(f"{MachineType.machine} {MachineType.tape} selected")

    inputplain()
    print(f"User input = {AnyString.string}")

    qr_canvas = generate_qr_bitmap(AnyString.string, scale=6)
    bitmap_payload = convert_to_printer_bytes(qr_canvas)

    try:
        # Connection Check
        if not proto.ensure_connection(max_retries=20, interval=0.03):
            raise LinkError("Failed to start communication.")

        """
        The following is the sequence for reproducing the communication between
        the genuine CASIO PC connection software FA-775 and the NAME LAND
        
        Standard Print Procedure with auto cutter:    without cutter:
        
        setconfig()                                   setconfig()
        fd80()                                        fd80()
        feed3mm()
        gofeed()
        setconfig()
        feed3mm()
        gofeed()
        setconfig()
        fd80()
        header()                                      header()
        feed3mm()                                     feed3mm()
        picture()                                     picture()
        goprint()                                     goprint()
        setconfig()                                   setconfig()
        feed3mm()                                     feed3mm()
        gofeed()                                      gofeed()
        setconfig()
        feed17mm()
        gofeed()
        setconfig()
        gocut()
        finish()                                      finish()
        """

        # My print test for KL-A45
        
        setconfig()
        fd80()
        feed3mm()
        gofeed()
        gofeed()
        header()
        picture()
        goprint()
        feed3mm()
        gofeed()
        gocut()
        finish()
        
    except CommError as e:
        print(f"{e}")
    
    except LinkError as e:
        print(f"{e}")
        
    finally:
        proto.close()
    