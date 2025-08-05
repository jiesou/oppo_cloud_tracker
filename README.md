# OPPO Cloud HeyTap Tracker

[![Open a repository in your Home Assistant HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiesou&repository=oppo_cloud_tracker&category=integration)

Use the Device Find feature of OPPO (HeyTap) Cloud to locate OPPO/OnePlus devices and integrate them into Home Assistant as Device Tracker entities.

[简体中文文档](README.zh.md) | [English Documentation](README.md)

## ⚠️ Security Warning

**This integration uses phone number and password for authentication. Password security cannot be guaranteed!** The integration automates the OPPO Cloud web interface using Selenium WebDriver, which means your credentials are processed by browser automation. Use at your own risk and consider using a dedicated account if possible.

## Features

This integration provides the following device information for your OPPO/OnePlus devices:

- **Device Model** - The model name of your device
- **Location Name** - Human-readable address of the device location
- **GPS Coordinates** - Latitude and longitude data
- **Battery Level** - Current battery percentage
- **Last Update Time** - When the device last reported its location
- **Online Status** - Whether the device is currently online
- **Multiple Device Support** - May support multiple devices (untested by author)

## Requirements

This integration requires a **separate Selenium Grid instance** to operate. It uses Selenium WebDriver to automate the OPPO Cloud web interface since no official API is available.

### Selenium Grid Setup

The recommended way to deploy Selenium Grid is using Docker with the `selenium/standalone-chrome` image.

Create a `docker-compose.yml` file:

```yaml
name: selenium
services:
  standalone-chrome:
    cpu_shares: 90
    command: []
    container_name: selenium-chrome
    hostname: selenium-chrome
    image: selenium/standalone-chrome:latest
    ports:
      - target: 4444
        published: "4444"
        protocol: tcp
      - target: 7900
        published: "7900"
        protocol: tcp
    restart: unless-stopped
    network_mode: bridge
    privileged: false
```

Then run:
```bash
docker-compose up -d
```

For more information about Selenium Grid, visit: https://www.selenium.dev/documentation/grid/

## Installation

### Method 1: HACS (Recommended)

[![Open a repository in your Home Assistant HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiesou&repository=oppo_cloud_tracker&category=integration)

1. Click the badge above or manually add this repository to HACS
2. Search for "OPPO Cloud HeyTap Tracker"
3. Install the integration
4. Restart Home Assistant

### Method 2: Manual Installation

1. Download this repository
2. Copy the `custom_components/oppo_cloud_tracker` folder to your Home Assistant's `custom_components` directory
3. Restart Home Assistant

## Configuration

### Step 1: Add Integration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "OPPO Cloud HeyTap Tracker"
4. Click to add the integration

### Step 2: Configure Connection

You'll need to provide:

- **Selenium Grid URL**: The URL to your Selenium Grid instance
  - Format: `http://[your_docker_hostname]:4444/wd/hub`
  - Default: `http://localhost:4444/wd/hub`
  - Make sure your Home Assistant instance can access the Docker container
- **OPPO Phone Number**: Your OPPO account phone number (+86 only)
- **OPPO Password**: Your OPPO account password

### Step 3: Configure Options (Optional)

After adding the integration, you can configure additional options:

- **Scan Interval**: How often to update device locations (default: 300 seconds / 5 minutes)
  - Range: 30-3600 seconds
  - ⚠️ **Be careful with power consumption!** Lower intervals require devices to report GPS more frequently

### Step 4: Session Management

The integration creates a virtual switch called "Keep Selenium Session" to control session behavior:

- **ON**: Keeps the Selenium session active between updates
  - Allows higher refresh frequencies
  - Requires devices to constantly report GPS (high battery drain)
  - Better for real-time tracking
  
- **OFF** (Default): Closes Selenium session after each update
  - Restarts Selenium and re-logs into OPPO Cloud for each update
  - Lower battery impact on devices
  - Suitable for periodic location checks

## Usage

Once configured, the integration will:

1. Create device tracker entities for each discovered OPPO/OnePlus device
2. Update device locations based on your configured scan interval
3. Provide device information as entity attributes
4. Allow manual location updates via the "Locate Devices" service

### Available Services

- **Locate Devices** (`oppo_cloud_tracker.locate`): Triggers an immediate update of all device locations

## Troubleshooting

### Common Issues

1. **Cannot connect to Selenium Grid**
   - Verify the Selenium Grid URL is correct
   - Ensure Home Assistant can reach the Docker container
   - Check that the Selenium Grid container is running

2. **OPPO login failed**
   - Verify your phone number and password are correct
   - Only +86 (China) phone numbers are supported
   - Try logging in manually to OPPO Cloud website first

3. **Devices not appearing**
   - Make sure devices are linked to your OPPO account
   - Check that device location services are enabled
   - Wait for the initial scan to complete

4. **Strange errors or timeouts**
   - Restart the Selenium Grid Docker container:
     ```bash
     docker restart selenium-chrome
     ```
   - Check Selenium Grid logs:
     ```bash
     docker logs selenium-chrome
     ```

### Debug Information

- Selenium Grid web interface: http://[your_docker_hostname]:7900 (VNC viewer)
- Home Assistant logs will show integration activity under `custom_components.oppo_cloud_tracker`

## Limitations

- Only supports phone number + password authentication
- Only supports +86 (China) phone numbers
- Requires active internet connection for both Home Assistant and tracked devices
- Password security cannot be guaranteed (browser automation)
- Multiple device support is untested
- May be affected by OPPO Cloud website changes

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This integration is not affiliated with or endorsed by OPPO. It uses publicly available web interfaces and may stop working if OPPO changes their website. Use at your own risk.