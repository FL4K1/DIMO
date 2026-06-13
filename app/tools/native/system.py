"""
Native DIMO tools for System Management (Windows).
Thin wrappers around app.services.system.* logic.
"""

from app.services.system.windows_settings import WindowsSettingsService
from app.services.system.task_scheduler import TaskSchedulerService

def computer_settings(**kwargs) -> dict:
    """Adjust system settings (volume, brightness, power state, etc.)."""
    try:
        service = WindowsSettingsService()
        action = kwargs.get("action", "")
        value = kwargs.get("value")
        
        # Guard for dangerous actions
        if action in ("restart", "shutdown"):
            confirmed = str(kwargs.get("confirmed", "")).lower()
            if confirmed not in ("yes", "true", "1", "confirm"):
                return {
                    "success": False,
                    "result": "",
                    "error": f"This will {action} the computer. Please confirm by calling again with confirmed=yes."
                }
                
        result = service.execute_action(action, value)
        return {"success": True, "result": result, "error": ""}
    except Exception as e:
        return {"success": False, "result": "", "error": str(e)}

def reminder(**kwargs) -> dict:
    """Set a Windows Task Scheduler reminder."""
    try:
        service = TaskSchedulerService()
        date_str = kwargs.get("date")
        time_str = kwargs.get("time")
        message = kwargs.get("message", "Reminder")
        
        if not date_str or not time_str:
            return {"success": False, "result": "", "error": "Both date and time are required."}
            
        result = service.create_reminder(date_str, time_str, message)
        return {"success": True, "result": result, "error": ""}
    except Exception as e:
        return {"success": False, "result": "", "error": str(e)}
