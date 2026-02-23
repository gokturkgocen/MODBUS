# Modbus RTU HMI Control Panel

A Python-based Modbus RTU control panel application featuring a modern, sleek interface inspired by the "Matrix" aesthetic. This software allows you to seamlessly monitor and control multiple Modbus devices (slaves) concurrently via serial port connections (RS485/RS232).

## Key Features

- **Multi-Device Support**: Add and monitor multiple Modbus nodes simultaneously, keeping track of their status in real-time.
- **Sequential & Priority Polling**: A background polling mechanism ensures continuous data updates, while a queue-based priority system handles user commands (write operations) with minimal latency.
- **Detailed Error Tracking**: Real-time display of device connection issues, communication lag, and Modbus-specific errors directly on the interface.
- **Customizable Parameters**: Easy-to-use interface to access and modify Modbus registers for each device, including opening/closing speeds, torque, or custom durations.
- **Matrix-Themed UI**: Built using `CustomTkinter`, the application features a dark background with vibrant neon-green accents, delivering a professional, terminal-style aesthetic.

## Requirements

This project is designed to run on Python 3.10 or newer.

To install the required dependencies, execute the following command after cloning the repository:

```bash
pip install -r requirements.txt
```

### Core Dependencies
- `customtkinter`: For the modern GUI.
- `minimalmodbus`: For handling Modbus RTU communication.
- `pyserial`: For serial port access and management.

## Installation & Usage Guide

1. Clone the repository to your local machine:
   ```bash
   git clone <repo-url>
   cd MODBUS
   ```

2. Install the necessary Python packages:
   ```bash
   pip install -r requirements.txt
   ```

3. Launch the application:
   ```bash
   python modbus_panel.py
   ```

4. **Operation Steps**:
   - Select the appropriate `PORT` (e.g., COMx) and `BAUD` rate (e.g., 9600) from the top Toolbar.
   - Click the `[+ ADD NODE]` button to register the devices you wish to control by providing their Slave IDs (e.g., 1, 2) and custom labels.
   - Press `[ EXEC CONNECT ]` to initialize serial communication (polling). Once devices are online, their status will update to a glowing green "ONLINE".
   - Control devices directly via the action buttons (e.g., OPEN/CLOSE) on their respective cards, or access the `[SETTINGS]` menu to update granular register values.

## File Structure

- `modbus_panel.py`: The main source code, containing both the GUI implementation and Modbus communication logic.
- `devices.json`: A configuration file that stores the registered slave IDs and device labels (automatically generated/updated during runtime).
- `requirements.txt`: The list of required Python dependencies.

## License

This project was developed for personal and developmental purposes.
