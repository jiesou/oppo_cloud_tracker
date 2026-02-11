# OPPO Cloud HeyTap Tracker

Use the [OPPO (HeyTap) Cloud](https://cloud.oppo.com) "Find My Phone" feature to locate OPPO/OnePlus devices and integrate them into Home Assistant as device tracker entities.

[简体中文文档](README.zh.md)

<img width="560" alt="ha device" src="https://github.com/user-attachments/assets/5b8dda5c-f751-4f9a-b184-27affb0f72d5" />
<img width="560" alt="device tracker" src="https://github.com/user-attachments/assets/db90e6ea-19fd-416e-9c64-4d0439ff036d" />

## Features

This integration provides the following information for your OPPO/OnePlus devices:

- **Device model**
- **Location name**
- **GPS coordinates**
- **Last update time**
- **Online status**
- *Might* support multiple devices, but **not tested**

## Requirements

The integration works via Selenium WebDriver and only supports login by phone number and password.

**Warning: Password storage security is NOT guaranteed**

It requires a **separate [Selenium Grid](https://www.selenium.dev/documentation/grid) instance** as the remote browser backend.

### Remote Browser Backend Setup

#### Selenium Grid (Docker)

It is recommended to deploy Selenium Grid using the official Docker `selenium/standalone-chrome` image.

Example `docker-compose.yml`:
```yaml
name: selenium
services:
  standalone-chrome:
    container_name: selenium-chrome
    image: selenium/standalone-chrome:latest
    shm_size: 2gb
    environment:
      # External will access standalone-chrome via SE_NODE_GRID_URL, which is maybe needed if network forward is configured.
      -  SE_NODE_GRID_URL=http://[your_docker_hostname]:4444
    ports:
      - target: 4444
        published: "4444"
        protocol: tcp
      - target: 7900
        published: "7900"
        protocol: tcp
    restart: unless-stopped
```

Then you will get your "Remote Browser URL", which looks like:
`http://[your_docker_hostname]:4444/wd/hub`
Make sure your Home Assistant instance can access the Docker container.

## Installation

### Method 1: HACS (Recommended)

[![Open a repository in your Home Assistant HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiesou&repository=oppo_cloud_tracker&category=integration)

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

You will need to provide:

- **Remote Browser URL**: The URL of your Selenium Grid instance
  - For Selenium Grid: `http://[your_docker_hostname]:4444/wd/hub`
  - Make sure your Home Assistant instance can access the Docker container
- **OPPO Phone Number**: Your OPPO account phone number (**only +86 supported**)
- **OPPO Password**: Your OPPO account password (**Warning again: password security is NOT guaranteed**)

After setup, you can also configure the scan interval (default: 300 seconds / 5 minutes).

The integration creates a virtual switch called "Keep Browser Session" to control session behavior:

- **ON**: Keeps the browser session active between updates
  - Allows higher refresh frequency
  - Requires devices to continuously report GPS (high battery consumption)
  - Better for real-time tracking

- **OFF** (default): Closes the browser session after each update
  - Restarts the browser and re-logs into OPPO Cloud for each update
  - Lower battery impact on devices
  - Suitable for periodic location checks

It also provides a `oppo_cloud_tracker.locate` service for manually triggering an immediate device location update in automations.

## FAQ

1. **Cannot connect to the remote browser**
   - Verify the Remote Browser URL is correct
   - For Selenium Grid, check that SE_NODE_GRID_URL is configured correctly. Ensure Home Assistant can access it: **SE_NODE_GRID_URL should be set to the external port and hostname**.
   - Ensure Home Assistant can access the Docker container
   - Check if the container is running

2. **OPPO login failed**
   - Verify your phone number and password are correct
   - Only +86 (China) phone numbers are supported
   - Try logging in manually to the OPPO Cloud website first

3. **Selenium Grid: session not created from unknown error: cannot create default profile directory**
   - You need to add `shm_size: 2gb` in your `docker-compose.yml`, see [SeleniumHQ/docker-selenium](https://github.com/SeleniumHQ/docker-selenium#--shm-size2g)
   - Check if the disk space is full

4. **Strange errors or timeouts**
   - Since the integration operates via a remote browser, initialization and fetching usually take more than 10 seconds, which is normal.
   - If it consistently takes more than 30 seconds, it's best to check and restart the Selenium Grid container.
   - Restart the Selenium Grid Docker container:
     ```bash
     docker restart selenium-chrome
     ```
   - Check container logs:
     ```bash
     docker logs selenium-chrome
     ```

### Tips & Tricks

- Selenium Grid web VNC viewer: http://[your_docker_hostname]:7900
- Home Assistant logs will show integration activity under `custom_components.oppo_cloud_tracker`

## Disclaimer

This integration is not affiliated with or endorsed by OPPO. It is based on publicly available web interfaces, and all actions on the website follow your configuration. If OPPO changes their website, the integration may stop working. Use at your own risk.
