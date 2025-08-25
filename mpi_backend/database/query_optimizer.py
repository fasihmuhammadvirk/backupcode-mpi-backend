"""
Database Query Optimizer for MPI Backend
Implements proactive optimization strategies to prevent high CPU usage.
"""

import logging
import time
from typing import Dict, Any, List, Optional
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text, Index
from sqlalchemy.orm import sessionmaker, Session, joinedload, selectinload
from sqlalchemy.pool import QueuePool
import psutil

logger = logging.getLogger(__name__)

class QueryOptimizer:
    """Proactive database query optimization to prevent high CPU usage"""
    
    def __init__(self):
        self.query_stats = {
            'total_queries': 0,
            'slow_queries': 0,
            'optimized_queries': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        self.query_cache = {}
        self.max_cache_size = 1000
        self.slow_query_threshold = 1.0  # seconds
        
    def optimize_connection_pool(self, engine):
        """Optimize database connection pool settings"""
        # Reduce pool size to prevent connection overhead
        engine.pool.size = 8  # Reduced from 10
        engine.pool.max_overflow = 3  # Reduced from 5
        engine.pool.timeout = 20  # Reduced from 30
        engine.pool.recycle = 900  # 15 minutes instead of 30
        
        logger.info("Database connection pool optimized for better performance")
        
    def create_performance_indexes(self, engine):
        """Create performance indexes for frequently queried columns"""
        try:
            # Create indexes for common query patterns
            indexes = [
                # Invoice queries
                Index('idx_invoice_date', 'invoices', 'invoice_date'),
                Index('idx_invoice_supplier', 'invoices', 'supplier_id'),
                Index('idx_invoice_status', 'invoices', 'status'),
                Index('idx_invoice_date_supplier', 'invoices', 'invoice_date', 'supplier_id'),
                
                # Invoice items queries
                Index('idx_item_code', 'invoice_items', 'item_code'),
                Index('idx_item_supplier', 'invoice_items', 'supplier_id'),
                Index('idx_item_invoice', 'invoice_items', 'invoice_id'),
                
                # Supplier queries
                Index('idx_supplier_name', 'suppliers', 'name'),
                Index('idx_supplier_active', 'suppliers', 'is_active'),
                
                # Mapping queries
                Index('idx_mapping_item', 'item_mappings', 'item_code'),
                Index('idx_mapping_supplier', 'item_mappings', 'supplier_id'),
            ]
            
            for index in indexes:
                try:
                    index.create(engine)
                    logger.info(f"Created performance index: {index.name}")
                except Exception as e:
                    logger.debug(f"Index {index.name} already exists: {e}")
                    
        except Exception as e:
            logger.error(f"Error creating performance indexes: {e}")
    
    def optimize_query_with_joins(self, session: Session, base_query, join_tables: List[str]):
        """Optimize queries by using JOINs instead of N+1 queries"""
        try:
            # Add eager loading for related tables
            for table in join_tables:
                if table == 'supplier':
                    base_query = base_query.options(joinedload('supplier'))
                elif table == 'invoice_items':
                    base_query = base_query.options(selectinload('invoice_items'))
                elif table == 'mappings':
                    base_query = base_query.options(joinedload('mappings'))
            
            return base_query
            
        except Exception as e:
            logger.error(f"Error optimizing query with joins: {e}")
            return base_query
    
    def batch_process_queries(self, session: Session, operation_func, items: List[Any], batch_size: int = 100):
        """Process queries in batches to reduce database load"""
        try:
            total_processed = 0
            start_time = time.time()
            
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                
                # Process batch in single transaction
                with session.begin():
                    for item in batch:
                        operation_func(session, item)
                
                total_processed += len(batch)
                
                # Log progress
                if total_processed % (batch_size * 5) == 0:
                    elapsed = time.time() - start_time
                    logger.info(f"Batch processing: {total_processed}/{len(items)} items processed in {elapsed:.2f}s")
            
            elapsed = time.time() - start_time
            logger.info(f"Batch processing complete: {total_processed} items in {elapsed:.2f}s")
            
            return total_processed
            
        except Exception as e:
            logger.error(f"Error in batch processing: {e}")
            session.rollback()
            raise
    
    def cache_query_result(self, cache_key: str, result: Any, ttl: int = 3600):
        """Cache query results to reduce database load"""
        try:
            if len(self.query_cache) >= self.max_cache_size:
                # Remove oldest entries
                oldest_keys = sorted(self.query_cache.keys(), key=lambda k: self.query_cache[k]['timestamp'])[:100]
                for key in oldest_keys:
                    del self.query_cache[key]
            
            self.query_cache[cache_key] = {
                'result': result,
                'timestamp': time.time(),
                'ttl': ttl
            }
            
            self.query_stats['cache_hits'] += 1
            
        except Exception as e:
            logger.error(f"Error caching query result: {e}")
    
    def get_cached_result(self, cache_key: str) -> Optional[Any]:
        """Get cached query result if available and not expired"""
        try:
            if cache_key in self.query_cache:
                cached_data = self.query_cache[cache_key]
                
                # Check if cache is expired
                if time.time() - cached_data['timestamp'] < cached_data['ttl']:
                    self.query_stats['cache_hits'] += 1
                    return cached_data['result']
                else:
                    # Remove expired cache
                    del self.query_cache[cache_key]
            
            self.query_stats['cache_misses'] += 1
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached result: {e}")
            return None
    
    def monitor_query_performance(self, query_name: str, execution_time: float):
        """Monitor query performance and log slow queries"""
        self.query_stats['total_queries'] += 1
        
        if execution_time > self.slow_query_threshold:
            self.query_stats['slow_queries'] += 1
            logger.warning(f"Slow query detected: {query_name} took {execution_time:.2f}s")
            
            # Log CPU usage during slow query
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > 80:
                logger.warning(f"High CPU usage ({cpu_percent}%) during slow query: {query_name}")
    
    def get_optimization_stats(self) -> Dict[str, Any]:
        """Get query optimization statistics"""
        return {
            'query_stats': self.query_stats.copy(),
            'cache_size': len(self.query_cache),
            'cache_efficiency': (
                self.query_stats['cache_hits'] / 
                (self.query_stats['cache_hits'] + self.query_stats['cache_misses'])
                if (self.query_stats['cache_hits'] + self.query_stats['cache_misses']) > 0 
                else 0
            ),
            'slow_query_percentage': (
                self.query_stats['slow_queries'] / self.query_stats['total_queries']
                if self.query_stats['total_queries'] > 0 
                else 0
            )
        }
    
    def clear_cache(self):
        """Clear query cache to free memory"""
        try:
            cache_size = len(self.query_cache)
            self.query_cache.clear()
            logger.info(f"Query cache cleared, freed {cache_size} cached items")
        except Exception as e:
            logger.error(f"Error clearing query cache: {e}")

# Global query optimizer instance
query_optimizer = QueryOptimizer()
