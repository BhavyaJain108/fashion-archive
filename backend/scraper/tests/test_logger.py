#!/usr/bin/env python3
"""
Centralized Test Output Logger
=============================

Captures and logs all test outputs to a single file for easy monitoring and debugging.
"""

import sys
import os
import time
from datetime import datetime
from contextlib import contextmanager
from io import StringIO
import threading

class TestOutputLogger:
    """Centralized logger for all test outputs"""
    
    def __init__(self, log_file_path: str = None):
        if log_file_path is None:
            # Default to tests directory
            tests_dir = os.path.dirname(__file__)
            log_file_path = os.path.join(tests_dir, "test_outputs.log")
        
        self.log_file_path = log_file_path
        self.lock = threading.Lock()
        
        # Ensure log file exists
        os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)
        
    def log_test_start(self, test_name: str, command: str = None):
        """Log the start of a test run"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = "=" * 80
        
        with self.lock:
            # Clear the file and write fresh header
            with open(self.log_file_path, 'w', encoding='utf-8') as f:
                f.write(f"{separator}\n")
                f.write(f"TEST START: {test_name}\n")
                f.write(f"TIMESTAMP: {timestamp}\n")
                if command:
                    f.write(f"COMMAND: {command}\n")
                f.write(f"{separator}\n\n")
    
    def log_test_end(self, test_name: str, success: bool = None):
        """Log the end of a test run"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "SUCCESS" if success is True else "FAILED" if success is False else "COMPLETED"
        
        with self.lock:
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"\nTEST END: {test_name} - {status}\n")
                f.write(f"TIMESTAMP: {timestamp}\n")
                f.write(f"{'='*80}\n\n")
    
    def log_output(self, content: str):
        """Log test output content"""
        with self.lock:
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                f.write(content)
                if not content.endswith('\n'):
                    f.write('\n')
    
    def clear_log(self):
        """Clear the log file"""
        with self.lock:
            with open(self.log_file_path, 'w', encoding='utf-8') as f:
                f.write(f"Test Output Log - Started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")


class TeeOutput:
    """Output class that writes to both original stream and log file"""
    
    def __init__(self, original_stream, logger: TestOutputLogger):
        self.original_stream = original_stream
        self.logger = logger
        
    def write(self, text):
        # Write to original stream (console)
        self.original_stream.write(text)
        # Write to log file
        self.logger.log_output(text)
        
    def flush(self):
        self.original_stream.flush()
    
    def __getattr__(self, name):
        return getattr(self.original_stream, name)


# Global logger instance
_global_logger = None

def get_logger() -> TestOutputLogger:
    """Get the global test logger instance"""
    global _global_logger
    if _global_logger is None:
        _global_logger = TestOutputLogger()
    return _global_logger


@contextmanager
def capture_test_output(test_name: str, command: str = None):
    """
    Context manager to capture all test output to log file
    
    Usage:
        with capture_test_output("test_02_pattern_recognition", "python test_02_pattern_recognition.py brand1"):
            # Run your test code here
            print("This will be logged")
    """
    logger = get_logger()
    logger.log_test_start(test_name, command)
    
    # Store original streams
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    try:
        # Replace with tee streams
        sys.stdout = TeeOutput(original_stdout, logger)
        sys.stderr = TeeOutput(original_stderr, logger)
        
        yield logger
        
        logger.log_test_end(test_name, True)
        
    except Exception as e:
        logger.log_output(f"\nERROR: {str(e)}\n")
        logger.log_test_end(test_name, False)
        raise
        
    finally:
        # Restore original streams
        sys.stdout = original_stdout
        sys.stderr = original_stderr


def log_command_run(command: str, test_name: str = None):
    """
    Decorator to automatically log command runs
    
    Usage:
        @log_command_run("python test_02_pattern_recognition.py", "Pattern Recognition Test")
        def run_pattern_test():
            # test code here
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            test_name_final = test_name or func.__name__
            with capture_test_output(test_name_final, command):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def clear_test_log():
    """Clear the test output log"""
    logger = get_logger()
    logger.clear_log()
    print(f"Test log cleared: {logger.log_file_path}")


def view_test_log(lines: int = None):
    """View the test output log"""
    logger = get_logger()
    
    if not os.path.exists(logger.log_file_path):
        print("No test log found")
        return
    
    with open(logger.log_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if lines:
        content_lines = content.split('\n')
        content = '\n'.join(content_lines[-lines:])
    
    print(content)


if __name__ == "__main__":
    # Command line interface
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Output Logger Utility")
    parser.add_argument("--clear", action="store_true", help="Clear the test log")
    parser.add_argument("--view", type=int, nargs="?", const=0, help="View test log (optionally last N lines)")
    parser.add_argument("--path", help="Show log file path")
    
    args = parser.parse_args()
    
    if args.clear:
        clear_test_log()
    elif args.view is not None:
        lines = args.view if args.view > 0 else None
        view_test_log(lines)
    elif args.path:
        logger = get_logger()
        print(logger.log_file_path)
    else:
        # Demo usage
        with capture_test_output("demo_test", "python demo.py"):
            print("This is a demo test output")
            print("Multiple lines will be captured")
            print("Both to console and log file")