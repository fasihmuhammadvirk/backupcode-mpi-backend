"""
Request Processing Optimizer for MPI Backend
Implements proactive optimization strategies to prevent high CPU usage.
"""

import logging
import time
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import Request, Response
import psutil

logger = logging.getLogger(__name__)

class RequestOptimizer:
    """Proactive request processing optimization to prevent high CPU usage"""
    
    def __init__(self):
        self.request_stats = {
            'total_requests': 0,
            'optimized_requests': 0,
            'batched_requests': 0,
            'cached_responses': 0,
            'slow_requests': 0
        }
        self.response_cache = {}
        self.max_cache_size = 500
        self.slow_request_threshold = 2.0  # seconds
        
    async def optimize_request_processing(self, request: Request, call_next):
        """Optimize request processing based on system resources"""
        try:
            start_time = time.time()
            
            # Check system resources before processing
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent
            
            # Apply optimizations based on resource usage
            if cpu_percent > 80 or memory_percent > 80:
                # High resource usage - enable aggressive optimizations
                await self._enable_aggressive_optimizations(request)
                logger.info(f"High resource usage detected - CPU: {cpu_percent}%, Memory: {memory_percent}% - Enabling aggressive optimizations")
                
            elif cpu_percent > 60 or memory_percent > 60:
                # Moderate resource usage - enable moderate optimizations
                await self._enable_moderate_optimizations(request)
                logger.info(f"Moderate resource usage detected - CPU: {cpu_percent}%, Memory: {memory_percent}% - Enabling moderate optimizations")
            
            # Process request
            response = await call_next(request)
            
            # Record request statistics
            execution_time = time.time() - start_time
            self._record_request_stats(request, execution_time)
            
            # Apply response optimizations
            response = await self._optimize_response(response, request)
            
            return response
            
        except Exception as e:
            logger.error(f"Error in request optimization: {e}")
            # Fallback to normal processing
            return await call_next(request)
    
    async def _enable_aggressive_optimizations(self, request: Request):
        """Enable aggressive optimizations during high resource usage"""
        try:
            # Add optimization headers
            request.state.aggressive_optimization = True
            request.state.cache_responses = True
            request.state.batch_processing = True
            
            # Log optimization mode
            logger.info(f"Enabled aggressive optimizations for {request.method} {request.url.path}")
            
        except Exception as e:
            logger.error(f"Error enabling aggressive optimizations: {e}")
    
    async def _enable_moderate_optimizations(self, request: Request):
        """Enable moderate optimizations during moderate resource usage"""
        try:
            # Add optimization headers
            request.state.moderate_optimization = True
            request.state.cache_responses = True
            request.state.batch_processing = False
            
            # Log optimization mode
            logger.info(f"Enabled moderate optimizations for {request.method} {request.url.path}")
            
        except Exception as e:
            logger.error(f"Error enabling moderate optimizations: {e}")
    
    def _record_request_stats(self, request: Request, execution_time: float):
        """Record request statistics for optimization analysis"""
        try:
            self.request_stats['total_requests'] += 1
            
            if execution_time > self.slow_request_threshold:
                self.request_stats['slow_requests'] += 1
                logger.warning(f"Slow request detected: {request.method} {request.url.path} took {execution_time:.2f}s")
            
            # Log CPU usage during slow requests
            if execution_time > self.slow_request_threshold:
                cpu_percent = psutil.cpu_percent(interval=0.1)
                if cpu_percent > 80:
                    logger.warning(f"High CPU usage ({cpu_percent}%) during slow request: {request.method} {request.url.path}")
                    
        except Exception as e:
            logger.error(f"Error recording request stats: {e}")
    
    async def _optimize_response(self, response: Response, request: Request):
        """Apply response optimizations based on request state"""
        try:
            # Check if caching is enabled
            if hasattr(request.state, 'cache_responses') and request.state.cache_responses:
                # Cache response for future requests
                cache_key = self._generate_cache_key(request)
                self._cache_response(cache_key, response)
                self.request_stats['cached_responses'] += 1
            
            # Add optimization headers
            response.headers["X-Optimization-Enabled"] = "true"
            
            if hasattr(request.state, 'aggressive_optimization'):
                response.headers["X-Optimization-Level"] = "aggressive"
            elif hasattr(request.state, 'moderate_optimization'):
                response.headers["X-Optimization-Level"] = "moderate"
            else:
                response.headers["X-Optimization-Level"] = "normal"
            
            return response
            
        except Exception as e:
            logger.error(f"Error optimizing response: {e}")
            return response
    
    def _generate_cache_key(self, request: Request) -> str:
        """Generate cache key for request"""
        try:
            # Create cache key based on method, path, and query parameters
            cache_key = f"{request.method}:{request.url.path}"
            
            # Add query parameters if present
            if request.query_params:
                query_string = "&".join([f"{k}={v}" for k, v in request.query_params.items()])
                cache_key += f"?{query_string}"
            
            return cache_key
            
        except Exception as e:
            logger.error(f"Error generating cache key: {e}")
            return str(hash(request))
    
    def _cache_response(self, cache_key: str, response: Response):
        """Cache response for future requests"""
        try:
            if len(self.response_cache) >= self.max_cache_size:
                # Remove oldest entries
                oldest_keys = sorted(self.response_cache.keys(), key=lambda k: self.response_cache[k]['timestamp'])[:50]
                for key in oldest_keys:
                    del self.response_cache[key]
            
            # Cache response data
            self.response_cache[cache_key] = {
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'body': getattr(response, 'body', b''),
                'timestamp': time.time(),
                'ttl': 300  # 5 minutes cache
            }
            
        except Exception as e:
            logger.error(f"Error caching response: {e}")
    
    def get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached response if available and not expired"""
        try:
            if cache_key in self.response_cache:
                cached_data = self.response_cache[cache_key]
                
                # Check if cache is expired
                if time.time() - cached_data['timestamp'] < cached_data['ttl']:
                    return cached_data
                else:
                    # Remove expired cache
                    del self.response_cache[cache_key]
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached response: {e}")
            return None
    
    async def batch_process_requests(self, requests: List[Request], batch_operation_func):
        """Process multiple requests in a batch to reduce overhead"""
        try:
            if not requests:
                return []
            
            start_time = time.time()
            batch_size = len(requests)
            
            # Process requests in batch
            results = await batch_operation_func(requests)
            
            # Record batch processing statistics
            execution_time = time.time() - start_time
            self.request_stats['batched_requests'] += batch_size
            self.request_stats['optimized_requests'] += batch_size
            
            logger.info(f"Batch processed {batch_size} requests in {execution_time:.2f}s")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in batch processing: {e}")
            return []
    
    def get_request_optimization_stats(self) -> Dict[str, Any]:
        """Get request optimization statistics"""
        try:
            return {
                'request_stats': self.request_stats.copy(),
                'cache_size': len(self.response_cache),
                'cache_efficiency': (
                    self.request_stats['cached_responses'] / 
                    self.request_stats['total_requests']
                    if self.request_stats['total_requests'] > 0 
                    else 0
                ),
                'slow_request_percentage': (
                    self.request_stats['slow_requests'] / self.request_stats['total_requests']
                    if self.request_stats['total_requests'] > 0 
                    else 0
                ),
                'optimization_effectiveness': (
                    self.request_stats['optimized_requests'] / self.request_stats['total_requests']
                    if self.request_stats['total_requests'] > 0 
                    else 0
                )
            }
        except Exception as e:
            logger.error(f"Error getting request optimization stats: {e}")
            return {}
    
    def clear_response_cache(self):
        """Clear response cache to free memory"""
        try:
            cache_size = len(self.response_cache)
            self.response_cache.clear()
            logger.info(f"Response cache cleared, freed {cache_size} cached responses")
        except Exception as e:
            logger.error(f"Error clearing response cache: {e}")

# Global request optimizer instance
request_optimizer = RequestOptimizer()
