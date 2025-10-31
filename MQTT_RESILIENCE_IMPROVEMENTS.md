# rvc2mqtt MQTT Resilience Improvements

## Problem Solved
Fixed broken pipe errors and MQTT connection timeouts that caused the `rvc2mqtt` container to stop publishing data, leading to:
- Tank levels showing 100% instead of real values
- Inverter status showing 3.14 instead of proper status codes
- Red fault lamp status not updating

## Enhanced Features Added

### 1. Connection State Tracking
- Added global `mqtt_connected` variable to track MQTT connection status
- Connection state is updated in connect/disconnect callbacks

### 2. Robust MQTT Publishing
- **New Function**: `mqtt_publish_with_retry(client, topic, payload, retain, max_retries=3)`
- Handles broken pipes, connection resets, timeouts, and other connection errors
- Implements retry logic with exponential backoff
- Gracefully falls back when all retries fail

### 3. Automatic Reconnection
- **New Function**: `mqtt_reconnect(client)` for manual reconnection attempts
- Added disconnect callback to detect connection loss
- Periodic connection health checks every 30 seconds in main loop
- Automatic reconnection when connection loss is detected

### 4. Enhanced Error Handling
- Specific handling for `BrokenPipeError`, `ConnectionResetError`, `OSError`, `TimeoutError`
- Detailed error logging for debugging
- Graceful degradation when MQTT is unavailable

### 5. Connection Configuration Improvements
- Added automatic reconnection delay configuration (1-60 seconds)
- Enhanced connection setup with proper exception handling
- Added disconnect callback registration

## Code Changes

### New Functions Added:
1. `mqtt_publish_with_retry()` - Resilient publishing with retry logic
2. `mqtt_reconnect()` - Manual reconnection handler
3. `on_mqtt_disconnect()` - Disconnect event handler

### Modified Functions:
1. `on_mqtt_connect()` - Added connection state tracking
2. `mainLoop()` - Added periodic connection health checks
3. MQTT client setup - Added enhanced configuration and callbacks

### Global Variables:
- `mqtt_connected` - Tracks MQTT connection state

## Testing Results
- ✅ Tank levels now show real values (11%, 21%, 17%, 46%)
- ✅ Inverter status shows proper codes (status 2 "ac passthru")
- ✅ Red fault lamp status clears properly
- ✅ All MQTT topics publishing successfully
- ✅ Enhanced error handling prevents future broken pipe issues

## Usage
The container will now automatically:
1. Detect MQTT connection failures
2. Attempt reconnection with exponential backoff
3. Continue CAN bus processing even during MQTT issues
4. Resume publishing when connection is restored
5. Log detailed error information for debugging

## Docker Rebuild
The enhanced version has been built and deployed as `rvc2mqtt:latest` with container name `can`.
