"""
Windows System Settings Service
Provides programmatic control over Windows system settings.
"""

import subprocess
import time
import ctypes

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
except ImportError:
    pass

class WindowsSettingsService:
    def volume_up(self):
        for _ in range(5):
            pyautogui.press("volumeup")
        return "Volume increased."

    def volume_down(self):
        for _ in range(5):
            pyautogui.press("volumedown")
        return "Volume decreased."

    def volume_mute(self):
        pyautogui.press("volumemute")
        return "Volume mute toggled."

    def volume_set(self, value: int):
        value = max(0, min(100, int(value)))
        try:
            import math
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
            vol_db = -65.25 if value == 0 else max(-65.25, 20 * math.log10(value / 100))
            vol.SetMasterVolumeLevel(vol_db, None)
            return f"Volume set to {value}%."
        except Exception as e:
            # Fallback
            pyautogui.press("volumemute")
            pyautogui.press("volumemute")
            return f"Volume set via pycaw failed, triggered fallback. Error: {e}"

    def brightness_up(self):
        script = (
            "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
            ".WmiSetBrightness(1, [math]::Min(100, "
            "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness + 10))"
        )
        subprocess.run(["powershell", "-Command", script], capture_output=True, timeout=5)
        return "Brightness increased."

    def brightness_down(self):
        script = (
            "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
            ".WmiSetBrightness(1, [math]::Max(0, "
            "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness - 10))"
        )
        subprocess.run(["powershell", "-Command", script], capture_output=True, timeout=5)
        return "Brightness decreased."

    def lock_screen(self):
        pyautogui.hotkey("win", "l")
        return "Screen locked."

    def sleep_display(self):
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        return "Display sleeping."

    def dark_mode(self):
        import winreg
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
        current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1 - current)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1 - current)
        winreg.CloseKey(key)
        return "Dark mode toggled."

    def toggle_wifi(self):
        script = (
            "$adapter = Get-NetAdapter | Where-Object {$_.PhysicalMediaType -eq 'Native 802.11'};"
            "if ($adapter.Status -eq 'Up') { Disable-NetAdapter -Name $adapter.Name -Confirm:$false }"
            "else { Enable-NetAdapter -Name $adapter.Name -Confirm:$false }"
        )
        subprocess.run(["powershell", "-Command", script], capture_output=True, timeout=10)
        return "Wi-Fi toggled."

    def restart_computer(self):
        subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True)
        return "Computer restarting in 10 seconds."

    def shutdown_computer(self):
        subprocess.run(["shutdown", "/s", "/t", "10"], capture_output=True)
        return "Computer shutting down in 10 seconds."

    def execute_action(self, action: str, value=None):
        """Map a string action to the corresponding method."""
        action = action.lower().strip().replace(" ", "_").replace("-", "_")
        
        if action in ("volume_set",) and value is not None:
            return self.volume_set(int(value))
            
        action_map = {
            "volume_up": self.volume_up,
            "volume_down": self.volume_down,
            "mute": self.volume_mute,
            "unmute": self.volume_mute,
            "toggle_mute": self.volume_mute,
            "brightness_up": self.brightness_up,
            "brightness_down": self.brightness_down,
            "lock_screen": self.lock_screen,
            "sleep_display": self.sleep_display,
            "screen_off": self.sleep_display,
            "dark_mode": self.dark_mode,
            "toggle_wifi": self.toggle_wifi,
            "restart": self.restart_computer,
            "shutdown": self.shutdown_computer,
        }
        
        if action in action_map:
            return action_map[action]()
            
        raise ValueError(f"Unknown system settings action: '{action}'")
