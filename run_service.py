# cd notediscovery installation path
# pip install pywin32
# pip install psutil 

# python .\run_service.py install
# python .\run_service.py remove
# python .\run_service.py start
# python .\run_service.py stop

import win32serviceutil
import win32service
import win32event
import servicemanager
import subprocess
import sys
import os
from pathlib import Path

class PyService(win32serviceutil.ServiceFramework):
    _svc_name_ = "NoteDiscovery"
    _svc_display_name_ = "NoteDiscovery Service"
    _svc_description_ = "Start NoteDiscovery - 127.0.0.1:8000" #check your port

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None
        
        # Setup paths
        self.service_dir = Path(__file__).parent.absolute()
        self.log_file = self.service_dir / "service.log"
        self.error_file = self.service_dir / "service_error.log"

    def log(self, message):
        """Write to both service log and file"""
        # Windows Event Log
        servicemanager.LogInfoMsg(f"{self._svc_name_}: {message}")
        # File log
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

    def SvcStop(self):
        self.log("Stop signal received")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.process and self.process.poll() is None:
            try:
                self.log("Terminating process tree...")
                # Kill the entire process tree (including child processes like uvicorn)
                self._kill_process_tree(self.process.pid)
                self.log("Process tree terminated successfully")
            except Exception as e:
                self.log(f"Error terminating process: {e}")
        win32event.SetEvent(self.stop_event)

    def _kill_process_tree(self, pid):
        """Terminate a process and all its children"""
        import psutil
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            # Terminate children first
            for child in children:
                try:
                    self.log(f"Terminating child process {child.pid}")
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            
            # Terminate parent
            parent.terminate()
            
            # Wait for graceful termination
            gone, alive = psutil.wait_procs(children + [parent], timeout=5)
            
            # Force kill any remaining processes
            for p in alive:
                try:
                    self.log(f"Force killing process {p.pid}")
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
                    
        except psutil.NoSuchProcess:
            self.log(f"Process {pid} already terminated")
        except Exception as e:
            self.log(f"Error in _kill_process_tree: {e}")

    def SvcDoRun(self):
        try:
            self.log(f"Service starting in directory: {self.service_dir}")
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                  servicemanager.PYS_SERVICE_STARTED,
                                  (self._svc_name_, ''))
            
            # In service context, sys.executable is pythonservice.exe, not python.exe
            # We need to find the actual python.exe in the same directory
            service_exe = Path(sys.executable)
            python_exe = service_exe.parent / "python.exe"
            
            if not python_exe.exists():
                # Try pythonw.exe as fallback
                python_exe = service_exe.parent / "pythonw.exe"
            
            if not python_exe.exists():
                self.log(f"ERROR: Could not find python.exe in {service_exe.parent}")
                return
            
            script_path = self.service_dir / "run.py"
            
            self.log(f"Python executable: {python_exe}")
            self.log(f"Script path: {script_path}")
            
            # Check if script exists
            if not script_path.exists():
                self.log(f"ERROR: Script not found at {script_path}")
                return
            
            # Create/clear log files (use 'w' to overwrite old logs)
            stdout_file = open(self.service_dir / "service_stdout.log", 'w', encoding='utf-8')
            stderr_file = open(self.service_dir / "service_stderr.log", 'w', encoding='utf-8')
            
            self.log("Log files created/cleared")
            
            # Prepare environment with service flag
            env = os.environ.copy()
            env['RUNNING_AS_SERVICE'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'  # Fix emoji encoding issues
            env['PYTHONUTF8'] = '1'  # Enable UTF-8 mode
            
            # Start subprocess with proper working directory and output redirection
            self.log("Starting subprocess...")
            self.process = subprocess.Popen(
                [str(python_exe), str(script_path)],
                cwd=str(self.service_dir),
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env
            )
            
            self.log(f"Process started with PID: {self.process.pid}")
            
            # Check if process is still running after a short delay
            import time
            time.sleep(2)
            if self.process.poll() is not None:
                self.log(f"WARNING: Process terminated immediately with code: {self.process.returncode}")
                stdout_file.close()
                stderr_file.close()
                return
            else:
                self.log("Process is running successfully")
            
            # Wait until stop requested
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
            
            # Cleanup
            self.log("Cleaning up...")
            stdout_file.close()
            stderr_file.close()
            
            if self.process and self.process.poll() is None:
                try:
                    self._kill_process_tree(self.process.pid)
                except Exception as e:
                    self.log(f"Error during cleanup: {e}")
                    
        except Exception as e:
            self.log(f"EXCEPTION in SvcDoRun: {e}")
            import traceback
            self.log(traceback.format_exc())

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(PyService)
