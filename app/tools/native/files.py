from app.services.files.file_service import FileService
from app.services.files.document_service import DocumentService
from app.services.files.path_service import PathService

def file_controller(**kwargs) -> dict:
    action  = kwargs.get("action", "").lower().strip()
    path    = kwargs.get("path", "desktop")
    name    = kwargs.get("name", "")
    content = kwargs.get("content", "")

    def _full_path(p: str, n: str) -> str:
        base = PathService.resolve_path(p)
        if n:
            return str(base / n)
        return str(base)

    try:
        if action == "list":
            result = FileService.list_files(path)

        elif action == "create_file":
            full = _full_path(path, name)
            result = FileService.create_file(full, content=content)
            try:
                from core.undo import push_undo
                from send2trash import send2trash
                push_undo(f"Create file {full}", lambda: send2trash(full))
            except Exception:
                pass

        elif action == "create_folder":
            full = _full_path(path, name)
            result = FileService.create_folder(full)
            try:
                from core.undo import push_undo
                from send2trash import send2trash
                push_undo(f"Create folder {full}", lambda: send2trash(full))
            except Exception:
                pass

        elif action == "delete":
            full = _full_path(path, name)
            result = FileService.delete_file(full)

        elif action == "move":
            full = _full_path(path, name)
            result = FileService.move_file(full, kwargs.get("destination", ""))

        elif action == "copy":
            full = _full_path(path, name)
            result = FileService.copy_file(full, kwargs.get("destination", ""))

        elif action == "rename":
            full = _full_path(path, name)
            result = FileService.rename_file(full, kwargs.get("new_name", ""))

        elif action == "read":
            full = _full_path(path, name)
            result = FileService.read_file(full)

        elif action == "write":
            full = _full_path(path, name)
            result = FileService.write_file(
                full,
                content=content,
                append=kwargs.get("append", False)
            )

        elif action == "find":
            result = FileService.find_files(
                name=name or kwargs.get("name", ""),
                extension=kwargs.get("extension", ""),
                path=path,
                max_results=kwargs.get("max_results", 20)
            )

        elif action == "largest":
            result = FileService.get_largest_files(
                path=path,
                count=kwargs.get("count", 10)
            )

        elif action == "disk_usage":
            result = FileService.get_disk_usage(path)

        elif action == "organize_desktop":
            result = FileService.organize_desktop()

        elif action == "info":
            full = _full_path(path, name)
            result = FileService.get_file_info(full)

        else:
            return {"success": False, "result": "", "error": f"Unknown action: '{action}'"}

        return {"success": True, "result": result, "error": ""}

    except Exception as e:
        return {"success": False, "result": "", "error": f"File controller error: {e}"}


def file_processor(**kwargs) -> dict:
    try:
        result = DocumentService.execute(kwargs)
        if "failed" in result.lower() or "error" in result.lower():
            if "saved:" not in result.lower():
                return {"success": False, "result": result, "error": result}
        return {"success": True, "result": result, "error": ""}
    except Exception as e:
        return {"success": False, "result": "", "error": f"File processor error: {e}"}
