from prometheus_client import start_http_server, Gauge, Counter, Histogram
import requests, time, random, datetime, threading
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json
import sys
import os

# Add parent directory to path for database imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from database.db_service import get_db_service, initialize_database

# Enhanced Metrics
cpu_usage = Gauge("service_cpu_usage", "CPU usage percentage", ["service", "pod"])
memory_usage = Gauge("service_memory_usage", "Memory usage percentage", ["service", "pod"])
disk_usage = Gauge("service_disk_usage", "Disk usage percentage", ["service", "pod"])
network_latency = Gauge("service_network_latency_ms", "Network latency in milliseconds", ["service", "target"])
request_rate = Gauge("service_request_rate", "Requests per second", ["service", "endpoint"])
error_rate = Gauge("service_error_rate", "Error rate percentage", ["service", "error_type"])
response_time = Histogram("service_response_time_seconds", "Response time in seconds", ["service", "endpoint"])
database_connections = Gauge("service_db_connections", "Active database connections", ["service", "db_name"])
queue_depth = Gauge("service_queue_depth", "Message queue depth", ["service", "queue_name"])
gc_time = Gauge("service_gc_time_ms", "Garbage collection time in milliseconds", ["service", "gc_type"])

# Loki endpoint (updated for local execution)
LOKI_URL = "http://localhost:3100/loki/api/v1/push"

class IncidentType(Enum):
    NORMAL = "normal"
    MEMORY_LEAK = "memory_leak"
    CPU_SPIKE = "cpu_spike"
    DATABASE_SLOW = "database_slow"
    NETWORK_LATENCY = "network_latency"
    DISK_FULL = "disk_full"
    CONNECTION_LEAK = "connection_leak"
    QUEUE_BACKLOG = "queue_backlog"
    GC_PRESSURE = "gc_pressure"
    ERROR_BURST = "error_burst"

@dataclass
class Service:
    name: str
    service_type: str
    base_cpu: int = 20
    base_memory: int = 40
    base_connections: int = 10
    pods: List[str] = field(default_factory=list)
    current_incident: Optional[IncidentType] = None
    incident_start_time: Optional[datetime.datetime] = None
    incident_duration: int = 0
    current_incident_id: Optional[str] = None  # Database incident ID

# Define realistic services
SERVICES = [
    Service("user-api", "web", base_cpu=25, base_memory=45, pods=["user-api-1", "user-api-2"]),
    Service("payment-service", "web", base_cpu=30, base_memory=50, pods=["payment-1", "payment-2", "payment-3"]),
    Service("order-processor", "worker", base_cpu=40, base_memory=60, pods=["order-proc-1"]),
    Service("search-engine", "search", base_cpu=35, base_memory=70, pods=["search-1", "search-2"]),
    Service("user-db", "database", base_cpu=50, base_memory=80, base_connections=50, pods=["user-db-1"]),
    Service("redis-cache", "cache", base_cpu=15, base_memory=30, pods=["redis-1", "redis-2"]),
    Service("message-queue", "queue", base_cpu=20, base_memory=35, pods=["mq-1"]),
]

class IncidentGenerator:
    def __init__(self):
        self.active_incidents = {}
        self.total_incidents_generated = 0
        self.max_concurrent_incidents = 3
        self.generation_start_time = datetime.datetime.now()
        
        # Initialize database service
        self.db_service = None
        self.db_enabled = self._initialize_database()
        
        self.incident_patterns = {
            IncidentType.MEMORY_LEAK: {
                "duration_range": (120, 600),  # 2-10 minutes
                "probability": 0.15,
                "services": ["user-api", "payment-service", "order-processor"]
            },
            IncidentType.CPU_SPIKE: {
                "duration_range": (60, 300),   # 1-5 minutes
                "probability": 0.20,
                "services": ["user-api", "payment-service", "search-engine"]
            },
            IncidentType.DATABASE_SLOW: {
                "duration_range": (90, 450),   # 1.5-7.5 minutes
                "probability": 0.12,
                "services": ["user-db"]
            },
            IncidentType.NETWORK_LATENCY: {
                "duration_range": (60, 240),   # 1-4 minutes
                "probability": 0.18,
                "services": ["user-api", "payment-service"]
            },
            IncidentType.DISK_FULL: {
                "duration_range": (180, 900),  # 3-15 minutes
                "probability": 0.08,
                "services": ["user-db", "search-engine"]
            },
            IncidentType.CONNECTION_LEAK: {
                "duration_range": (120, 480),  # 2-8 minutes
                "probability": 0.10,
                "services": ["user-api", "payment-service", "user-db"]
            },
            IncidentType.QUEUE_BACKLOG: {
                "duration_range": (90, 360),   # 1.5-6 minutes
                "probability": 0.14,
                "services": ["message-queue", "order-processor"]
            },
            IncidentType.GC_PRESSURE: {
                "duration_range": (90, 420),   # 1.5-7 minutes
                "probability": 0.16,
                "services": ["user-api", "payment-service", "search-engine"]
            },
            IncidentType.ERROR_BURST: {
                "duration_range": (30, 180),   # 0.5-3 minutes
                "probability": 0.22,
                "services": ["user-api", "payment-service", "order-processor"]
            }
        }
    
    def _initialize_database(self):
        """Initialize database connection"""
        try:
            if initialize_database():
                self.db_service = get_db_service()
                print("Database integration enabled")
                return True
            else:
                print("Database connection failed - continuing with metrics/logs only")
                return False
        except Exception as e:
            print(f"Database initialization error: {e}")
            print("Continuing without database integration")
            return False

    def push_log(self, service, level, message, labels=None, incident_id=None):
        """Enhanced log pushing with better formatting and labels"""
        ts = str(int(time.time() * 1e9))
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        stream_labels = {"service": service, "level": level}
        if labels:
            stream_labels.update(labels)
            
        payload = {
            "streams": [
                {
                    "stream": stream_labels,
                    "values": [[ts, f"{timestamp} {level.upper()} [{service}] {message}"]],
                }
            ]
        }
        
        # Push to Loki
        try:
            requests.post(LOKI_URL, json=payload, timeout=2)
        except Exception as e:
            print(f"Failed to push log to Loki: {e}")
        
        # Store in database
        if self.db_enabled and self.db_service:
            try:
                pod_name = labels.get('pod') if labels else None
                self.db_service.insert_log(
                    service_name=service,
                    pod_name=pod_name,
                    log_level=level.upper(),
                    message=message,
                    incident_id=incident_id,
                    labels=labels
                )
            except Exception as e:
                print(f"Failed to store log in database: {e}")
    
    def store_metric(self, service_name: str, pod_name: str, metric_name: str, 
                    metric_value: float, incident_id: str = None, labels: Dict = None):
        """Store metric data in database"""
        if self.db_enabled and self.db_service:
            try:
                self.db_service.insert_metric(
                    service_name=service_name,
                    pod_name=pod_name,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    incident_id=incident_id,
                    labels=labels
                )
            except Exception as e:
                print(f"Failed to store metric in database: {e}")

    def should_start_incident(self, service: Service) -> Optional[IncidentType]:
        """Enhanced incident starting logic with safety checks"""
        
        # Safety Check 1: Service already has incident
        if service.current_incident is not None:
            return None
        
        # Safety Check 2: Too many concurrent incidents
        active_count = sum(1 for s in SERVICES if s.current_incident is not None)
        if active_count >= self.max_concurrent_incidents:
            return None
            
        # Safety Check 3: Runtime limit (optional - for testing)
        runtime_hours = (datetime.datetime.now() - self.generation_start_time).total_seconds() / 3600
        if runtime_hours > 8:  # Stop after 8 hours
            print("Runtime limit reached - stopping incident generation")
            return None
        
        # Safety Check 4: Total incident limit (optional)
        if self.total_incidents_generated > 50:  # Stop after 50 incidents
            print("Incident limit reached - stopping generation")
            return None
            
        # Original probability check
        for incident_type, config in self.incident_patterns.items():
            if (service.name in config["services"] and 
                random.random() < config["probability"]):
                self.total_incidents_generated += 1
                return incident_type
        return None

    def should_end_incident(self, service: Service) -> bool:
        """Enhanced incident ending with safety timeout"""
        if service.current_incident is None:
            return False
            
        if service.incident_start_time is None:
            # Safety: Force end incident with no start time
            print(f"Force ending incident on {service.name} - no start time")
            return True
            
        elapsed = (datetime.datetime.now() - service.incident_start_time).total_seconds()
        
        # Safety: Force end after 1 hour regardless of duration
        if elapsed > 3600:  # 1 hour
            print(f"Force ending long-running incident on {service.name}")
            return True
            
        return elapsed >= service.incident_duration

    def generate_memory_leak_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate memory leak incident pattern"""
        # Memory grows over time
        memory_growth = min(50, elapsed_time // 5)  # Grows faster for shorter incidents
        memory = min(98, service.base_memory + memory_growth)
        cpu = service.base_cpu + random.randint(5, 15)
        gc_time_ms = random.randint(100, 500)
        
        # Set Prometheus metrics
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        gc_time.labels(service=service.name, gc_type="major").set(gc_time_ms)
        
        # Store metrics in database
        self.store_metric(service.name, pod, "memory_usage", memory, service.current_incident_id)
        self.store_metric(service.name, pod, "cpu_usage", cpu, service.current_incident_id)
        self.store_metric(service.name, pod, "gc_time_ms", gc_time_ms, service.current_incident_id, {"gc_type": "major"})
        
        # Progressive log messages
        if elapsed_time < 30:
            self.push_log(service.name, "warn", f"Memory usage climbing: {memory}%", {"pod": pod}, service.current_incident_id)
        elif elapsed_time < 120:
            self.push_log(service.name, "error", "OutOfMemoryError: Java heap space", {"pod": pod}, service.current_incident_id)
            self.push_log(service.name, "warn", "GC overhead limit exceeded", {"pod": pod}, service.current_incident_id)
        else:
            self.push_log(service.name, "error", "Failed to allocate memory for user session", {"pod": pod}, service.current_incident_id)
            self.push_log(service.name, "error", "Application becoming unresponsive", {"pod": pod}, service.current_incident_id)

    def generate_cpu_spike_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate CPU spike incident pattern"""
        cpu = random.randint(91, 99)
        memory = service.base_memory + random.randint(5, 15)
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        response_time.labels(service=service.name, endpoint="/api/users").observe(random.uniform(2.0, 8.0))
        
        self.push_log(service.name, "warn", f"High CPU usage detected: {cpu}%", {"pod": pod})
        self.push_log(service.name, "error", "Thread pool queue at capacity", {"pod": pod})
        self.push_log(service.name, "warn", "Request processing delays detected", {"pod": pod})

    def generate_database_slow_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate database performance incident"""
        cpu = service.base_cpu + random.randint(10, 30)
        memory = service.base_memory + random.randint(5, 20)
        connections = min(200, service.base_connections + elapsed_time // 3)
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        database_connections.labels(service=service.name, db_name="userdb").set(connections)
        response_time.labels(service=service.name, endpoint="query").observe(random.uniform(5.0, 15.0))
        
        self.push_log(service.name, "warn", f"Slow query detected: SELECT * FROM users (took {random.randint(5, 15)}s)", {"pod": pod})
        self.push_log(service.name, "error", f"Connection pool reaching limit: {connections}/200", {"pod": pod})
        self.push_log(service.name, "warn", "Query timeout threshold exceeded", {"pod": pod})

    def generate_network_latency_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate network latency incident"""
        cpu = service.base_cpu + random.randint(0, 10)
        memory = service.base_memory + random.randint(0, 10)
        latency = random.randint(500, 2000)
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        network_latency.labels(service=service.name, target="external_api").set(latency)
        error_rate.labels(service=service.name, error_type="timeout").set(random.randint(5, 25))
        
        self.push_log(service.name, "error", f"Network timeout to external service (latency: {latency}ms)", {"pod": pod})
        self.push_log(service.name, "warn", "Increased retry attempts for external calls", {"pod": pod})
        self.push_log(service.name, "error", "Circuit breaker opened for external service", {"pod": pod})

    def generate_disk_full_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate disk space incident"""
        disk_percent = min(99, 70 + elapsed_time // 10)
        cpu = service.base_cpu + random.randint(5, 15)
        memory = service.base_memory
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        disk_usage.labels(service=service.name, pod=pod).set(disk_percent)
        
        if disk_percent > 90:
            self.push_log(service.name, "error", f"Disk space critical: {disk_percent}% used", {"pod": pod})
            self.push_log(service.name, "error", "Failed to write log file: No space left on device", {"pod": pod})
        else:
            self.push_log(service.name, "warn", f"Disk space warning: {disk_percent}% used", {"pod": pod})

    def generate_connection_leak_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate connection leak incident"""
        connections = min(150, service.base_connections + elapsed_time // 2)
        cpu = service.base_cpu + random.randint(0, 10)
        memory = service.base_memory + random.randint(10, 25)
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        database_connections.labels(service=service.name, db_name="userdb").set(connections)
        
        self.push_log(service.name, "warn", f"Database connection count increasing: {connections}", {"pod": pod})
        self.push_log(service.name, "error", "Connection pool leak detected", {"pod": pod})
        if connections > 100:
            self.push_log(service.name, "error", "New connection requests being rejected", {"pod": pod})

    def generate_queue_backlog_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate message queue backlog incident"""
        queue_size = min(10000, 100 + elapsed_time * 5)
        cpu = service.base_cpu + random.randint(5, 20)
        memory = service.base_memory + random.randint(5, 15)
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        queue_depth.labels(service=service.name, queue_name="user_events").set(queue_size)
        
        self.push_log(service.name, "warn", f"Queue depth growing: {queue_size} messages", {"pod": pod})
        if queue_size > 1000:
            self.push_log(service.name, "error", "Message processing lag detected", {"pod": pod})
        if queue_size > 5000:
            self.push_log(service.name, "error", "Queue backlog critical - potential data loss", {"pod": pod})

    def generate_gc_pressure_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate garbage collection pressure incident"""
        cpu = service.base_cpu + random.randint(15, 35)
        memory = service.base_memory + random.randint(10, 25)
        gc_duration = random.randint(200, 1000)
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        gc_time.labels(service=service.name, gc_type="major").set(gc_duration)
        response_time.labels(service=service.name, endpoint="/api/users").observe(random.uniform(1.0, 5.0))
        
        self.push_log(service.name, "warn", f"Frequent garbage collection events (duration: {gc_duration}ms)", {"pod": pod})
        self.push_log(service.name, "warn", "Application pause time increasing", {"pod": pod})
        self.push_log(service.name, "error", "GC pressure affecting response times", {"pod": pod})

    def generate_error_burst_incident(self, service: Service, pod: str, elapsed_time: int):
        """Generate error burst incident"""
        cpu = service.base_cpu + random.randint(0, 15)
        memory = service.base_memory + random.randint(0, 15)
        error_percentage = random.randint(10, 50)
        
        cpu_usage.labels(service=service.name, pod=pod).set(cpu)
        memory_usage.labels(service=service.name, pod=pod).set(memory)
        error_rate.labels(service=service.name, error_type="4xx").set(error_percentage)
        
        error_messages = [
            "HTTP 400 Bad Request: Invalid user ID format",
            "HTTP 404 Not Found: User profile not found",
            "HTTP 429 Too Many Requests: Rate limit exceeded",
            "HTTP 503 Service Unavailable: Downstream service error"
        ]
        
        for _ in range(random.randint(1, 3)):
            self.push_log(service.name, "error", random.choice(error_messages), {"pod": pod})

    def generate_normal_operation(self, service: Service, pod: str):
        """Generate normal operation metrics and logs"""
        cpu = service.base_cpu + random.randint(-5, 10)
        memory = service.base_memory + random.randint(-5, 10)
        
        cpu_usage.labels(service=service.name, pod=pod).set(max(1, cpu))
        memory_usage.labels(service=service.name, pod=pod).set(max(1, memory))
        
        if service.service_type == "database":
            database_connections.labels(service=service.name, db_name="userdb").set(service.base_connections + random.randint(-5, 5))
        
        # Occasional normal logs
        if random.random() < 0.05:  # 5% chance - reduced frequency
            normal_messages = [
                "Health check completed successfully",
                f"Processed {random.randint(10, 100)} requests in last minute",
                "Service startup completed",
                "Configuration reloaded"
            ]
            self.push_log(service.name, "info", random.choice(normal_messages), {"pod": pod})

    def generate_incident_data(self, service: Service, pod: str, elapsed_time: int):
        """Centralized incident data generation with error handling"""
        try:
            incident_type = service.current_incident
            
            if incident_type == IncidentType.MEMORY_LEAK:
                self.generate_memory_leak_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.CPU_SPIKE:
                self.generate_cpu_spike_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.DATABASE_SLOW:
                self.generate_database_slow_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.NETWORK_LATENCY:
                self.generate_network_latency_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.DISK_FULL:
                self.generate_disk_full_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.CONNECTION_LEAK:
                self.generate_connection_leak_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.QUEUE_BACKLOG:
                self.generate_queue_backlog_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.GC_PRESSURE:
                self.generate_gc_pressure_incident(service, pod, elapsed_time)
            elif incident_type == IncidentType.ERROR_BURST:
                self.generate_error_burst_incident(service, pod, elapsed_time)
            else:
                print(f"Unknown incident type: {incident_type}")
                
        except Exception as e:
            print(f"Error in incident data generation: {e}")

    def process_service(self, service: Service):
        """Enhanced service processing with error handling"""
        try:
            current_time = datetime.datetime.now()
            
            # Check if we should start a new incident
            if service.current_incident is None:
                new_incident = self.should_start_incident(service)
                if new_incident:
                    service.current_incident = new_incident
                    service.incident_start_time = current_time
                    pattern = self.incident_patterns[new_incident]
                    service.incident_duration = random.randint(*pattern["duration_range"])
                    
                    # Create incident in database
                    if self.db_enabled and self.db_service:
                        try:
                            severity_map = {
                                IncidentType.MEMORY_LEAK: "high",
                                IncidentType.CPU_SPIKE: "high",
                                IncidentType.DATABASE_SLOW: "critical",
                                IncidentType.NETWORK_LATENCY: "medium",
                                IncidentType.DISK_FULL: "critical",
                                IncidentType.CONNECTION_LEAK: "high",
                                IncidentType.QUEUE_BACKLOG: "medium",
                                IncidentType.GC_PRESSURE: "medium",
                                IncidentType.ERROR_BURST: "high"
                            }
                            
                            service.current_incident_id = self.db_service.create_incident(
                                incident_type=new_incident.value,
                                service_name=service.name,
                                severity=severity_map.get(new_incident, "medium"),
                                description=f"{new_incident.value.replace('_', ' ').title()} detected in {service.name}",
                                affected_pods=service.pods
                            )
                        except Exception as e:
                            print(f"Failed to create incident in database: {e}")
                    
                    print(f"Started {new_incident.value} incident on {service.name} (duration: {service.incident_duration}s)")
            
            # Check if we should end current incident
            elif self.should_end_incident(service):
                print(f"Resolved {service.current_incident.value} incident on {service.name}")
                
                # Update incident status in database
                if self.db_enabled and self.db_service and service.current_incident_id:
                    try:
                        self.db_service.update_incident_status(
                            incident_id=service.current_incident_id,
                            status="resolved",
                            end_time=current_time
                        )
                    except Exception as e:
                        print(f"Failed to update incident status in database: {e}")
                
                service.current_incident = None
                service.incident_start_time = None
                service.incident_duration = 0
                service.current_incident_id = None
            
            # Generate metrics and logs for each pod
            for pod in service.pods:
                try:
                    if service.current_incident:
                        elapsed = int((current_time - service.incident_start_time).total_seconds())
                        self.generate_incident_data(service, pod, elapsed)
                    else:
                        self.generate_normal_operation(service, pod)
                        
                except Exception as e:
                    print(f"Error generating data for {service.name}/{pod}: {e}")
                    
        except Exception as e:
            print(f"Error processing service {service.name}: {e}")
            # Reset service state on error
            service.current_incident = None
            service.incident_start_time = None

def run_incident_generator():
    """Enhanced main loop with graceful shutdown"""
    generator = IncidentGenerator()
    print("Enhanced incident generator starting...")
    print(f"Monitoring {len(SERVICES)} services with {sum(len(s.pods) for s in SERVICES)} pods")
    print(f"Safety limits: {generator.max_concurrent_incidents} concurrent incidents max")
    
    try:
        while True:
            try:
                for service in SERVICES:
                    generator.process_service(service)
                
                # Status report every 10 incidents
                if generator.total_incidents_generated % 10 == 0 and generator.total_incidents_generated > 0:
                    active_incidents = [s.name for s in SERVICES if s.current_incident]
                    print(f"Status: {generator.total_incidents_generated} total incidents, {len(active_incidents)} active")
                
                time.sleep(10)  # Generate data every 10 seconds
                
            except KeyboardInterrupt:
                print("Shutdown requested...")
                break
            except Exception as e:
                print(f"Error in main loop: {e}")
                print("Continuing after 30 second pause...")
                time.sleep(30)
                
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        print("Incident generator stopped")

if __name__ == "__main__":
    # Start Prometheus metrics server
    start_http_server(8000)
    print("Metrics endpoint available at :8000/metrics")
    
    # Start incident generation with enhanced error handling
    try:
        run_incident_generator()
    except KeyboardInterrupt:
        print("Incident generator stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")