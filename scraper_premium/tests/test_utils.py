"""
Test Utilities
==============

Common utilities for test logging, formatting, and helper functions.
"""

import time
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from contextlib import contextmanager


class TestLogger:
    """Enhanced logging for tests with structured output"""
    
    def __init__(self, test_name: str):
        self.test_name = test_name
        self.start_time = time.time()
        self.step_count = 0
        
    def header(self, message: str):
        """Print test header"""
        print(f"\n{'='*80}")
        print(f"🧪 TEST: {self.test_name}")
        print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📋 {message}")
        print('='*80)
        
    def step(self, message: str):
        """Log a test step"""
        self.step_count += 1
        print(f"\n📍 STEP {self.step_count}: {message}")
        print("-" * 60)
        
    def info(self, message: str):
        """Log info message"""
        print(f"ℹ️  {message}")
        
    def success(self, message: str):
        """Log success message"""
        print(f"✅ {message}")
        
    def warning(self, message: str):
        """Log warning message"""
        print(f"⚠️  {message}")
        
    def error(self, message: str):
        """Log error message"""
        print(f"❌ {message}")
        
    def data(self, label: str, data: Any):
        """Log structured data"""
        print(f"📊 {label}:")
        if isinstance(data, dict):
            for key, value in data.items():
                print(f"   {key}: {value}")
        elif isinstance(data, list):
            for i, item in enumerate(data[:5]):  # Show first 5 items
                print(f"   {i+1}. {item}")
            if len(data) > 5:
                print(f"   ... and {len(data) - 5} more items")
        else:
            print(f"   {data}")
            
    def result(self, success: bool, message: str, details: Dict = None):
        """Log final test result"""
        duration = time.time() - self.start_time
        
        print(f"\n{'='*80}")
        if success:
            print(f"✅ TEST PASSED: {self.test_name}")
        else:
            print(f"❌ TEST FAILED: {self.test_name}")
            
        print(f"⏱️  Duration: {duration:.2f}s")
        print(f"📝 {message}")
        
        if details:
            print(f"\n📊 Test Details:")
            self.data("Results", details)
            
        print('='*80)
        
        return success


@contextmanager 
def test_timer(logger: TestLogger, operation: str):
    """Time a test operation"""
    logger.info(f"Starting: {operation}")
    start_time = time.time()
    
    try:
        yield
        duration = time.time() - start_time
        logger.success(f"Completed: {operation} ({duration:.2f}s)")
        return duration
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Failed: {operation} ({duration:.2f}s) - {e}")
        raise


@contextmanager 
def operation_timer(logger: TestLogger, operation: str):
    """Time a test operation"""
    logger.info(f"Starting: {operation}")
    start_time = time.time()
    
    try:
        yield
        duration = time.time() - start_time
        logger.success(f"Completed: {operation} ({duration:.2f}s)")
        return duration
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Failed: {operation} ({duration:.2f}s) - {e}")
        raise


class LatencyTracker:
    """Track latency metrics for test operations"""
    
    def __init__(self):
        self.operations = {}
        self.total_start_time = time.time()
    
    def add_operation(self, operation_name: str, duration: float, input_size: int = None):
        """Add an operation timing"""
        self.operations[operation_name] = {
            'duration': duration,
            'input_size': input_size,
            'latency_per_input': duration / input_size if input_size and input_size > 0 else None
        }
    
    def get_summary(self) -> Dict:
        """Get latency summary"""
        total_duration = time.time() - self.total_start_time
        return {
            'total_duration': total_duration,
            'operations': self.operations,
            'operation_count': len(self.operations)
        }
    
    def print_summary(self, logger: TestLogger):
        """Print concise latency summary (max 3 lines)"""
        summary = self.get_summary()
        logger.info(f"📊 LATENCY: Total {summary['total_duration']:.1f}s | Operations: {summary['operation_count']}")
        
        # Show key operation with per-input latency
        for op_name, metrics in summary['operations'].items():
            if metrics['latency_per_input'] and metrics['input_size'] > 1:
                logger.info(f"   {op_name}: {metrics['duration']:.1f}s ({metrics['latency_per_input']:.3f}s per input)")
                break


def validate_result(result: Dict, required_fields: List[str], logger: TestLogger) -> bool:
    """Validate a result dictionary has required fields"""
    missing_fields = []
    
    for field in required_fields:
        if field not in result:
            missing_fields.append(field)
            
    if missing_fields:
        logger.error(f"Missing required fields: {missing_fields}")
        return False
        
    logger.success(f"All required fields present: {required_fields}")
    return True


def print_brand_info(brand_info, logger: TestLogger):
    """Print brand information for testing"""
    logger.info(f"Testing Brand: {brand_info.name}")
    logger.info(f"Homepage: {brand_info.homepage_url}")
    if brand_info.expected_categories:
        logger.info(f"Expected Categories: {brand_info.expected_categories}")
    if brand_info.notes:
        logger.info(f"Notes: {brand_info.notes}")


def print_category_info(category_info, logger: TestLogger):
    """Print category information for testing"""
    logger.info(f"Testing Category: {category_info.name}")
    logger.info(f"URL: {category_info.url}")
    if category_info.expected_products:
        logger.info(f"Expected Products: {category_info.expected_products}")
    if category_info.has_pagination is not None:
        logger.info(f"Has Pagination: {category_info.has_pagination}")
    if category_info.notes:
        logger.info(f"Notes: {category_info.notes}")


def assert_with_logging(condition: bool, message: str, logger: TestLogger) -> bool:
    """Assert with logging"""
    if condition:
        logger.success(f"✓ {message}")
        return True
    else:
        logger.error(f"✗ {message}")
        return False


# Common JSON loading functions for all tests
def load_brands_json() -> Optional[Dict]:
    """Load brands.json file"""
    brands_json_path = os.path.join(os.path.dirname(__file__), "brands.json")
    
    try:
        with open(brands_json_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def load_brand_from_json(brand_key: str) -> Optional[Dict]:
    """Load brand data from brands.json file"""
    brands_data = load_brands_json()
    if not brands_data:
        return None
    return brands_data.get(brand_key)


def get_test_data_for_brand(brand_key: str, test_type: str = None) -> Optional[Dict]:
    """
    Get test data for a specific brand and optionally test type.
    
    Args:
        brand_key: Brand identifier
        test_type: Type of test data ('scroll_test', 'pagination_test', etc.) 
                  If None, returns entire brand data
        
    Returns:
        Tuple of (test_url, expected_value) if test_type specified, 
        or entire brand data dict if test_type is None
    """
    brand_data = load_brand_from_json(brand_key)
    if not brand_data:
        return None
    
    # If no test_type specified, return entire brand data (for test_05)
    if test_type is None:
        return brand_data
    
    # Original behavior for specific test types
    test_data = brand_data.get(test_type)
    if not test_data or len(test_data) < 2:
        return None
    
    return test_data[0], test_data[1]


def get_all_brand_names() -> List[str]:
    """
    Get list of all brand keys from brands.json.
    
    Returns:
        List of all brand keys
    """
    brands_data = load_brands_json()
    if not brands_data:
        return []
    
    return list(brands_data.keys())


def get_brands_with_test_type(test_type: str) -> List[str]:
    """
    Get list of brand keys that have a specific test type.
    
    Args:
        test_type: Type of test data ('scroll_test', 'pagignation_test', etc.)
        
    Returns:
        List of brand keys that have the specified test type
    """
    brands_data = load_brands_json()
    if not brands_data:
        return []
    
    brands_with_test = []
    for brand_key, brand_info in brands_data.items():
        if test_type in brand_info:
            brands_with_test.append(brand_key)
    
    return brands_with_test


def print_test_results_table(results: List[Dict], title: str = "Test Results"):
    """
    Print a formatted results table using rich.
    
    Args:
        results: List of result dictionaries
        title: Table title
    """
    try:
        from rich.table import Table
        from rich.console import Console
        
        console = Console()
        table = Table(title=title)
        
        if not results:
            print(f"No results to display for {title}")
            return
        
        # Add columns based on first result
        first_result = results[0]
        for key in first_result.keys():
            table.add_column(key.replace('_', ' ').title(), justify="center")
        
        # Add rows
        for result in results:
            row_values = []
            for value in result.values():
                if isinstance(value, bool):
                    row_values.append("✅" if value else "❌")
                else:
                    row_values.append(str(value))
            table.add_row(*row_values)
        
        console.print(table)
        
    except ImportError:
        # Fallback to simple print if rich is not available
        print(f"\n{title}:")
        print("-" * 50)
        for result in results:
            print(f"  {result}")
        print("-" * 50)


def parse_run_count_from_args() -> int:
    """Parse -N flag from command line arguments to determine run count"""
    if '-N' in sys.argv:
        try:
            n_index = sys.argv.index('-N')
            if n_index + 1 < len(sys.argv):
                return int(sys.argv[n_index + 1])
        except (ValueError, IndexError):
            pass
    return 1


def run_test_multiple_times(test_function: Callable, *args, **kwargs) -> List[Any]:
    """
    Run a test function multiple times based on -N command line flag.
    
    Args:
        test_function: The test function to run
        *args: Arguments to pass to the test function
        **kwargs: Keyword arguments to pass to the test function
        
    Returns:
        List of results from each test run (single result if run_count=1)
    """
    run_count = parse_run_count_from_args()
    
    if run_count == 1:
        # Single run - return the result directly
        return test_function(*args, **kwargs)
    
    # Multiple runs
    print(f"\n🔁 Running test {run_count} times...")
    print("=" * 60)
    
    results = []
    for i in range(run_count):
        print(f"\n📍 RUN {i + 1}/{run_count}")
        print("-" * 40)
        
        try:
            result = test_function(*args, **kwargs)
            results.append(result)
            print(f"✅ Run {i + 1} completed")
        except Exception as e:
            print(f"❌ Run {i + 1} failed: {e}")
            results.append(None)
    
    # Summary
    print(f"\n📊 MULTI-RUN SUMMARY ({run_count} runs)")
    print("=" * 60)
    successful_runs = sum(1 for r in results if r is not None)
    print(f"✅ Successful: {successful_runs}/{run_count}")
    print(f"❌ Failed: {run_count - successful_runs}/{run_count}")
    
    return results