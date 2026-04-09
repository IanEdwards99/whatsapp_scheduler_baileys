#!/usr/bin/env python3
"""
Process manager to supervise driver server and background scheduler
Implements auto-restart with exponential backoff
"""

import subprocess
import time
import requests
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ProcessSupervisor:
    """Supervise and restart processes on failure"""
    
    def __init__(self):
        self.driver_process = None
        self.scheduler_process = None
        self.driver_restart_count = 0
        self.scheduler_restart_count = 0
        self.max_restarts = 5
        self.base_backoff = 5  # seconds
    
    def start_driver_server(self):
        """Start Node.js driver server"""
        try:
            logger.info("Starting driver server...")
            self.driver_process = subprocess.Popen(
                ["node", "server.js"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent
            )
            time.sleep(5)  # Wait for startup
            
            if self.check_driver_health():
                logger.info("✓ Driver server started successfully")
                self.driver_restart_count = 0
                return True
            else:
                logger.error("✗ Driver server failed health check")
                return False
        
        except Exception as e:
            logger.error(f"Failed to start driver server: {e}")
            return False
    
    def start_background_scheduler(self):
        """Start Python background scheduler"""
        try:
            logger.info("Starting background scheduler...")
            self.scheduler_process = subprocess.Popen(
                ["python3", "background_scheduler.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent
            )
            time.sleep(2)
            
            if self.scheduler_process.poll() is None:
                logger.info("✓ Background scheduler started successfully")
                self.scheduler_restart_count = 0
                return True
            else:
                logger.error("✗ Background scheduler exited immediately")
                return False
        
        except Exception as e:
            logger.error(f"Failed to start background scheduler: {e}")
            return False
    
    def check_driver_health(self) -> bool:
        """Check if driver server is responding"""
        try:
            response = requests.get("http://127.0.0.1:5001/status", timeout=2)
            return response.status_code == 200
        except Exception:
            return False
    
    def check_scheduler_health(self) -> bool:
        """Check if scheduler process is running"""
        if self.scheduler_process is None:
            return False
        return self.scheduler_process.poll() is None
    
    def restart_driver_with_backoff(self):
        """Restart driver with exponential backoff"""
        self.driver_restart_count += 1
        
        if self.driver_restart_count > self.max_restarts:
            logger.error("Max driver restarts reached, giving up")
            return False
        
        backoff = self.base_backoff * (2 ** (self.driver_restart_count - 1))
        logger.warning(f"Restarting driver (attempt {self.driver_restart_count}) in {backoff}s")
        time.sleep(backoff)
        
        if self.driver_process:
            try:
                self.driver_process.terminate()
                self.driver_process.wait(timeout=5)
            except Exception:
                pass
        
        return self.start_driver_server()
    
    def restart_scheduler_with_backoff(self):
        """Restart scheduler with exponential backoff"""
        self.scheduler_restart_count += 1
        
        if self.scheduler_restart_count > self.max_restarts:
            logger.error("Max scheduler restarts reached, giving up")
            return False
        
        backoff = self.base_backoff * (2 ** (self.scheduler_restart_count - 1))
        logger.warning(f"Restarting scheduler (attempt {self.scheduler_restart_count}) in {backoff}s")
        time.sleep(backoff)
        
        if self.scheduler_process:
            try:
                self.scheduler_process.terminate()
                self.scheduler_process.wait(timeout=5)
            except Exception:
                pass
        
        return self.start_background_scheduler()
    
    def supervise(self):
        """Main supervision loop"""
        logger.info("=== Process Manager Started ===")
        
        # Initial startup
        if not self.start_driver_server():
            logger.error("Failed to start driver server initially")
            return
        
        if not self.start_background_scheduler():
            logger.error("Failed to start background scheduler initially")
            return
        
        logger.info("All processes started, entering supervision mode")
        
        try:
            while True:
                time.sleep(10)  # Check every 10 seconds
                
                # Check driver health
                if not self.check_driver_health():
                    logger.error("Driver server unhealthy!")
                    if not self.restart_driver_with_backoff():
                        logger.critical("Failed to restart driver, exiting")
                        break
                
                # Check scheduler health
                if not self.check_scheduler_health():
                    logger.error("Scheduler process crashed!")
                    if not self.restart_scheduler_with_backoff():
                        logger.critical("Failed to restart scheduler, exiting")
                        break
        
        except KeyboardInterrupt:
            logger.info("Supervisor stopped by user")
        
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up processes on exit"""
        logger.info("Cleaning up processes...")
        
        if self.driver_process:
            try:
                self.driver_process.terminate()
                self.driver_process.wait(timeout=5)
            except Exception as e:
                logger.error(f"Error terminating driver: {e}")
        
        if self.scheduler_process:
            try:
                self.scheduler_process.terminate()
                self.scheduler_process.wait(timeout=5)
            except Exception as e:
                logger.error(f"Error terminating scheduler: {e}")
        
        logger.info("Cleanup complete")


if __name__ == "__main__":
    supervisor = ProcessSupervisor()
    supervisor.supervise()
