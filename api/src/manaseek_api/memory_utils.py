"""
Memory reporting utilities for tracking memory usage of API components.
"""
import logging
import os
import sys
import psutil
from typing import Optional, Dict, Any

# Use the API logger since memory reports are part of API startup
logger = logging.getLogger("manaseek_api.api")


def _get_object_size(obj, seen=None):
    """
    Recursively calculate the size of an object in bytes.
    Handles common data structures including numpy arrays and sparse matrices.
    """
    if seen is None:
        seen = set()
    
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    
    seen.add(obj_id)
    size = sys.getsizeof(obj)
    
    try:
        # Handle numpy arrays
        if hasattr(obj, 'nbytes'):
            return obj.nbytes
        
        # Handle scipy sparse matrices
        if hasattr(obj, 'data') and hasattr(obj, 'indices') and hasattr(obj, 'indptr'):
            # CSR or CSC sparse matrix
            size = sys.getsizeof(obj.data) + sys.getsizeof(obj.indices) + sys.getsizeof(obj.indptr) + sys.getsizeof(obj)
            return size
        
        # Handle dictionaries
        if isinstance(obj, dict):
            size += sum(_get_object_size(k, seen) + _get_object_size(v, seen) for k, v in obj.items())
        
        # Handle lists and tuples
        elif isinstance(obj, (list, tuple)):
            size += sum(_get_object_size(item, seen) for item in obj)
        
        # Handle sets
        elif isinstance(obj, set):
            size += sum(_get_object_size(item, seen) for item in obj)
        
        # Handle objects with __dict__
        elif hasattr(obj, '__dict__'):
            size += _get_object_size(obj.__dict__, seen)
        
        # Handle objects with __slots__
        elif hasattr(obj, '__slots__'):
            for slot in obj.__slots__:
                if hasattr(obj, slot):
                    size += _get_object_size(getattr(obj, slot), seen)
    
    except (RecursionError, TypeError):
        pass
    
    return size


def _format_bytes(bytes_value: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} TB"


def _log_resolver_memory(resolver_obj, resolver_name: str):
    """Log detailed memory breakdown for a resolver object."""
    if resolver_obj is None:
        logger.info(f"  {resolver_name}: Not initialized")
        return
    
    breakdown = {}
    total = 0
    
    # Get memory for each attribute
    if hasattr(resolver_obj, 'card_ids'):
        size = _get_object_size(resolver_obj.card_ids)
        breakdown['card_ids'] = size
        total += size
    
    if hasattr(resolver_obj, 'card_names'):
        size = _get_object_size(resolver_obj.card_names)
        breakdown['card_names'] = size
        total += size
    
    if hasattr(resolver_obj, 'card_ranks'):
        size = _get_object_size(resolver_obj.card_ranks)
        breakdown['card_ranks'] = size
        total += size
    
    if hasattr(resolver_obj, 'card_rank_scores'):
        size = _get_object_size(resolver_obj.card_rank_scores)
        breakdown['card_rank_scores'] = size
        total += size
    
    if hasattr(resolver_obj, 'vectorizer'):
        size = _get_object_size(resolver_obj.vectorizer)
        breakdown['vectorizer'] = size
        total += size
    
    # Get matrix memory (name_matrix or oracle_matrix)
    matrix_attr = 'name_matrix' if hasattr(resolver_obj, 'name_matrix') else 'oracle_matrix'
    if hasattr(resolver_obj, matrix_attr):
        matrix = getattr(resolver_obj, matrix_attr)
        size = _get_object_size(matrix)
        breakdown[matrix_attr] = size
        total += size
    
    # Oracle resolver specific
    if hasattr(resolver_obj, 'oracle_texts'):
        size = _get_object_size(resolver_obj.oracle_texts)
        breakdown['oracle_texts'] = size
        total += size
    
    # Get cache memory if available
    cache_info = None
    if hasattr(resolver_obj, '_calculate_matches'):
        cache_info = resolver_obj._calculate_matches.cache_info()
    elif hasattr(resolver_obj, '_calculate_similarities'):
        cache_info = resolver_obj._calculate_similarities.cache_info()
    
    logger.info(f"  {resolver_name}:")
    logger.info(f"    Total: {_format_bytes(total)}")
    for key, size in sorted(breakdown.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"      {key}: {_format_bytes(size)}")
    
    if cache_info:
        logger.info(f"    Cache: {cache_info.currsize}/{cache_info.maxsize} entries "
                   f"({cache_info.hits} hits, {cache_info.misses} misses)")


def log_memory_report(
    resolver: Optional[Any],
    oracle_resolver: Optional[Any],
    cards_by_id: Dict[str, Dict[str, Any]]
):
    """
    Log a comprehensive memory usage report to the terminal.
    
    Args:
        resolver: The CardNameResolver instance
        oracle_resolver: The CardOracleResolver instance
        cards_by_id: Dictionary mapping card IDs to card data
    """
    process = psutil.Process(os.getpid())
    process_memory = process.memory_info()
    process_memory_mb = process_memory.rss / (1024 * 1024)
    process_memory_percent = process.memory_percent()
    
    system_memory = psutil.virtual_memory()
    system_memory_total_mb = system_memory.total / (1024 * 1024)
    system_memory_available_mb = system_memory.available / (1024 * 1024)
    system_memory_percent = system_memory.percent
    
    logger.info("=" * 60)
    logger.info("MEMORY USAGE REPORT")
    logger.info("=" * 60)
    logger.info(f"Process Memory: {_format_bytes(process_memory.rss)} ({process_memory_percent:.1f}% of system)")
    logger.info(f"System Memory: {_format_bytes(system_memory.total)} total, "
               f"{_format_bytes(system_memory.available)} available ({system_memory_percent:.1f}% used)")
    logger.info("")
    logger.info("Component Breakdown:")
    
    # Memory for cards_by_id dictionary
    cards_by_id_size = _get_object_size(cards_by_id)
    logger.info(f"  cards_by_id dictionary:")
    logger.info(f"    Total: {_format_bytes(cards_by_id_size)}")
    logger.info(f"    Card count: {len(cards_by_id):,}")
    logger.info(f"    Average per card: {_format_bytes(cards_by_id_size / len(cards_by_id) if cards_by_id else 0)}")
    
    # Memory for name resolver
    logger.info("")
    _log_resolver_memory(resolver, "name_resolver")
    
    # Memory for oracle resolver
    logger.info("")
    _log_resolver_memory(oracle_resolver, "oracle_resolver")
    
    # Calculate other memory (process memory minus tracked components)
    tracked_memory = (
        cards_by_id_size +
        (_get_object_size(resolver) if resolver else 0) +
        (_get_object_size(oracle_resolver) if oracle_resolver else 0)
    )
    other_memory = process_memory.rss - tracked_memory
    logger.info("")
    logger.info(f"  Other (Python interpreter, FastAPI, dependencies):")
    logger.info(f"    Estimated: {_format_bytes(max(0, other_memory))}")
    
    logger.info("=" * 60)

