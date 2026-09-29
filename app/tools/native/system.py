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
        
        # Guard for dangerous actions using Mark-LV's confirm_gate
        if action in ("restart", "shutdown"):
            token = kwargs.get("token")
            try:
                from core.confirm import confirm_gate
                if not confirm_gate.verify(token):
                    # Request UI confirmation banner
                    confirm_gate.request(
                        summary=f"Computer System {action.capitalize()}",
                        detail=f"The assistant is attempting to {action} your computer.",
                        on_confirm=lambda: service.execute_action(action, value),
                        danger=True
                    )
                    return {
                        "success": False,
                        "result": "",
                        "error": f"Confirmation required. A prompt has been displayed on the screen for human approval."
                    }
            except ImportError:
                pass
                
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
