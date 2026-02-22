"""
lambda_debug_toolkit.py - Practical debugging utilities for AWS Lambda

Real-world debugging helpers that actually work in production.

Author: Agnibes Banerjee
License: MIT
"""

import time
import functools
import json
import uuid
import os
import traceback
import random
from typing import Any, Callable, Optional


class LambdaDebugger:
    """
    Debugging toolkit for AWS Lambda functions.
    
    Usage:
        from lambda_debug_toolkit import debugger
        
        @debugger.timeit
        def my_function():
            pass
    """
    
    def __init__(self):
        self.debug_enabled = os.environ.get('DEBUG', 'false').lower() == 'true'
        self.sample_rate = float(os.environ.get('LOG_SAMPLE_RATE', '0.01'))
    
    def timeit(self, func: Callable) -> Callable:
        """
        Decorator to time function execution and log results.
        
        Example:
            @debugger.timeit
            def slow_function():
                time.sleep(1)
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                
                self.log('function_timing', {
                    'function': func.__name__,
                    'duration_ms': round(duration_ms, 2),
                    'status': 'success'
                })
                
                return result
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                
                self.log('function_timing', {
                    'function': func.__name__,
                    'duration_ms': round(duration_ms, 2),
                    'status': 'error',
                    'error': str(e)
                })
                raise
        
        return wrapper
    
    def log(self, event_type: str, data: dict):
        """
        Structured JSON logging.
        
        Example:
            debugger.log('user_processed', {
                'user_id': '123',
                'items_count': 5
            })
        """
        log_entry = {
            'event': event_type,
            'timestamp': time.time(),
            **data
        }
        print(json.dumps(log_entry))
    
    def should_log(self, custom_rate: Optional[float] = None) -> bool:
        """
        Sampling logic for high-volume functions.
        
        Example:
            if debugger.should_log():
                debugger.log('detailed_info', {...})
        """
        rate = custom_rate if custom_rate is not None else self.sample_rate
        return random.random() < rate
    
    def log_error(self, error: Exception, context: dict = None):
        """
        Log errors with full context.
        
        Example:
            try:
                risky_operation()
            except Exception as e:
                debugger.log_error(e, {'user_id': user_id})
                raise
        """
        self.log('error', {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
            'context': context or {}
        })
    
    def log_if_debug(self, event_type: str, data: dict):
        """
        Log only if DEBUG environment variable is true.
        
        Example:
            debugger.log_if_debug('detailed_debug', {
                'full_event': event
            })
        """
        if self.debug_enabled:
            self.log(event_type, data)


# Global instance
debugger = LambdaDebugger()


class CorrelationIDMiddleware:
    """
    Middleware to track requests across multiple Lambdas.
    
    Usage:
        from lambda_debug_toolkit import correlation
        
        def lambda_handler(event, context):
            corr_id = correlation.get_or_create(event)
            # Your code here
            return correlation.add_to_response(response, corr_id)
    """
    
    @staticmethod
    def get_or_create(event: dict) -> str:
        """Extract or generate correlation ID."""
        return event.get('correlation_id') or str(uuid.uuid4())
    
    @staticmethod
    def add_to_response(response: dict, correlation_id: str) -> dict:
        """Add correlation ID to response."""
        if 'headers' not in response:
            response['headers'] = {}
        response['headers']['X-Correlation-ID'] = correlation_id
        return response
    
    @staticmethod
    def add_to_next_lambda_payload(payload: dict, correlation_id: str) -> dict:
        """Add correlation ID when invoking next Lambda."""
        payload['correlation_id'] = correlation_id
        return payload


# Global instance
correlation = CorrelationIDMiddleware()


def lambda_debug_wrapper(handler: Callable) -> Callable:
    """
    Wrap your Lambda handler with debugging utilities.
    
    Provides:
    - Automatic timing
    - Correlation ID tracking
    - Structured error logging
    - Debug mode support
    
    Usage:
        from lambda_debug_toolkit import lambda_debug_wrapper
        
        @lambda_debug_wrapper
        def lambda_handler(event, context):
            # Your code here
            return {'statusCode': 200}
    """
    @functools.wraps(handler)
    def wrapper(event, context):
        # Get or create correlation ID
        corr_id = correlation.get_or_create(event)
        
        # Log request start
        debugger.log('request_start', {
            'correlation_id': corr_id,
            'request_id': context.request_id,
            'function_name': context.function_name
        })
        
        # Log full event if debug mode
        debugger.log_if_debug('full_event', {
            'correlation_id': corr_id,
            'event': event
        })
        
        start_time = time.time()
        
        try:
            # Execute handler
            result = handler(event, context)
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Log success
            debugger.log('request_end', {
                'correlation_id': corr_id,
                'duration_ms': round(duration_ms, 2),
                'status': 'success',
                'memory_used_mb': context.memory_limit_in_mb,
                'time_remaining_ms': context.get_remaining_time_in_millis()
            })
            
            # Add correlation ID to response
            if isinstance(result, dict):
                result = correlation.add_to_response(result, corr_id)
            
            return result
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            # Log error
            debugger.log_error(e, {
                'correlation_id': corr_id,
                'request_id': context.request_id,
                'duration_ms': round(duration_ms, 2)
            })
            
            raise
    
    return wrapper


# Example usage
if __name__ == '__main__':
    """
    Example Lambda function using the debug toolkit.
    """
    
    import boto3
    
    dynamodb = boto3.resource('dynamodb')
    
    @lambda_debug_wrapper
    def lambda_handler(event, context):
        """Example Lambda with full debugging."""
        
        user_id = event.get('user_id')
        
        if not user_id:
            raise ValueError("user_id is required")
        
        # This will be timed automatically
        data = get_user_data(user_id)
        
        # Sample logging for high volume
        if debugger.should_log(0.1):  # 10% sample
            debugger.log('user_data_fetched', {
                'user_id': user_id,
                'data_size': len(str(data))
            })
        
        result = process_data(data)
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
    
    @debugger.timeit
    def get_user_data(user_id: str) -> dict:
        """Fetch user data - automatically timed."""
        table = dynamodb.Table('users')
        response = table.get_item(Key={'user_id': user_id})
        return response.get('Item', {})
    
    @debugger.timeit
    def process_data(data: dict) -> dict:
        """Process data - automatically timed."""
        # Simulate processing
        time.sleep(0.1)
        return {'processed': True, 'items': len(data)}
    
    # Test locally
    test_event = {
        'user_id': 'test-123'
    }
    
    class MockContext:
        request_id = 'local-test'
        function_name = 'test-function'
        memory_limit_in_mb = 128
        
        def get_remaining_time_in_millis(self):
            return 3000
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))
