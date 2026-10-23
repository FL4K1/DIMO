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
        action = str(kwargs.get("action", "")).lower().strip().replace(" ", "_").replace("-", "_")
        value = kwargs.get("value")
        
        # Guard for dangerous actions using Mark-LV's confirm module
        dangerous_restart = ("restart", "restart_computer")
        dangerous_shutdown = ("shutdown", "shutdown_computer")

        if action in dangerous_restart or action in dangerous_shutdown:
            try:
                import core.confirm as confirm
            except ImportError:
                try:
                    from app.marklv.core import confirm
                except ImportError:
                    confirm = None

            if confirm is None:
                return {
                    "success": False,
                    "pending_confirmation": False,
                    "result": "",
                    "error": (
                        f"Confirmation interface is unavailable. Cannot execute {action} "
                        "without human confirmation."
                    ),
                }

            if confirm.pending_title():
                return {
                    "success": False,
                    "pending_confirmation": True,
                    "result": (
                        f"[CONFIRMATION_PENDING] A confirmation for '{confirm.pending_title()}' "
                        "is already pending on the HUD."
                    ),
                    "error": f"Another confirmation ('{confirm.pending_title()}') is currently pending on the HUD.",
                }

            is_restart = action in dangerous_restart
            canonical_key = "restart" if is_restart else "shutdown"
            title = f"Computer {'Restart' if is_restart else 'Shutdown'}"
            detail = f"The assistant requested to {'restart' if is_restart else 'shut down'} this computer."
            req_msg = confirm.request(
                key=canonical_key,
                title=title,
                detail=detail,
                run=lambda: str(service.execute_action(action, value)),
            )

            if req_msg.startswith("[CONFIRMATION_PENDING]"):
                return {
                    "success": False,
                    "pending_confirmation": True,
                    "result": req_msg,
                    "error": "Confirmation required on HUD before action can proceed.",
                }
            else:
                return {
                    "success": False,
                    "pending_confirmation": False,
                    "result": "",
                    "error": req_msg,
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
