"""
Sovereign Rate Limiter - Adaptive Token Bucket with Circuit Breaker
2x Innovation Features:
- Adaptive rate limits (adjusts based on exchange responses)
- Endpoint-aware routing (different limits for different endpoint types)
- Predictive throttling (track response times to predict rate limit hits)
- Circuit breaker (auto-slow on 429 responses)
- Jittered retry (prevents synchronized hammering)
"""

import asyncio
import logging
import time
import random
from enum import Enum, auto
from typing import Dict, Any, Optional, Callable, Awaitable, Tuple
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


class RequestPriority(Enum):
    """Priority levels for API requests."""
    EMERGENCY = 0      # Kill switch, absolute bypass
    CRITICAL = 1       # Order submissions, cancellations
    NORMAL = 2         # Balance queries, position checks
    BACKGROUND = 3     # Historical data, non-essential


class EndpointCategory(Enum):
    """Categories of API endpoints with different rate limits."""
    PUBLIC_MARKET_DATA = "public_market_data"     # Order book, ticker
    PUBLIC_HISTORICAL = "public_historical"       # OHLCV, trades history
    PRIVATE_ORDER = "private_order"               # Submit, cancel orders
    PRIVATE_ACCOUNT = "private_account"           # Balance, positions
    PRIVATE_TRADES = "private_trades"             # Trade history


@dataclass
class RateLimitConfig:
    """Configuration for a rate limiter with adaptive capabilities."""
    base_rate_per_second: float
    bucket_size: int
    min_rate_per_second: float = 1.0
    max_rate_per_second: float = 20.0
    adaptive_enabled: bool = True
    circuit_breaker_threshold: int = 5  # 5 errors in window
    circuit_breaker_window_sec: float = 60.0
    retry_jitter_ms: Tuple[float, float] = (50, 250)  # Random delay range


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()      # Normal operation
    OPEN = auto()        # Too many errors, waiting
    HALF_OPEN = auto()   # Testing if recovered


@dataclass
class EndpointStats:
    """Statistics for an endpoint category."""
    total_requests: int = 0
    error_count: int = 0
    rate_limit_hits: int = 0
    last_error_time: float = 0
    avg_response_time_ms: float = 0
    response_times: deque = field(default_factory=lambda: deque(maxlen=100))
    circuit_state: CircuitBreakerState = CircuitBreakerState.CLOSED
    circuit_open_until: float = 0


class AdaptiveTokenBucket:
    """
    Adaptive token bucket with circuit breaker.
    Adjusts rate based on exchange responses and error patterns.
    """
    
    def __init__(self, category: EndpointCategory, config: RateLimitConfig):
        """
        Initialize adaptive token bucket.

        Args:
            category: Endpoint category
            config: Rate limit configuration
        """
        self.category = category
        self.config = config
        self.current_rate = config.base_rate_per_second
        self._tokens = float(config.bucket_size)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._stats = EndpointStats()
        
        logger.debug(f"AdaptiveTokenBucket initialized for {category.value}: "
                    f"base_rate={config.base_rate_per_second}/s, "
                    f"adaptive={config.adaptive_enabled}")
    
    async def acquire(self, tokens: float = 1.0) -> bool:
        """
        Acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens acquired
        """
        async with self._lock:
            self._refill()
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    async def wait_and_acquire(self, tokens: float = 1.0, timeout: float = None) -> bool:
        """
        Wait until tokens are available and acquire them.

        Args:
            tokens: Number of tokens to acquire
            timeout: Maximum wait time in seconds

        Returns:
            True if acquired, False if timeout
        """
        start_time = time.monotonic()
        
        while True:
            if await self.acquire(tokens):
                return True
            
            if timeout and (time.monotonic() - start_time) >= timeout:
                return False
            
            # Calculate wait time for next token with jitter
            base_wait = 1.0 / max(self.current_rate, 0.1)
            jitter = random.uniform(0, base_wait * 0.3)
            await asyncio.sleep(base_wait + jitter)
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time and current rate."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        if elapsed > 0:
            new_tokens = elapsed * self.current_rate
            self._tokens = min(self.config.bucket_size, self._tokens + new_tokens)
            self._last_refill = now
    
    def record_response(self, success: bool, response_time_ms: float, rate_limited: bool = False) -> None:
        """
        Record API response for adaptive rate adjustment.

        Args:
            success: Whether request succeeded
            response_time_ms: Response time in milliseconds
            rate_limited: Whether request was rate limited (429)
        """
        self._stats.total_requests += 1
        
        # Track response times
        self._stats.response_times.append(response_time_ms)
        self._stats.avg_response_time_ms = sum(self._stats.response_times) / len(self._stats.response_times)
        
        if not success:
            self._stats.error_count += 1
            self._stats.last_error_time = time.monotonic()
        
        if rate_limited:
            self._stats.rate_limit_hits += 1
            self._adjust_rate_down()
        
        # Update circuit breaker
        self._update_circuit_breaker()
        
        # Adjust rate based on response times (predictive)
        if self.config.adaptive_enabled and not rate_limited:
            self._adjust_rate_predictive()
    
    def _adjust_rate_down(self) -> None:
        """Reduce rate limit on 429 response."""
        if not self.config.adaptive_enabled:
            return
        
        # Reduce rate by 30%
        new_rate = self.current_rate * 0.7
        self.current_rate = max(self.config.min_rate_per_second, new_rate)
        logger.warning(f"Rate limit hit for {self.category.value}! Reducing rate to {self.current_rate:.1f}/s")
    
    def _adjust_rate_up(self) -> None:
        """Increase rate limit when performing well."""
        if not self.config.adaptive_enabled:
            return
        
        # Increase rate by 5% (slow recovery)
        new_rate = self.current_rate * 1.05
        self.current_rate = min(self.config.max_rate_per_second, new_rate)
    
    def _adjust_rate_predictive(self) -> None:
        """Predictively adjust rate based on response times."""
        if not self.config.adaptive_enabled or len(self._stats.response_times) < 10:
            return
        
        # If response times are increasing, we might be hitting limits
        recent = list(self._stats.response_times)[-10:]
        trend = recent[-1] - recent[0] if len(recent) > 1 else 0
        
        if trend > 100:  # Response time increased by 100ms
            self._adjust_rate_down()
        elif trend < -50 and self.current_rate < self.config.base_rate_per_second:
            # Response times improving, slowly increase rate
            self._adjust_rate_up()
    
    def _update_circuit_breaker(self) -> None:
        """Update circuit breaker state."""
        now = time.monotonic()
        
        if self._stats.circuit_state == CircuitBreakerState.OPEN:
            if now >= self._stats.circuit_open_until:
                self._stats.circuit_state = CircuitBreakerState.HALF_OPEN
                logger.info(f"Circuit breaker for {self.category.value} moving to HALF_OPEN")
            return
        
        if self._stats.circuit_state == CircuitBreakerState.HALF_OPEN:
            # In half-open, we allow a few requests to test
            return
        
        # Check if we should open circuit
        window_start = now - self.config.circuit_breaker_window_sec
        recent_errors = 0
        
        # Simplified: count errors in last window
        if self._stats.last_error_time > window_start:
            recent_errors = self._stats.error_count
        
        if recent_errors >= self.config.circuit_breaker_threshold:
            self._stats.circuit_state = CircuitBreakerState.OPEN
            self._stats.circuit_open_until = now + 60.0  # Open for 60 seconds
            logger.critical(f"CIRCUIT BREAKER OPEN for {self.category.value} - cooling down for 60s")
    
    def is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        now = time.monotonic()
        if self._stats.circuit_state == CircuitBreakerState.OPEN:
            if now >= self._stats.circuit_open_until:
                self._stats.circuit_state = CircuitBreakerState.HALF_OPEN
                return False
            return True
        return False
    
    def reset_circuit(self) -> None:
        """Manually reset circuit breaker."""
        self._stats.circuit_state = CircuitBreakerState.CLOSED
        self._stats.error_count = 0
        self._stats.rate_limit_hits = 0
        self.current_rate = self.config.base_rate_per_second
        logger.info(f"Circuit breaker for {self.category.value} manually reset")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current bucket statistics."""
        self._refill()
        return {
            "category": self.category.value,
            "current_rate": self.current_rate,
            "tokens_available": self._tokens,
            "bucket_size": self.config.bucket_size,
            "usage_pct": (1 - self._tokens / self.config.bucket_size) * 100 if self.config.bucket_size > 0 else 0,
            "total_requests": self._stats.total_requests,
            "error_count": self._stats.error_count,
            "rate_limit_hits": self._stats.rate_limit_hits,
            "avg_response_time_ms": self._stats.avg_response_time_ms,
            "circuit_state": self._stats.circuit_state.name
        }


class SovereignThrottler:
    """
    Sovereign Rate Limiter - Adaptive Token Bucket with Circuit Breaker.
    
    2x Innovations:
    - Adaptive rate limits (adjusts based on exchange 429 responses)
    - Predictive throttling (response time trends predict rate limit hits)
    - Circuit breaker (auto-slow on repeated errors)
    - Endpoint-aware routing (different limits for different endpoint types)
    - Jittered retry (prevents synchronized hammering)
    - Priority queuing with emergency bypass
    """
    
    def __init__(self):
        """Initialize sovereign throttler."""
        # Configuration for different endpoint categories
        self._configs = {
            EndpointCategory.PUBLIC_MARKET_DATA: RateLimitConfig(
                base_rate_per_second=15.0,
                bucket_size=30,
                min_rate_per_second=5.0,
                max_rate_per_second=20.0
            ),
            EndpointCategory.PUBLIC_HISTORICAL: RateLimitConfig(
                base_rate_per_second=10.0,
                bucket_size=20,
                min_rate_per_second=3.0,
                max_rate_per_second=15.0
            ),
            EndpointCategory.PRIVATE_ORDER: RateLimitConfig(
                base_rate_per_second=6.0,
                bucket_size=12,
                min_rate_per_second=2.0,
                max_rate_per_second=8.0
            ),
            EndpointCategory.PRIVATE_ACCOUNT: RateLimitConfig(
                base_rate_per_second=6.0,
                bucket_size=12,
                min_rate_per_second=2.0,
                max_rate_per_second=8.0
            ),
            EndpointCategory.PRIVATE_TRADES: RateLimitConfig(
                base_rate_per_second=4.0,
                bucket_size=8,
                min_rate_per_second=1.0,
                max_rate_per_second=6.0
            )
        }
        
        # Adaptive token buckets for each category
        self._buckets: Dict[EndpointCategory, AdaptiveTokenBucket] = {
            cat: AdaptiveTokenBucket(cat, cfg) 
            for cat, cfg in self._configs.items()
        }
        
        # Priority queues for each category
        self._queues: Dict[EndpointCategory, deque] = {
            cat: deque() for cat in EndpointCategory
        }
        
        # Processing tasks
        self._processor_tasks: Dict[EndpointCategory, asyncio.Task] = {}
        self._running = False
        
        # Statistics
        self._stats_lock = asyncio.Lock()
        self._total_requests = 0
        self._emergency_bypass = 0
        self._circuit_open_count = 0
        
        logger.info("SovereignThrottler initialized (2x Innovation)")
        for cat, cfg in self._configs.items():
            logger.info(f"  {cat.value}: {cfg.base_rate_per_second}/s (adaptive {cfg.min_rate_per_second}-{cfg.max_rate_per_second}/s)")
    
    # ============================================
    # PUBLIC API
    # ============================================
    
    async def execute(
        self,
        func: Callable,
        *args,
        category: EndpointCategory = EndpointCategory.PUBLIC_MARKET_DATA,
        priority: RequestPriority = RequestPriority.NORMAL,
        timeout: float = 30.0,
        retry_on_rate_limit: bool = True,
        max_retries: int = 3,
        **kwargs
    ) -> Any:
        """
        Execute an API request with adaptive rate limiting.

        Args:
            func: Async function to execute
            *args: Function arguments
            category: Endpoint category
            priority: Request priority (EMERGENCY bypasses throttling)
            timeout: Request timeout in seconds
            retry_on_rate_limit: Whether to retry on 429
            max_retries: Maximum retries on rate limit
            **kwargs: Function keyword arguments

        Returns:
            Result from the function

        Raises:
            TimeoutError: If request times out
            Exception: If function raises exception
        """
        # Emergency bypass: no throttling, immediate execution
        if priority == RequestPriority.EMERGENCY:
            self._emergency_bypass += 1
            self._total_requests += 1
            logger.warning(f"EMERGENCY BYPASS: Executing {func.__name__} immediately")
            return await self._execute_with_timeout(func, timeout, *args, **kwargs)
        
        # Check circuit breaker
        bucket = self._buckets[category]
        if bucket.is_circuit_open():
            self._circuit_open_count += 1
            logger.warning(f"Circuit breaker open for {category.value}, waiting 60s")
            await asyncio.sleep(5)  # Check again after 5 seconds
            # Recursive call to retry after circuit open
            return await self.execute(
                func, *args, category=category, priority=priority,
                timeout=timeout, retry_on_rate_limit=retry_on_rate_limit,
                max_retries=max_retries, **kwargs
            )
        
        # Acquire tokens with retry
        acquired = False
        retry_count = 0
        
        while not acquired and retry_count <= max_retries:
            acquired = await bucket.wait_and_acquire(1.0, timeout=timeout)
            
            if not acquired:
                if retry_count < max_retries:
                    retry_count += 1
                    wait_time = random.uniform(0.5, 2.0) * retry_count
                    logger.warning(f"Rate limit wait timeout for {category.value}, retry {retry_count}/{max_retries} in {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                else:
                    raise TimeoutError(f"Rate limit wait timeout for {category.value} after {max_retries} retries")
        
        # Execute request
        start_time = time.monotonic()
        success = True
        rate_limited = False
        result = None
        
        try:
            result = await self._execute_with_timeout(func, timeout, *args, **kwargs)
        except Exception as e:
            success = False
            # Check if this was a rate limit error
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                rate_limited = True
                logger.warning(f"Rate limit hit for {category.value}: {e}")
            raise
        finally:
            response_time_ms = (time.monotonic() - start_time) * 1000
            bucket.record_response(success, response_time_ms, rate_limited)
            self._total_requests += 1
        
        return result
    
    async def _execute_with_timeout(self, func: Callable, timeout: float, *args, **kwargs) -> Any:
        """Execute function with timeout."""
        try:
            return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request to {func.__name__} timed out after {timeout}s")
    
    # ============================================
    # UTILITY METHODS
    # ============================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get throttler statistics."""
        return {
            "total_requests": self._total_requests,
            "emergency_bypass": self._emergency_bypass,
            "circuit_open_count": self._circuit_open_count,
            "buckets": {cat.value: bucket.get_stats() for cat, bucket in self._buckets.items()}
        }
    
    def reset_circuit(self, category: Optional[EndpointCategory] = None) -> None:
        """
        Reset circuit breaker for a category or all categories.

        Args:
            category: Category to reset (None for all)
        """
        if category:
            self._buckets[category].reset_circuit()
        else:
            for bucket in self._buckets.values():
                bucket.reset_circuit()
        logger.info("Circuit breaker(s) reset")
    
    async def start(self) -> None:
        """Start throttler (currently no background tasks)."""
        self._running = True
        logger.info("SovereignThrottler started")
    
    async def stop(self) -> None:
        """Stop throttler."""
        self._running = False
        logger.info("SovereignThrottler stopped")


# ============================================
# FACTORY FUNCTION
# ============================================

def create_throttler() -> SovereignThrottler:
    """
    Create a configured sovereign throttler.

    Returns:
        Configured SovereignThrottler instance
    """
    return SovereignThrottler()